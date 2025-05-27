# Ref: Arm Debug Interface Architecture Specification ADIv5.0 to ADIv5.2, Issue E
# Accession: G00097
# Document Number: IHI0031E

from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io, cdc
from amaranth.lib.wiring import In, Out, connect, flipped

from glasgow.gateware.ports import PortGroup
from glasgow.gateware.stream import StreamBuffer
from glasgow.gateware.iostream import IOStreamer


__all__ = [
    "Request", "Result", "Header", "Ack", "Driver",
    "Controller", "Command", "Response",
]


class Request(enum.Enum, shape=3):
    Reset  = 0
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


class Enframer(wiring.Component):
    words: In(stream.Signature(data.StructLayout({
        "type": Request,
        "hdr":  Header,
        "data": 32
    })))
    frames: Out(IOStreamer.o_stream_signature({
        "swclk": ("o",  1),
        "swdio": ("io", 1),
    }, meta_layout=Request))
    divisor: In(16)

    def elaborate(self, platform):
        m = Module()

        max_seq_len = 52

        seq_o  = Signal(max_seq_len)
        seq_oe = Signal(max_seq_len)
        seq_ie = Signal(max_seq_len)
        length = Signal(range(max_seq_len))

        with m.Switch(self.words.p.type):
            with m.Case(Request.Reset):
                m.d.comb += seq_o[0:50].eq(~0)
                m.d.comb += seq_o[50:52].eq(0)
                m.d.comb += seq_oe[0:52].eq(~0)
                m.d.comb += length.eq(52)

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
        phase = Signal(len(length) + 1)
        m.d.comb += [
            self.frames.p.port.swclk.o.eq(phase[0]),
            self.frames.p.port.swclk.oe.eq(1),
            self.frames.p.port.swdio.o.eq(seq_o.bit_select(phase[1:], 1)),
            self.frames.p.port.swdio.oe.eq(seq_oe.bit_select(phase[1:], 1)),
            self.frames.p.i_en.eq(seq_ie.bit_select(phase[1:], 1) & phase[0] & (timer == 0)),
            self.frames.p.meta.eq(self.words.p.type),
        ]

        m.d.comb += self.frames.valid.eq(self.words.valid)
        with m.If(self.frames.valid & self.frames.ready):
            with m.If(timer == self.divisor):
                m.d.sync += timer.eq(0)
                with m.If(phase == Cat(1, length - 1)):
                    m.d.sync += phase.eq(0)
                    m.d.comb += self.words.ready.eq(1)
                with m.Else():
                    m.d.sync += phase.eq(phase + 1)
            with m.Else():
                m.d.sync += timer.eq(timer + 1)

        return m


class Deframer(wiring.Component):
    frames: In(IOStreamer.i_stream_signature({
        "swclk": ("o",  1),
        "swdio": ("io", 1),
    }, meta_layout=Request))
    words: Out(stream.Signature(data.StructLayout({
        "type": Result,
        "ack":  Ack,
        "data": 32,
    })))

    def elaborate(self, platform):
        m = Module()

        p_meta = Signal.like(self.frames.p.meta)
        buffer = Signal(33)
        count  = Signal(range(len(buffer) + 1))

        m.d.comb += self.words.p.ack.eq(buffer[-3:])
        m.d.comb += self.words.p.data.eq(buffer[:32])

        m.d.comb += self.words.p.type.eq(Result.Error)
        with m.If(p_meta == Request.Header):
            with m.If(self.words.p.ack.as_value().matches(Ack.OK, Ack.WAIT, Ack.FAULT)):
                m.d.comb += self.words.p.type.eq(Result.Ack)
        with m.If(p_meta == Request.DataRd):
            with m.If(buffer[:32].xor() == buffer[32]):
                m.d.comb += self.words.p.type.eq(Result.Data)

        with m.FSM():
            with m.State("More"):
                m.d.comb += self.frames.ready.eq(1)
                with m.If(self.frames.valid):
                    m.d.sync += p_meta.eq(self.frames.p.meta)
                    m.d.sync += buffer.eq(Cat(buffer[1:], self.frames.p.port.swdio.i))
                    m.d.sync += count.eq(count + 1)
                    with m.If((self.frames.p.meta == Request.Header) & (count == 3 - 1)):
                        m.next = "Done"
                    with m.Elif((self.frames.p.meta == Request.DataRd) & (count == 33 - 1)):
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
        "hdr":  Header,
        "data": 32
    })))
    o_words: Out(stream.Signature(data.StructLayout({
        "type": Result,
        "ack":  Ack,
        "data": 32,
    })))
    divisor: In(16)

    def __init__(self, ports):
        self._ports = PortGroup(swclk=ports.swclk, swdio=ports.swdio)

        super().__init__()

    def elaborate(self, platform):
        ioshape = {
            "swclk": ("o",  1),
            "swdio": ("io", 1),
        }

        m = Module()

        m.submodules.enframer = enframer = Enframer()
        connect(m, controller=flipped(self.i_words), enframer=enframer.words)
        m.d.comb += enframer.divisor.eq(self.divisor)

        m.submodules.io_streamer = io_streamer = IOStreamer(ioshape, self._ports, meta_layout=Request)
        connect(m, enframer=enframer.frames, io_streamer=io_streamer.o_stream)

        m.submodules.deframer = deframer = Deframer()
        connect(m, io_streamer=io_streamer.i_stream, deframer=deframer.frames)

        connect(m, deframer=deframer.words, controller=flipped(self.o_words))

        return m


class Command(enum.Enum, shape=1):
    Transfer = 0
    Reset    = 1


class Response(enum.Enum, shape=2):
    Data   = 0
    NoData = 1
    Error  = 2


class Controller(wiring.Component):
    i_stream: In(stream.Signature(data.StructLayout({
        "cmd":  Command,
        "hdr":  Header,
        "data": 32
    })))
    o_stream: Out(stream.Signature(data.StructLayout({
        "rsp":  Response,
        "ack":  Ack,
        "data": 32,
    })))
    divisor: In(16)
    timeout: In(16, init=~0) # how many times to retry in response to WAIT

    def __init__(self, ports):
        self._ports = ports

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.driver = driver = Driver(self._ports)
        m.d.comb += driver.divisor.eq(self.divisor)

        m.submodules.o_buffer = o_buffer = StreamBuffer(driver.o_words.p.shape())
        wiring.connect(m, o_buffer.i, driver.o_words)

        m.d.comb += driver.i_words.p.hdr.eq(self.i_stream.p.hdr)
        m.d.comb += driver.i_words.p.data.eq(self.i_stream.p.data)

        with m.FSM():
            wait_count = Signal.like(self.timeout, init=0)

            with m.State("Command"):
                with m.If(self.i_stream.valid):
                    m.d.comb += driver.i_words.valid.eq(1)
                    with m.If(self.i_stream.p.cmd == Command.Reset):
                        m.d.comb += driver.i_words.p.type.eq(Request.Reset)
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
