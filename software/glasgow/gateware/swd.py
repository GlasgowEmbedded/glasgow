# Ref: Arm Debug Interface Architecture Specification ADIv5.0 to ADIv5.2, Issue E
# Accession: G00097
# Document Number: IHI0031E

from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io
from amaranth.lib.wiring import In, Out, connect, flipped

from glasgow.gateware.ports import PortGroup
from glasgow.gateware.stream import StreamBuffer
from glasgow.gateware.iostream2 import IOStreamer


__all__ = [
    "Request", "Result", "Header", "Ack", "Driver",
    "Controller", "Command", "Response",
]


class Request(enum.Enum, shape=3):
    Sequence = 0
    Header = 1
    DataWr = 2
    DataRd = 3
    NoData = 4


class Result(enum.Enum, shape=2):
    Ack    = 0
    Data   = 1
    Error  = 2


class Header(data.Struct):
    ap_ndp: 1
    r_nw:   1
    addr:   4 # must be word-aligned

    def as_request(self):
        return Cat(self.ap_ndp, self.r_nw, self.addr[2:4])

    def parity(self):
        return self.as_request().xor()


class Ack(enum.Enum, shape=3):
    OK    = 0b001
    WAIT  = 0b010
    FAULT = 0b100


class Sample(data.Struct):
    type: Request
    half: 1


class Enframer(wiring.Component):
    def __init__(self, ports):
        super().__init__({
            "words":  In(stream.Signature(data.StructLayout({
                "type": Request,
                "len":  range(32), # `type == Request.Sequence` only
                "hdr":  Header,    # `type == Request.Header` only
                "data": 32
            }))),
            "frames":  Out(IOStreamer.i_signature(ports, ratio=2, meta_layout=Sample)),
            "divisor": In(16)
        })

    def elaborate(self, platform):
        m = Module()

        max_seq_len = 34

        seq_o  = Signal(max_seq_len)
        seq_oe = Signal(max_seq_len)
        seq_ie = Signal(max_seq_len)
        length = Signal(range(max_seq_len + 1))

        with m.Switch(self.words.p.type):
            with m.Case(Request.Sequence):
                m.d.comb += seq_o[0:32].eq(self.words.p.data)
                m.d.comb += seq_oe[0:32].eq(~0)
                with m.If(self.words.p.len == 0):
                    m.d.comb += length.eq(32)
                with m.Else():
                    m.d.comb += length.eq(self.words.p.len)

            with m.Case(Request.Header):
                m.d.comb += seq_o[0].eq(1) # start
                m.d.comb += seq_o[1:5].eq(self.words.p.hdr.as_request())
                m.d.comb += seq_o[5].eq(self.words.p.hdr.parity())
                m.d.comb += seq_o[6].eq(0) # stop
                m.d.comb += seq_o[7].eq(1) # park
                m.d.comb += seq_oe[0:8].eq(~0)
                m.d.comb += seq_ie[9:12].eq(~0) # ack
                m.d.comb += length.eq(12)

            with m.Case(Request.DataWr):
                m.d.comb += seq_o[1:33].eq(self.words.p.data)
                m.d.comb += seq_o[33].eq(self.words.p.data.xor())
                m.d.comb += seq_oe[1:34].eq(~0)
                m.d.comb += length.eq(34)

            with m.Case(Request.DataRd):
                m.d.comb += seq_ie[0:33].eq(~0)
                m.d.comb += length.eq(34)

            with m.Case(Request.NoData):
                m.d.comb += length.eq(1)

        timer = Signal.like(self.divisor)
        bitno = Signal.like(length)
        m.d.comb += [
            self.frames.p.port.swclk.o[0].eq(timer * 2 >  self.divisor),
            self.frames.p.port.swclk.o[1].eq(timer * 2 >= self.divisor),
            self.frames.p.port.swclk.oe.eq(1),
            self.frames.p.port.swdio.o.eq(seq_o.bit_select(bitno, 1).replicate(2)),
            self.frames.p.port.swdio.oe.eq(seq_oe.bit_select(bitno, 1)),
        ]
        with m.If(seq_ie.bit_select(bitno, 1) & (timer == (self.divisor + 1) >> 1)):
            m.d.comb += self.frames.p.meta.type.eq(self.words.p.type)
            m.d.comb += self.frames.p.meta.half.eq(~self.divisor[0])

        m.d.comb += self.frames.valid.eq(self.words.valid)
        with m.If(self.frames.valid & self.frames.ready):
            with m.If(timer == self.divisor):
                with m.If(bitno == length - 1):
                    m.d.comb += self.words.ready.eq(1)
                    m.d.sync += bitno.eq(0)
                with m.Else():
                    m.d.sync += bitno.eq(bitno + 1)
                m.d.sync += timer.eq(0)
            with m.Else():
                m.d.sync += timer.eq(timer + 1)

        return m


