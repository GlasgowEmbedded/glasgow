import logging
import asyncio

from amaranth import *
from amaranth.lib import enum, wiring, io, cdc
from amaranth.lib.wiring import In, Out

from glasgow.arch.ieee802_3 import *
from glasgow.gateware.ethernet import AbstractDriver
from glasgow.gateware.iostream import StreamIOBuffer
from glasgow.gateware.ports import PortGroup
from glasgow.gateware.pll import PLL
from glasgow.abstract import AbstractAssembly, GlasgowPin
from glasgow.applet.interface.ethernet import AbstractEthernetInterface, AbstractEthernetApplet
from glasgow.applet.control.mdio import ControlMDIOInterface


__all__ = ["EthernetRGMIIDriver", "EthernetRGMIIInterface"]


class IODelay(wiring.Elaboratable):
    def __init__(self, i, o, *, length=8): # approx. 5 ns by default
        self.i = i
        self.o = o
        self.length = length
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        i = self.i
        for n in range(self.length):
            o = Signal()
            m.submodules[f"lut{n}"] = Instance("SB_LUT4",
                a_keep=1,
                p_LUT_INIT=C(2, 16),
                i_I0=i,
                i_I1=C(0),
                i_I2=C(0),
                i_I3=C(0),
                o_O=o)
            i = o
        m.d.comb += self.o.eq(o)

        return m


class EthernetRGMIIDriver(AbstractDriver):
    class Mode(enum.Enum, shape=1):
        _1000M   = 0
        _10_100M = 1

    def __init__(self, ports):
        self._ports  = ports

        self._tx_delay = True
        self._rx_delay = True

        super().__init__({
            "mode": In(self.Mode, init=self.Mode._10_100M),
        })

    def elaborate(self, platform):
        m = Module()

        m.submodules.tx_clk_buffer  = tx_clk_buffer  = io.Buffer("o", self._ports.tx_clk)
        m.submodules.tx_ctl_buffer  = tx_ctl_buffer  = io.Buffer("o", self._ports.tx_ctl)
        m.submodules.tx_data_buffer = tx_data_buffer = io.Buffer("o", self._ports.tx_data)

        m.submodules.rx_clk_buffer  = rx_clk_buffer  = io.Buffer("i", self._ports.rx_clk)
        m.submodules.rx_ctl_buffer  = rx_ctl_buffer  = io.Buffer("i", self._ports.rx_ctl)
        m.submodules.rx_data_buffer = rx_data_buffer = io.Buffer("i", self._ports.rx_data)

        m.submodules.rx_rst_sync = cdc.ResetSynchronizer(ResetSignal(), domain="rx")
        m.submodules.tx_rst_sync = cdc.ResetSynchronizer(ResetSignal(), domain="tx")

        phy_clk = Signal()
        if platform is not None:
            # TODO: does not pass timing at 125 MHz
            # platform.add_clock_constraint(phy_clk, 125e6)
            platform.add_clock_constraint(phy_clk, 50e6)
        m.d.comb += phy_clk.eq(ClockSignal("rx"))
        m.d.comb += ClockSignal("tx").eq(phy_clk)

        # Transmitter with pseudo IO registers
        tx_io_data  = Signal(4)
        tx_io_valid = Signal(1)
        if platform is not None and self._tx_delay:
            m.submodules.tx_clk_delay = IODelay(ClockSignal("tx"), tx_clk_buffer.o, length=8)
        else:
            m.d.comb += tx_clk_buffer.o.eq(ClockSignal("tx"))
        # posedge: tx_dv, negedge: tx_dv xor tx_err; ignore tx_err to avoid the need for DDR buffers
        m.d.tx += tx_ctl_buffer.o.eq(tx_io_valid)
        m.d.tx += tx_data_buffer.o.eq(tx_io_data)

        # Receiver with pseudo IO registers
        rx_io_data  = Signal(4)
        rx_io_valid = Signal(1)
        if platform is not None and self._rx_delay:
            m.submodules.rx_clk_delay = IODelay(rx_clk_buffer.i, ClockSignal("rx"), length=8)
        else:
            m.d.comb += ClockSignal("rx").eq(rx_clk_buffer.i)
        # posedge: rx_dv, negedge: rx_dv xor rx_err; ignore rx_err to avoid the need for DDR buffers
        m.d.rx += rx_io_valid.eq(rx_ctl_buffer.i)
        m.d.rx += rx_io_data.eq(rx_data_buffer.i)

        tx_offset = Signal()
        with m.If(self.i.valid):
            m.d.tx += tx_offset.eq(tx_offset + 1)
            m.d.tx += tx_io_data.eq(self.i.p.data.word_select(tx_offset, 4))
            m.d.tx += tx_io_valid.eq(~self.i.p.end)
            m.d.comb += self.i.ready.eq(tx_offset == 1)
        with m.Else():
            m.d.tx += tx_io_data.eq(0)
            m.d.tx += tx_io_valid.eq(0)

        rx_data  = Signal(8)
        rx_valid = Signal(2)
        m.d.rx += rx_data.eq(Cat(rx_data[4:], rx_io_data))
        m.d.rx += rx_valid.eq(Cat(rx_valid[1:], rx_io_valid))
        with m.FSM(domain="rx"):
            m.d.rx += self.o.p.data.eq(rx_data)
            m.d.rx += self.o.p.end.eq(~rx_valid.all())
            m.d.rx += self.o.valid.eq(~self.o.valid)

            with m.State("10/100-Sync"):
                with m.If(rx_valid.all() & (rx_data == 0xd5)):
                    m.d.rx += self.o.valid.eq(1)
                    m.next = "10/100-Data"

            with m.State("10/100-Data"):
                with m.If(~rx_valid.all()):
                    m.next = "10/100-Sync"

        return m


