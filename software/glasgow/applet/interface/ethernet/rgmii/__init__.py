# Ref: IEEE Std 802.3-2018
# Accession: G00098
# Ref: Reduced Gigabit Media Independent Interface (RGMII) Version 1.3
# Accession: G00099

import logging

from amaranth import *
from amaranth.lib import io

from glasgow.arch.ieee802_3 import *
from glasgow.gateware.ethernet import AbstractDriver
from glasgow.gateware.iostream import StreamIOBuffer
from glasgow.gateware.ports import PortGroup
from glasgow.gateware.pll import PLL
from glasgow.gateware.iodelay import IODelay
from glasgow.abstract import AbstractAssembly, GlasgowPin
from glasgow.applet.interface.ethernet import AbstractEthernetInterface, AbstractEthernetApplet
from glasgow.applet.control.mdio import ControlMDIOInterface


__all__ = ["EthernetRGMIIDriver", "EthernetRGMIIInterface", "PLL"]


class EthernetRGMIIDriver(AbstractDriver):
    def __init__(self, ports, *, rx_delay: int, tx_delay: int):
        self._ports  = ports

        self._rx_delay = rx_delay
        self._tx_delay = tx_delay

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # The RGMII interface is source-synchronous with separate clocks for the receive and
        # transmit halves. We use RX_CLK (recovered receive clock) as the driver clock and
        # retransmit it as TX_CLK; the driver itself only uses a single `mac` clock domain.

        m.submodules.rx_clk_buffer = rx_clk_buffer = io.Buffer("i", self._ports.rx_clk)
        m.submodules.rx_clk_delay = IODelay(
            rx_clk_buffer.i, ClockSignal("mac"), length=self._rx_delay)
        if platform is not None:
            # TODO: does not pass timing at 125 MHz
            # platform.add_clock_constraint(phy_clk, 125e6)
            platform.add_clock_constraint(rx_clk_buffer.i, 50e6)

        m.submodules.tx_clk_buffer = tx_clk_buffer = io.Buffer("o", self._ports.tx_clk)
        m.submodules.tx_clk_delay = IODelay(
            ClockSignal("mac"), tx_clk_buffer.o, length=self._tx_delay)

        m.submodules.buffer = buffer = StreamIOBuffer(PortGroup(
            tx_ctl =self._ports.tx_ctl .with_direction("o"),
            tx_data=self._ports.tx_data.with_direction("o"),
            # These are outputs, but configuring them as I/O avoids issues with IOB clock
            # constraints on iCE40.
            rx_ctl =self._ports.rx_ctl .with_direction("io"),
            rx_data=self._ports.rx_data.with_direction("io"),
        ), ratio=2, o_domain="mac", i_domain="mac")
        m.d.comb += buffer.i.p.port.tx_ctl.oe.eq(Cat(1, 1))
        m.d.comb += buffer.i.p.port.tx_data.oe.eq(Cat(1, 1))

        tx_offset = Signal()
        m.d.mac += buffer.i.p.port.tx_ctl.o.eq(
            (self.i.valid & ~self.i.p.end).replicate(2))
        m.d.mac += buffer.i.p.port.tx_data.o.eq(
            self.i.p.data.word_select(tx_offset, 4).replicate(2))
        with m.If(self.i.valid):
            m.d.mac += tx_offset.eq(tx_offset + 1)
            m.d.comb += self.i.ready.eq(tx_offset == 1)

        rx_data  = Signal(8)
        rx_valid = Signal(2)
        # posedge: rx_dv, negedge: rx_dv xor rx_err; ignore rx_err for the time being
        m.d.mac += rx_data.eq(Cat(rx_data[4:], buffer.o.p.port.rx_data.i[0]))
        m.d.mac += rx_valid.eq(Cat(rx_valid[1:], buffer.o.p.port.rx_ctl.i[0]))
        m.d.mac += self.o.p.data.eq(rx_data)
        m.d.mac += self.o.p.end.eq(~rx_valid.all())

        with m.FSM(domain="mac"):
            m.d.mac += self.o.valid.eq(~self.o.valid)

            with m.State("10/100-Sync"):
                with m.If(rx_valid.all() & (rx_data == 0xd5)):
                    m.d.mac += self.o.valid.eq(1)
                    m.next = "10/100-Data"

            with m.State("10/100-Data"):
                with m.If(~rx_valid.all()):
                    m.next = "10/100-Sync"

        return m


class EthernetRGMIIInterface(AbstractEthernetInterface):
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 rx_clk: GlasgowPin, rx_ctl: GlasgowPin, rx_data: GlasgowPin, rx_delay: int,
                 tx_clk: GlasgowPin, tx_ctl: GlasgowPin, tx_data: GlasgowPin, tx_delay: int):
        ports = assembly.add_port_group(
            rx_clk=rx_clk, rx_ctl=rx_ctl, rx_data=rx_data,
            tx_clk=tx_clk, tx_ctl=tx_ctl, tx_data=tx_data)
        super().__init__(logger, assembly,
            driver=EthernetRGMIIDriver(ports, rx_delay=rx_delay, tx_delay=tx_delay))


class EthernetRGMIIApplet(AbstractEthernetApplet):
    logger = logging.getLogger(__name__)
    help = AbstractEthernetApplet.help + " via RGMII"
    preview = True
    description = AbstractEthernetApplet.description.replace("$PHYIF$", "RGMII") + """

    RGMII supports three modes: 10/100/1000 Mbps. This applet currently supports only the 100 Mbps
    mode (it disables autonegotiation), and extending it to support 1000 Mbps would be nontrivial.

    RGMII requires either the MAC or the PHY to delay the receive and transmit clocks to ensure
    sufficient setup and hold time. The default ``--tx-delay`` and ``--rx-delay`` values might be
    sufficient; if not, calibrate delays in range of 0..16 until there is no packet corruption or
    loss. Delay value of 4 stages corresponds to roughly 2.5 ns on iCE40; for the transmit path
    this corresponds to the measured data-to-clock phase offset, while for the receive path this
    delay shifts the capture window of FPGA input buffers. Note that the stages to nanoseconds
    relationship is not linear.
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

        parser.add_argument(
            "--rx-delay", metavar="STAGES", type=int, default=0,
            help="clock delay for the receive path (default: %(default)s)")
        parser.add_argument(
            "--tx-delay", metavar="STAGES", type=int, default=4,
            help="clock delay for the trasnmit path (default: %(default)s)")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.eth_iface = EthernetRGMIIInterface(self.logger, self.assembly,
                rx_clk=args.rx_clk, rx_ctl=args.rx_ctl, rx_data=args.rx_data,
                tx_clk=args.tx_clk, tx_ctl=args.tx_ctl, tx_data=args.tx_data,
                rx_delay=args.rx_delay, tx_delay=args.tx_delay)
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