class Deframer(wiring.Component):
    def __init__(self, ports):
        super().__init__({
            "frames": In(IOStreamer.o_signature(ports, ratio=2, meta_layout=Sample)),
            "words":  Out(stream.Signature(data.StructLayout({
                "type": Result,
                "ack":  Ack,
                "data": 32,
            })))
        })

    def elaborate(self, platform):
        m = Module()

        p_type = Signal(Request)
        buffer = Signal(33)
        count  = Signal(range(len(buffer) + 1))

        m.d.comb += self.words.p.ack.eq(buffer[-3:])
        m.d.comb += self.words.p.data.eq(buffer[:32])

        m.d.comb += self.words.p.type.eq(Result.Error)
        with m.If(p_type == Request.Header):
            with m.If(self.words.p.ack.as_value().matches(Ack.OK, Ack.WAIT, Ack.FAULT)):
                m.d.comb += self.words.p.type.eq(Result.Ack)
        with m.If(p_type == Request.DataRd):
            with m.If(buffer[:32].xor() == buffer[32]):
                m.d.comb += self.words.p.type.eq(Result.Data)

        with m.FSM():
            with m.State("More"):
                m.d.comb += self.frames.ready.eq(1)
                with m.If(self.frames.valid &
                        ((self.frames.p.meta.type == Request.Header) |
                         (self.frames.p.meta.type == Request.DataRd))):
                    m.d.sync += count.eq(count + 1)
                    m.d.sync += buffer.eq(Cat(buffer[1:],
                        self.frames.p.port.swdio.i[self.frames.p.meta.half]))
                    m.d.sync += p_type.eq(self.frames.p.meta.type)
                    with m.If((self.frames.p.meta.type == Request.Header) & (count == 3 - 1)):
                        m.next = "Done"
                    with m.Elif((self.frames.p.meta.type == Request.DataRd) & (count == 33 - 1)):
                        m.next = "Done"

            with m.State("Done"):
                m.d.comb += self.words.valid.eq(1)
                with m.If(self.words.ready):
                    m.d.sync += count.eq(0)
                    m.next = "More"

        return m


class Driver(wiring.Component):
    i_words: In(stream.Signature(data.StructLayout({
        "type": Request,
        "len":  range(32), # `type == Request.Sequence` only
        "hdr":  Header,    # `type == Request.Header` only
        "data": 32
    })))
    o_words: Out(stream.Signature(data.StructLayout({
        "type": Result,
        "ack":  Ack,
        "data": 32,
    })))
    divisor: In(16)

    def __init__(self, ports, *, offset=0):
        self._ports  = PortGroup(
            swclk=ports.swclk.with_direction("o"),
            swdio=ports.swdio.with_direction("io"),
        )
        self._offset = offset

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.enframer = enframer = Enframer(self._ports)
        connect(m, enframer=enframer.words, driver=flipped(self.i_words))
        m.d.comb += enframer.divisor.eq(self.divisor)

        m.submodules.io_streamer = io_streamer = \
            IOStreamer(self._ports, ratio=2, offset=self._offset, meta_layout=Sample)
        connect(m, io_streamer=io_streamer.i, enframer=enframer.frames)

        m.submodules.deframer = deframer = Deframer(self._ports)
        connect(m, deframer=deframer.frames, io_streamer=io_streamer.o)

        connect(m, driver=flipped(self.o_words), deframer=deframer.words)

        return m


class Command(enum.Enum, shape=1):
    Transfer = 0
    Sequence = 1


class Response(enum.Enum, shape=2):
    Data   = 0
    NoData = 1
    Error  = 2