class EthernetRGMIIInterface(AbstractEthernetInterface):
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 rx_clk: GlasgowPin, rx_ctl: GlasgowPin, rx_data: GlasgowPin,
                 tx_clk: GlasgowPin, tx_ctl: GlasgowPin, tx_data: GlasgowPin):
        ports = assembly.add_port_group(
            rx_clk=rx_clk, rx_ctl=rx_ctl, rx_data=rx_data,
            tx_clk=tx_clk, tx_ctl=tx_ctl, tx_data=tx_data)
        super().__init__(logger, assembly, driver=EthernetRGMIIDriver(ports))


class EthernetRGMIIApplet(AbstractEthernetApplet):
    logger = logging.getLogger(__name__)
    help = AbstractEthernetApplet.help + " via RGMII"
    preview = True
    description = AbstractEthernetApplet.description.replace("$PHYIF$", "RGMII") + """

    RGMII supports two modes: 100/1000 Mbps. This applet currently supports only 100 Mbps mode, and
    extending it to support 1000 Mbps would be nontrivial.
    """
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "rx_clk",  default=True, required=True)
        access.add_pins_argument(parser, "rx_ctl",  default=True, required=True)
        access.add_pins_argument(parser, "rx_data", default=True, required=True, width=4)
        access.add_pins_argument(parser, "tx_clk",  default=True, required=True)
        access.add_pins_argument(parser, "tx_ctl",  default=True, required=True)
        access.add_pins_argument(parser, "tx_data", default=True, required=True, width=4)
        access.add_pins_argument(parser, "mdc",     default=True, required=True)
        access.add_pins_argument(parser, "mdio",    default=True, required=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.eth_iface = EthernetRGMIIInterface(self.logger, self.assembly,
                rx_clk=args.rx_clk, rx_ctl=args.rx_ctl, rx_data=args.rx_data,
                tx_clk=args.tx_clk, tx_ctl=args.tx_ctl, tx_data=args.tx_data)
            self.mdio_iface = ControlMDIOInterface(self.logger, self.assembly,
                mdc=args.mdc, mdio=args.mdio)

    async def setup(self, args):
        await super().setup(args)
        await self.mdio_iface.clock.set_frequency(1e6)

        # Configure for 100 Mbps full duplex, no autonegotiation
        await self.mdio_iface.c22_write(0, REG_BASIC_CONTROL_addr,
            REG_BASIC_CONTROL(DUPLEXMD=1, SPD_SEL_0=1).to_int())

    @classmethod
    def tests(cls):
        from . import test
        return test.EthernetRGMIIAppletTestCase
