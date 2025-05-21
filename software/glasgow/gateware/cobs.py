from amaranth import *
from amaranth.lib import data, wiring, memory, stream
from amaranth.lib.stream import In, Out


__all__ = ["Encoder", "Decoder"]


class Encoder(wiring.Component):
    """`Consistent Overhead Byte Stuffing <cobs>`_ encoder combined with a FIFO.

    The encoder accepts a stream of tokens, which can be either _data_ or _end_, and produces
    a stream of bytes. Input data tokens produce non-NUL output bytes with a maximum latency
    of 256 cycles; input end tokens produce NUL output bytes.

    Since COBS encoding requires up to 254 bytes of lookahead, and a COBS encoder will be usually
    combined with a FIFO (either at the input or at the output), this encoder is combined with
    a FIFO to use limited memory resources more efficiently. All but one byte of the internal FIFO
    will be filled with data in case of output back-pressure.

    The latency of the encoder depends on the type and value of input tokens. Input non-NUL data
    tokens do not immediately produce output bytes; rather, bytes corresponding to these tokens
    appear at the output only after: (a) an input end token, or (b) an input NUL data token, or
    (c) 255th consecutive non-NUL data token.

    .. _cobs: https://en.wikipedia.org/wiki/Consistent_Overhead_Byte_Stuffing
    """

    i: In(stream.Signature(data.StructLayout({
        "data": 8,
        "end":  1
    })))
    o: Out(stream.Signature(8))

    def __init__(self, fifo_depth=256):
        if not (fifo_depth >= 256 and fifo_depth.bit_count() == 1):
            raise ValueError("COBS encoder requires a power-of-2 sized FIFO that is "
                             "at least 256 bytes deep")
        self.fifo_depth = fifo_depth

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # This implementation improves resource use efficiency by merging the two memories that
        # would otherwise be necessary in a typical implementation: the FIFO for buffering packet
        # data, and the lookahead memory for COBS encoding. Specifically, it reuses the "empty"
        # space in the FIFO for storing bytes that follow a yet-unknown COBS overhead byte; this is
        # called "staging". Once the value of the overhead byte becomes known, the FIFO write
        # pointer is advanced simultaneously with the overhead byte being overwriten; this is
        # called "committing".

        m.submodules.data = data = memory.Memory(shape=8, depth=self.fifo_depth, init=[])
        w_port = data.write_port()
        r_port = data.read_port(transparent_for=(w_port,))

        w_addr = Signal.like(w_port.addr)
        r_addr = Signal.like(r_port.addr)
        empty  = (w_addr == r_addr)
        full   = (w_addr == r_addr - 1)

        def write(at, data):
            m.d.comb += w_port.addr.eq(at)
            m.d.comb += w_port.data.eq(data)
            m.d.comb += w_port.en.eq(1)

        staged = Signal(8, init=1)

        def stage(data):
            write(w_addr + staged, data)
            m.d.sync += staged.eq(staged + 1)

        def commit():
            write(w_addr, staged)
            m.d.sync += w_addr.eq(w_addr + staged)
            m.d.sync += staged.eq(1)

        with m.FSM():
            with m.State("Data"):
                with m.If(self.i.valid & ~full):
                    with m.If(self.i.p.end):
                        m.d.comb += self.i.ready.eq(1)
                        commit()
                        m.next = "End"
                    with m.Elif(staged == 0xff):
                        commit()
                    with m.Elif(self.i.p.data == 0x00):
                        m.d.comb += self.i.ready.eq(1)
                        commit()
                    with m.Else():
                        m.d.comb += self.i.ready.eq(1)
                        stage(self.i.p.data)

            with m.State("End"):
                with m.If(~full):
                    write(w_addr, 0x00)
                    m.d.sync += w_addr.eq(w_addr + 1)
                    m.next = "Data"

        m.d.comb += self.o.valid.eq(~empty)
        m.d.comb += self.o.payload.eq(r_port.data)
        with m.If(self.o.valid & self.o.ready):
            m.d.comb += r_port.addr.eq(r_addr + 1)
            m.d.sync += r_addr.eq(r_addr + 1)
        with m.Else():
            m.d.comb += r_port.addr.eq(r_addr)

        return m


class Decoder(wiring.Component):
    """`Consistent Overhead Byte Stuffing <cobs>`_ decoder.

    Performs an inversion of the transformation done by :class:`Encoder` with a fixed 0 cycle
    latency.

    If invalid COBS data is encountered (namely: if a group header byte or data byte is NUL),
    the decoder transitions to an error state, signaled by the ``error`` output. This state is
    final, cleared only by a reset.

    .. _cobs: https://en.wikipedia.org/wiki/Consistent_Overhead_Byte_Stuffing
    """

    i: In(stream.Signature(8))
    o: Out(stream.Signature(data.StructLayout({
        "data": 8,
        "end":  1
    })))
    error: Out(1)

    def elaborate(self, platform):
        m = Module()

        count  = Signal(8)
        offset = Signal(8)

        with m.FSM():
            with m.State("Start"):
                m.d.comb += self.i.ready.eq(1)
                with m.If(self.i.valid & self.i.ready):
                    m.d.sync += count.eq(1)
                    with m.If(self.i.payload != 0x00):
                        m.d.sync += offset.eq(self.i.payload)
                        m.next = "Data"
                    with m.Else():
                        m.next = "Error"

            with m.State("Data"):
                m.d.comb += self.i.ready.eq(self.o.ready)
                with m.If(self.i.valid & self.i.ready):
                    with m.If(offset == count):
                        m.d.sync += count.eq(1)
                        with m.If(self.i.payload == 0x00):
                            m.d.comb += self.o.payload.end.eq(1)
                            m.d.comb += self.o.valid.eq(1)
                            m.next = "Start"
                        with m.Else():
                            m.d.comb += self.o.payload.data.eq(0x00)
                            m.d.comb += self.o.valid.eq(offset != 0xff)
                            m.d.sync += offset.eq(self.i.payload)
                    with m.Else():
                        m.d.sync += count.eq(count + 1)
                        with m.If(self.i.payload != 0x00):
                            m.d.comb += self.o.payload.data.eq(self.i.payload)
                            m.d.comb += self.o.valid.eq(1)
                        with m.Else():
                            m.next = "Error"

            with m.State("Error"):
                m.d.comb += self.error.eq(1)

        return m