class Controller(wiring.Component):
    i_stream: In(stream.Signature(data.StructLayout({
        "cmd":  Command,
        "hdr":  Header,    # `cmd == Command.Transfer` only
        "len":  range(32), # `cmd == Command.Sequence` only
        "data": 32
    })))
    o_stream: Out(stream.Signature(data.StructLayout({
        "rsp":  Response,
        "ack":  Ack,
        "data": 32,
    })))
    divisor: In(16)
    timeout: In(16, init=~0) # how many times to retry in response to WAIT

    def __init__(self, ports, *, offset=0):
        self._ports  = ports
        self._offset = offset

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.driver = driver = Driver(self._ports, offset=self._offset)
        m.d.comb += driver.divisor.eq(self.divisor)

        m.submodules.o_buffer = o_buffer = StreamBuffer(driver.o_words.p.shape())
        wiring.connect(m, o_buffer.i, driver.o_words)

        m.d.comb += driver.i_words.p.len.eq(self.i_stream.p.len)
        m.d.comb += driver.i_words.p.hdr.eq(self.i_stream.p.hdr)
        m.d.comb += driver.i_words.p.data.eq(self.i_stream.p.data)

        with m.FSM():
            wait_count = Signal.like(self.timeout, init=0)

            with m.State("Command"):
                with m.If(self.i_stream.valid):
                    m.d.comb += driver.i_words.valid.eq(1)
                    with m.If(self.i_stream.p.cmd == Command.Sequence):
                        m.d.comb += driver.i_words.p.type.eq(Request.Sequence)
                        m.d.comb += self.i_stream.ready.eq(driver.i_words.ready)
                    with m.Else():
                        m.d.comb += driver.i_words.p.type.eq(Request.Header)
                        with m.If(driver.i_words.ready):
                            m.next = "Ack Check"

            with m.State("Ack Check"):
                with m.If(o_buffer.o.p.type == Result.Error):
                    m.d.sync += self.o_stream.p.rsp.eq(Response.Error)
                with m.Else():
                    m.d.sync += self.o_stream.p.rsp.eq(Response.NoData)
                m.d.sync += self.o_stream.p.ack.eq(o_buffer.o.p.ack)
                m.d.comb += o_buffer.o.ready.eq(1)
                with m.If(o_buffer.o.valid):
                    with m.If(o_buffer.o.p.type == Result.Error):
                        m.next = "Response"
                    with m.Elif((o_buffer.o.p.type == Result.Ack) &
                              (o_buffer.o.p.ack == Ack.WAIT)):
                        m.next = "Wait Retry"
                    with m.Elif((o_buffer.o.p.type == Result.Ack) &
                              (o_buffer.o.p.ack == Ack.FAULT)):
                        m.next = "Fault Response"
                    with m.Elif(self.i_stream.p.hdr.r_nw):
                        m.next = "Read Data (Request)"
                    with m.Else():
                        m.next = "Write Data"

            with m.State("Wait Retry"):
                m.d.comb += driver.i_words.p.type.eq(Request.NoData)
                m.d.comb += driver.i_words.valid.eq(1)
                with m.If(driver.i_words.ready):
                    with m.If(wait_count == self.timeout):
                        m.next = "Response" # timed out, reply with WAIT
                    with m.Else():
                        m.d.sync += wait_count.eq(wait_count + 1)
                        m.next = "Command" # resend the command

            with m.State("Fault Response"):
                m.d.comb += driver.i_words.p.type.eq(Request.NoData)
                m.d.comb += driver.i_words.valid.eq(1)
                with m.If(driver.i_words.ready):
                    m.next = "Response"

            with m.State("Write Data"):
                m.d.comb += driver.i_words.p.type.eq(Request.DataWr)
                m.d.comb += driver.i_words.valid.eq(1)
                with m.If(driver.i_words.ready):
                    m.next = "Response"

            with m.State("Read Data (Request)"):
                m.d.comb += driver.i_words.p.type.eq(Request.DataRd)
                m.d.comb += driver.i_words.valid.eq(1)
                with m.If(driver.i_words.ready):
                    m.next = "Read Data (Result)"

            with m.State("Read Data (Result)"):
                with m.If(o_buffer.o.p.type == Result.Error):
                    m.d.sync += self.o_stream.p.rsp.eq(Response.Error)
                with m.Else():
                    m.d.sync += self.o_stream.p.rsp.eq(Response.Data)
                m.d.sync += self.o_stream.p.data.eq(o_buffer.o.p.data)
                m.d.comb += o_buffer.o.ready.eq(1)
                with m.If(o_buffer.o.valid):
                    m.next = "Response"

            with m.State("Response"):
                m.d.comb += self.o_stream.valid.eq(1)
                with m.If(self.o_stream.ready):
                    m.d.comb += self.i_stream.ready.eq(1)
                    m.d.sync += wait_count.eq(0)
                    m.next = "Command"

        return m
