import operator

from amaranth import *
from amaranth.hdl._ir import RequirePosedge
from amaranth.lib import wiring, io, data
from amaranth.vendor import LatticeECP5Platform

from . import GlasgowPlatform


__all__ = ["GlasgowECP5Platform"]


class GlasgowECP5Platform(GlasgowPlatform, LatticeECP5Platform):
    def bitstream_filename(self, design_name):
        return f"{design_name}.bit"


# This is copied from `amaranth.vendor._lattice.InnerBuffer` as-is.
class _InnerBuffer(wiring.Component):
    """A private component used to implement ``lib.io`` buffers.

    Works like ``lib.io.Buffer``, with the following differences:

    - ``port.invert`` is ignored (handling the inversion is the outer buffer's responsibility)
    - ``t`` is per-pin inverted output enable
    """

    def __init__(self, direction, port):
        self.direction = direction
        self.port = port
        members = {}
        if direction is not io.Direction.Output:
            members["i"] = wiring.In(len(port))
        if direction is not io.Direction.Input:
            members["o"] = wiring.Out(len(port))
            members["t"] = wiring.Out(len(port))
        super().__init__(wiring.Signature(members).flip())

    def elaborate(self, platform):
        m = Module()

        if isinstance(self.port, io.SingleEndedPort):
            io_port = self.port.io
        elif isinstance(self.port, io.DifferentialPort):
            io_port = self.port.p
        else:
            raise TypeError(f"Unknown port type {self.port!r}")

        for bit in range(len(self.port)):
            name = f"buf{bit}"
            if self.direction is io.Direction.Input:
                m.submodules[name] = Instance("IB",
                    i_I=io_port[bit],
                    o_O=self.i[bit],
                )
            elif self.direction is io.Direction.Output:
                m.submodules[name] = Instance("OBZ",
                    i_T=self.t[bit],
                    i_I=self.o[bit],
                    o_O=io_port[bit],
                )
            elif self.direction is io.Direction.Bidir:
                m.submodules[name] = Instance("BB",
                    i_T=self.t[bit],
                    i_I=self.o[bit],
                    o_O=self.i[bit],
                    io_B=io_port[bit],
                )
            else:
                assert False # :nocov:

        return m


