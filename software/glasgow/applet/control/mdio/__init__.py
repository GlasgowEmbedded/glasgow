# Ref: IEEE Std 802.3-2018 §22.2.2.14, §22.2.4, §22.3.4, §45
# Accession: G00098

# It's difficult to give this applet a technically accurate name because there is a lot of overlap
# between Clause 22 (the old interface, MIIM) and Clause 45 (the new interface, MDIO), with address
# spaces being orthogonal and electrical interfaces being almost entirely compatible.
# The IEEE 802.3 document uses these terms in very precise ways that do not match real-world use
# (nobody uses the term "MIIM", and everybody uses "MDIO" for both Clause 22 and Clause 45).
# We use "MDIO" to match practical use.

import struct
import logging

from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io
from amaranth.lib.wiring import In, Out

from glasgow.arch.ieee802_3 import *
from glasgow.gateware import mdio
from glasgow.abstract import GlasgowPin, AbstractAssembly
from glasgow.applet import GlasgowAppletV2


__all__ = ["ControlMDIOInterface"]


class ControlMDIOHeader(data.Struct):
    type: mdio.Request
    phy:  5
    reg:  5
    _:    5


class ControlMDIOComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))

    divisor: In(16)

    def __init__(self, ports):
        self._ports = ports

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.ctrl = ctrl = mdio.Controller(self._ports)
        m.d.comb += ctrl.divisor.eq(self.divisor)

        i_header = Signal(ControlMDIOHeader)
        m.d.comb += ctrl.i_stream.p.type.eq(i_header.type)
        m.d.comb += ctrl.i_stream.p.phy.eq(i_header.phy)
        m.d.comb += ctrl.i_stream.p.reg.eq(i_header.reg)

        i_count = Signal(range(2))
        with m.FSM(name="i_fsm"):
            with m.State("Receive Header"):
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    m.d.sync += i_header.as_value().word_select(i_count[0], 8).eq(self.i_stream.payload)
                    m.d.sync += i_count.eq(i_count + 1)
                    with m.If(i_count == 1):
                        with m.If(i_header.type == mdio.Request.Write):
                            m.next = "Receive Data"
                        with m.Else():
                            m.next = "Submit"

            with m.State("Receive Data"):
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    m.d.sync += ctrl.i_stream.p.data.word_select(i_count[0], 8).eq(self.i_stream.payload)
                    m.d.sync += i_count.eq(i_count + 1)
                    with m.If(i_count == 1):
                        m.next = "Submit"

            with m.State("Submit"):
                m.d.comb += ctrl.i_stream.valid.eq(1)
                with m.If(ctrl.i_stream.ready):
                    m.next = "Receive Header"

        o_count = Signal(range(2))
        m.d.comb += self.o_stream.payload.eq(ctrl.o_stream.p.data.word_select(o_count, 8))
        m.d.comb += self.o_stream.valid.eq(ctrl.o_stream.valid)
        with m.If(self.o_stream.valid & self.o_stream.ready):
            m.d.sync += o_count.eq(o_count + 1)
            with m.If(o_count == 1):
                m.d.comb += ctrl.o_stream.ready.eq(1)

        return m


class ControlMDIOInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 mdc: GlasgowPin, mdio: GlasgowPin):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        assembly.use_pulls({mdio: "low"})
        ports = assembly.add_port_group(mdc=mdc, mdio=mdio)
        component = assembly.add_submodule(ControlMDIOComponent(ports))
        self._pipe = assembly.add_inout_pipe(component.o_stream, component.i_stream)
        self._clock = assembly.add_clock_divisor(component.divisor,
            ref_period=assembly.sys_clk_period * 2, name="mdc")

    def _log(self, message: str, *args):
        self._logger.log(self._level, "MDIO: " + message, *args)

    @property
    def clock(self):
        return self._clock

    async def _read(self, phy: int, reg: int) -> int:
        await self._pipe.send(struct.pack("<H", ControlMDIOHeader.const({
            "type": mdio.Request.Read, "phy": phy, "reg": reg
        }).as_value().value))
        await self._pipe.flush()
        value, = struct.unpack("<H", await self._pipe.recv(2))
        return value

    async def _write(self, phy: int, reg: int, value: int):
        await self._pipe.send(struct.pack("<HH", ControlMDIOHeader.const({
            "type": mdio.Request.Write, "phy": phy, "reg": reg
        }).as_value().value, value))
        await self._pipe.flush()

    async def c22_read(self, phy: int, reg: int) -> int:
        """Read Clause 22 (SMI/MIIM) register ``reg`` of PHY ``phy``."""
        assert phy in range(32) and reg in range(32)
        value = await self._read(phy, reg)
        self._log(f"c22 rd phy={phy} reg={reg:#04x} data={value:#06x}")
        return value

    async def c22_write(self, phy: int, reg: int, value: int):
        """Write ``value`` to Clause 22 (MIIM) register ``reg`` of PHY ``phy``."""
        assert phy in range(32) and reg in range(32) and value in range(0x10000)
        self._log(f"c22 wr phy={phy} reg={reg:#04x} data={value:#06x}")
        await self._write(phy, reg, value)

    async def _c45_select(self, phy: int, dev: int, reg: int):
        await self._write(phy, REG_MMDCTRL_addr,
            REG_MMDCTRL(DEVAD=dev, FNCTN=MMD_FNCTN.Address.value).to_int())
        await self._write(phy, REG_MMDAD_addr, reg)
        await self._write(phy, REG_MMDCTRL_addr,
            REG_MMDCTRL(DEVAD=dev, FNCTN=MMD_FNCTN.Data_NoInc.value).to_int())

    async def c45_read(self, phy: int, dev: int, reg: int) -> int:
        """Read Clause 45 (MDIO) register ``reg`` of MMD ``dev`` of PHY ``phy``."""
        assert phy in range(32) and reg in range(0x10000)
        await self._c45_select(phy, dev, reg)
        value = await self._read(phy, REG_MMDAD_addr)
        self._log(f"c45 rd phy={phy} dev={dev} reg={reg:#04x} data={value:#06x}")
        return value

    async def c45_write(self, phy: int, dev: int, reg: int, value: int):
        """Write ``value`` to Clause 45 (MDIO) register ``reg`` of MMD ``dev`` of PHY ``phy``."""
        assert phy in range(32) and reg in range(0x10000) and value in range(0x10000)
        self._log(f"c45 wr phy={phy} dev={dev} reg={reg:#04x} data={value:#06x}")
        await self._c45_select(phy, dev, reg)
        await self._write(phy, REG_MMDAD_addr, value)


class ControlMDIOApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "configure IEEE 802.3 (Ethernet) PHYs via MDIO interface"
    description = """
    Configure Ethernet PHYs and query their status via the standard two-wire MDC/MDIO management
    interface. Both Clause 22 and Clause 45 operations are supported.
    """
    required_revision = "C0" # IEEE 802.3 requires pull-ups/pull-downs on MDIO

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "mdc",  required=True, default=True)
        access.add_pins_argument(parser, "mdio", required=True, default=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.mdio_iface = ControlMDIOInterface(self.logger, self.assembly,
                mdc=args.mdc, mdio=args.mdio)

    @classmethod
    def add_setup_arguments(cls, parser):
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=1000,
            help="set MDC frequency to FREQ kHz (default: %(default)s)")

    async def setup(self, args):
        await self.mdio_iface.clock.set_frequency(args.frequency * 1000)

    @classmethod
    def tests(cls):
        from . import test
        return test.ControlMDIOAppletTestCase
