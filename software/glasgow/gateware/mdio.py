# Ref: IEEE Std 802.3-2018 §22.2.2.14, §22.2.4, §22.3.4
# Accession: G00098

from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io
from amaranth.lib.wiring import In, Out, connect, flipped

from glasgow.gateware.ports import PortGroup
from glasgow.gateware.iostream import IOStreamer


__all__ = ["Request", "Controller"]


class Request(enum.Enum, shape=1):
    Read  = 0
    Write = 1


class Enframer(wiring.Component):
    def __init__(self, ports):
        super().__init__({
            "packets": In(stream.Signature(data.StructLayout({
                "type": Request,
                "phy":  5,
                "reg":  5,
                "data": 16, # `type == Request.Write` only
            }))),
            "frames":  Out(IOStreamer.i_signature(ports, meta_layout=1)),
            "divisor": In(16)
        })

    def elaborate(self, platform):
        m = Module()

        packet_len = 64
        seq_o  = Signal(packet_len)
        seq_oe = Signal(packet_len)
        seq_ie = Signal(packet_len)

        m.d.comb += seq_o[0:32].eq(~0)
        m.d.comb += seq_o[32].eq(0)
        m.d.comb += seq_o[33].eq(1)
        m.d.comb += seq_o[34].eq(~self.packets.p.type.as_value())
        m.d.comb += seq_o[35].eq(self.packets.p.type.as_value())
        m.d.comb += seq_o[36:41].eq(self.packets.p.phy[::-1])
        m.d.comb += seq_o[41:46].eq(self.packets.p.reg[::-1])
        m.d.comb += seq_o[46].eq(1)
        m.d.comb += seq_o[47].eq(0)
        m.d.comb += seq_o[48:64].eq(self.packets.p.data[::-1])
        with m.Switch(self.packets.p.type):
            with m.Case(Request.Read):
                m.d.comb += seq_oe[ 0:46].eq(~0)
                m.d.comb += seq_ie[48:64].eq(~0)
            with m.Case(Request.Write):
                m.d.comb += seq_oe[ 0:64].eq(~0)

        timer = Signal.like(self.divisor)
        phase = Signal(range(128))
        m.d.comb += [
            self.frames.p.port.mdc.o.eq(phase[0]),
            self.frames.p.port.mdc.oe.eq(1),
            self.frames.p.port.mdio.o.eq(seq_o.bit_select(phase[1:], 1)),
            self.frames.p.port.mdio.oe.eq(seq_oe.bit_select(phase[1:], 1)),
        ]
        with m.If(seq_ie.bit_select(phase[1:], 1) & phase[0] & (timer == 0)):
            m.d.comb += self.frames.p.meta.eq(1)

        m.d.comb += self.frames.valid.eq(self.packets.valid)
        with m.If(self.frames.valid & self.frames.ready):
            with m.If(timer == self.divisor):
                with m.If(phase == 127):
                    m.d.comb += self.packets.ready.eq(1)
                    m.d.sync += phase.eq(0)
                with m.Else():
                    m.d.sync += phase.eq(phase + 1)
                m.d.sync += timer.eq(0)
            with m.Else():
                m.d.sync += timer.eq(timer + 1)

        return m


class Deframer(wiring.Component):
    def __init__(self, ports):
        super().__init__({
            "frames":  In(IOStreamer.o_signature(ports, meta_layout=1)),
            "packets": Out(stream.Signature(data.StructLayout({
                "data": 16,
            })))
        })

    def elaborate(self, platform):
        m = Module()

        count = Signal(range(16))
        with m.FSM():
            with m.State("More"):
                m.d.comb += self.frames.ready.eq(1)
                with m.If(self.frames.valid & self.frames.p.meta):
                    m.d.sync += self.packets.p.data.eq(
                        Cat(self.frames.p.port.mdio.i, self.packets.p.data))
                    m.d.sync += count.eq(count + 1)
                    with m.If(count == 15):
                        m.next = "Done"

            with m.State("Done"):
                m.d.comb += self.packets.valid.eq(1)
                with m.If(self.packets.ready):
                    m.next = "More"

        return m


# This controller implementation is very simple and does not automate access via MMD / Clause 45
# indirect registers. It is expected that most uses will consist of initializing a PHY from
# a sequence of accesses, where native support for Clause 45 is unimportant. If it gets important,
# this `Controller` should be renamed to a `Driver` and wrapped into a new `Controller` component
# implementing higher-level commands.
class Controller(wiring.Component):
    i_stream: In(stream.Signature(data.StructLayout({
        "type": Request,
        "phy":  5,
        "reg":  5,
        "data": 16, # `type == Request.Write` only
    })))
    o_stream: Out(stream.Signature(data.StructLayout({
        "data": 16,
    })))
    divisor: In(16)

    def __init__(self, ports):
        self._ports = PortGroup(
            mdc=ports.mdc.with_direction("o"),
            mdio=ports.mdio.with_direction("io"),
        )

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.enframer = enframer = Enframer(self._ports)
        connect(m, enframer=enframer.packets, driver=flipped(self.i_stream))
        m.d.comb += enframer.divisor.eq(self.divisor)

        m.submodules.io_streamer = io_streamer = \
            IOStreamer(self._ports, meta_layout=1, init={
                "mdc": {"o": 0, "oe": 1}
            })
        connect(m, io_streamer=io_streamer.i, enframer=enframer.frames)

        m.submodules.deframer = deframer = Deframer(self._ports)
        connect(m, deframer=deframer.frames, io_streamer=io_streamer.o)

        connect(m, driver=flipped(self.o_stream), deframer=deframer.packets)

        return m
