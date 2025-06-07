from amaranth import *
from amaranth.lib import data, wiring, stream, crc
from amaranth.lib.wiring import In, Out


__all__ = ["ChecksumAppender", "ChecksumVerifier"]


class ChecksumAppender(wiring.Component):
    """Appends a CRC checksum to packets.

    Packet data is cut through with a latency of 0. After the last payload of the packet,
    the CRC value is output from LSB to MSB. (This order enables verifying the packet checksum
    by comparing the running CRC with the residue.)
    """

    def __init__(self, algorithm: crc.Algorithm, *, data_width=8):
        if algorithm.crc_width % data_width != 0:
            raise ValueError("CRC width must be divisible by data width")

        self._parameters = algorithm(data_width)

        super().__init__({
            "i": In(stream.Signature(data.StructLayout({
                "data":  data_width,
                "first": 1,
                "last":  1,
            }))),
            "o": Out(stream.Signature(data.StructLayout({
                "data":  data_width,
                "first": 1,
                "last":  1,
            })))
        })

    def elaborate(self, platform):
        m = Module()

        m.submodules.engine = engine = self._parameters.create()
        m.d.comb += engine.data.eq(self.i.p.data)

        with m.FSM():
            with m.State("Data"):
                wiring.connect(m, wiring.flipped(self.o), wiring.flipped(self.i))
                with m.If(self.i.valid & self.i.ready):
                    m.d.comb += engine.valid.eq(1)
                    m.d.comb += engine.start.eq(self.i.p.first)
                    with m.If(self.i.p.last):
                        m.d.comb += self.o.p.last.eq(0)
                        m.next = "CRC"

            with m.State("CRC"):
                length = len(engine.crc) // len(self.o.p.data)
                offset = Signal(range(length))

                m.d.comb += self.o.p.data.eq(engine.crc.word_select(offset, len(self.o.p.data)))
                m.d.comb += self.o.p.last.eq(offset == length - 1)
                m.d.comb += self.o.valid.eq(1)
                with m.If(self.o.ready):
                    m.d.sync += offset.eq(offset + 1)
                    with m.If(self.o.p.last):
                        m.next = "Data"

        return m


class ChecksumVerifier(wiring.Component):
    """Verifies a CRC checksum at the end of a packet.

    Packet data is cut through with a latency of ``algorithm.crc_width // data_width + 1``, with
    the checksum removed. ``last`` is asserted for the last payload of the packet if and only if
    the checksum matches.
    """

    def __init__(self, algorithm: crc.Algorithm, *, data_width=8):
        if algorithm.crc_width % data_width != 0:
            raise ValueError("CRC width must be divisible by data width")

        self._parameters = algorithm(data_width)

        super().__init__({
            "i": In(stream.Signature(data.StructLayout({
                "data":  data_width,
                "first": 1,
                "last":  1,
                "end":   1,
            }))),
            "o": Out(stream.Signature(data.StructLayout({
                "data":  data_width,
                "first": 1,
                "last":  1,
            })))
        })

    def elaborate(self, platform):
        m = Module()

        m.submodules.engine = engine = self._parameters.create()

        length = len(engine.crc) // len(self.o.p.data)
        buffer = Signal(data.ArrayLayout(self.i.p.data.shape(), length + 1))
        offset = Signal(range(len(buffer) + 1))

        m.d.comb += [
            engine.data.eq(self.i.p.data),
            engine.start.eq(self.i.valid & ~self.i.p.end & self.i.p.first),
            engine.valid.eq(self.i.valid & ~self.i.p.end & self.i.ready),
            self.o.p.data.eq(buffer[-1]),
            self.o.p.first.eq(offset == length),
        ]
        with m.FSM():
            with m.State("Data"):
                m.d.comb += self.o.valid.eq(
                    self.i.valid & (offset >= length) & ~(self.i.p.first & ~self.i.p.end))
                m.d.comb += self.i.ready.eq(
                    self.o.ready | (offset <  length) |  (self.i.p.first & ~self.i.p.end))
                with m.If(self.i.valid & self.i.ready):
                    m.d.sync += buffer.eq(Cat(self.i.p.data, buffer))
                    with m.If(self.i.p.first):
                        m.d.sync += offset.eq(0)
                    with m.Elif(offset <= length): # saturate at `length + 1`
                        m.d.sync += offset.eq(offset + 1)
                    with m.If((offset >= length - 1) & self.i.p.last):
                        m.next = "Last"
                    with m.If(self.i.p.end):
                        m.d.comb += self.o.p.last.eq(engine.match_detected & (offset >= length))
                        m.d.sync += offset.eq(0)

            with m.State("Last"):
                m.d.comb += self.o.valid.eq(1)
                m.d.comb += self.o.p.last.eq(engine.match_detected)
                with m.If(self.o.ready):
                    m.d.sync += offset.eq(0)
                    m.next = "Data"

        return m