# Patterned after `io.DDRBuffer`, but with somewhat more questionable design choices. Would likely
# not be accepted upstream as-is for a number of reasons; a major one is that IDDRX2F.ALIGNWD input
# is not connected at all.
class QDRBuffer(wiring.Component):
    class Signature(wiring.Signature):
        def __init__(self, direction, width):
            self._direction = io.Direction(direction)
            self._width = operator.index(width)
            members = {}
            if self._direction is not io.Direction.Output:
                members["i"] = wiring.In(data.ArrayLayout(self._width, 4))
            if self._direction is not io.Direction.Input:
                members["o"] = wiring.Out(data.ArrayLayout(self._width, 4))
                members["oe"] = wiring.Out(1, init=int(self._direction is io.Direction.Output))
            super().__init__(members)

        @property
        def direction(self):
            return self._direction

        @property
        def width(self):
            return self._width

        def __eq__(self, other):
            return (type(self) is type(other) and self.direction == other.direction and
                    self.width == other.width)

        def __repr__(self):
            return f"QDRBuffer.Signature({self.direction}, {self.width})"

    def __init__(self, direction, port, *, i_domain=None, o_domain=None):
        if not isinstance(port, io.PortLike):
            raise TypeError(f"'port' must be a 'PortLike', not {port!r}")
        self._port = port
        super().__init__(QDRBuffer.Signature(direction, len(port)).flip())
        if self.signature.direction is not io.Direction.Output:
            self._i_domain = i_domain or "sync"
        else:
            if i_domain is not None:
                raise ValueError("Output buffer doesn't have an input domain")
            self._i_domain = None
        if self.signature.direction is not io.Direction.Input:
            self._o_domain = o_domain or "sync"
        else:
            if o_domain is not None:
                raise ValueError("Input buffer doesn't have an output domain")
            self._o_domain = None
        if port.direction is io.Direction.Input and self.direction is not io.Direction.Input:
            raise ValueError(f"Input port cannot be used with {self.direction.name} buffer")
        if port.direction is io.Direction.Output and self.direction is not io.Direction.Output:
            raise ValueError(f"Output port cannot be used with {self.direction.name} buffer")

    @property
    def port(self):
        return self._port

    @property
    def direction(self):
        return self.signature.direction

    @property
    def i_domain(self):
        return self._i_domain

    @property
    def o_domain(self):
        return self._o_domain

    def elaborate(self, platform):
        assert isinstance(platform, LatticeECP5Platform), "QDR buffers are only supported on ECP5"

        m = Module()

        m.submodules.buf = buf = _InnerBuffer(self.direction, self.port)
        inv_mask = sum(inv << bit for bit, inv in enumerate(self.port.invert))

        if self.direction is not io.Direction.Output:
            m.submodules += RequirePosedge(self.i_domain)
            i0_inv = Signal(len(self.port))
            i1_inv = Signal(len(self.port))
            i2_inv = Signal(len(self.port))
            i3_inv = Signal(len(self.port))
            for bit in range(len(self.port)):
                m.submodules[f"i_ddr{bit}"] = Instance("IDDRX2F",
                    # https://github.com/YosysHQ/nextpnr/issues/1749
                    # i_ALIGNWD=0,
                    i_SCLK=ClockSignal(self.i_domain),
                    i_ECLK=ClockSignal("edge"),
                    i_RST=ResetSignal("edge"),
                    i_D=buf.i[bit],
                    o_Q0=i0_inv[bit],
                    o_Q1=i1_inv[bit],
                    o_Q2=i2_inv[bit],
                    o_Q3=i3_inv[bit],
                )
            m.d.comb += self.i[0].eq(i0_inv ^ inv_mask)
            m.d.comb += self.i[1].eq(i1_inv ^ inv_mask)
            m.d.comb += self.i[2].eq(i2_inv ^ inv_mask)
            m.d.comb += self.i[3].eq(i3_inv ^ inv_mask)

        if self.direction is not io.Direction.Input:
            m.submodules += RequirePosedge(self.o_domain)
            o0_inv = Signal(len(self.port))
            o1_inv = Signal(len(self.port))
            o2_inv = Signal(len(self.port))
            o3_inv = Signal(len(self.port))
            m.d.comb += [
                o0_inv.eq(self.o[0] ^ inv_mask),
                o1_inv.eq(self.o[1] ^ inv_mask),
                o2_inv.eq(self.o[2] ^ inv_mask),
                o3_inv.eq(self.o[3] ^ inv_mask),
            ]
            for bit in range(len(self.port)):
                m.submodules[f"o_ddr{bit}"] = Instance("ODDRX2F",
                    i_SCLK=ClockSignal(self.o_domain),
                    i_ECLK=ClockSignal("edge"),
                    i_RST=ResetSignal("edge"),
                    i_D0=o0_inv[bit],
                    i_D1=o1_inv[bit],
                    i_D2=o2_inv[bit],
                    i_D3=o3_inv[bit],
                    o_Q=buf.o[bit],
                )

            oe = ~self.oe
            for stage in range(2):
                oe_reg = Signal(name=f"oe_delay{stage}")
                m.d[self.o_domain] += oe_reg.eq(oe)
                oe = oe_reg
            for bit in range(len(buf.t)):
                m.submodules[f"oe_ff{bit}"] = Instance("OFS1P3DX",
                    i_SCLK=ClockSignal(self.o_domain),
                    i_SP=Const(1),
                    i_CD=ResetSignal("edge"),
                    i_D=oe,
                    o_Q=buf.t[bit],
                )

        return m
