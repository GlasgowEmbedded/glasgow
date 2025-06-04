import logging
import asyncio

from amaranth import *
from amaranth.lib import enum, wiring, io, cdc
from amaranth.lib.wiring import In, Out

from glasgow.gateware.ethernet import AbstractDriver
from glasgow.gateware.iostream import StreamIOBuffer
from glasgow.gateware.ports import PortGroup
from glasgow.gateware.pll import PLL
from glasgow.abstract import AbstractAssembly, GlasgowPin
from glasgow.applet.interface.ethernet import AbstractEthernetInterface, AbstractEthernetApplet
from glasgow.applet.control.mdio import ControlMDIOInterface


__all__ = ["EthernetRMIIDriver", "EthernetRMIIInterface"]


class EthernetRMIIDriver(AbstractDriver):
    class Mode(enum.Enum, shape=1):
        _100M = 0
        _10M  = 1

    def __init__(self, ports, *, offset=None):
        self._ports  = ports
        self._offset = offset

        super().__init__({
            "mode": In(self.Mode, init=self.Mode._10M),
        })

    def elaborate(self, platform):
        m = Module()

        # The RMII interface has one clock, REF_CLK, with both the transmit and the receive signals
        # of the interface being synchronous to it.
        m.domains.rxtx = cd_rxtx = ClockDomain()
        m.d.comb += [
            self.cd_rx.clk.eq(ClockSignal("rxtx")),
            self.cd_rx.rst.eq(ResetSignal("rxtx")),
            self.cd_tx.clk.eq(ClockSignal("rxtx")),
            self.cd_tx.rst.eq(ResetSignal("rxtx")),
        ]

        if platform is not None:
            m.submodules.pll = pll = PLL(48e6, 50e6, "rxtx")
        else: # simulation
            m.d.comb += cd_rxtx.clk.eq(ClockSignal("sync"))
            m.d.comb += cd_rxtx.rst.eq(ResetSignal("sync"))

        m.submodules.buffer = buffer = StreamIOBuffer(PortGroup(
            ref_clk=self._ports.ref_clk.with_direction("o"),
            tx_en  =self._ports.tx_en  .with_direction("o"),
            tx_data=self._ports.tx_data.with_direction("o"),
            crs_dv =self._ports.crs_dv .with_direction("i"),
            rx_data=self._ports.rx_data.with_direction("i"),
        ), ratio=2, offset=self._offset or 0, i_domain="rxtx", o_domain="rxtx")

        m.d.comb += buffer.i.p.port.ref_clk.o.eq(Cat(0, 1))
        m.d.comb += buffer.i.p.port.ref_clk.oe.eq(1)

        timer  = Signal(range(10))
        sample = Signal()
        with m.If(timer == 0):
            m.d.comb += sample.eq(1)
            # DIV/10 in 10 Mbps mode, DIV/1 in 100 Mbps mode.
            m.d.rxtx += timer.eq(Mux(self.mode == self.Mode._10M, 9, 0))
        with m.Else():
            m.d.rxtx += timer.eq(timer - 1)

        tx_offset = Signal(2)
        with m.If(self.i.valid & ~self.i.p.end):
            m.d.comb += buffer.i.p.port.tx_en.o.eq(Cat(1, 1))
            m.d.comb += buffer.i.p.port.tx_data.o.eq(
                self.i.p.data.word_select(tx_offset, 2).replicate(2))
        m.d.comb += buffer.i.p.port.tx_en.oe.eq(1)
        m.d.comb += buffer.i.p.port.tx_data.oe.eq(1)
        with m.If(self.i.valid & sample):
            m.d.rxtx += tx_offset.eq(tx_offset + 1)
            with m.If(tx_offset == 3):
                m.d.comb += self.i.ready.eq(1)

        rx_buffer = Signal(8)
        rx_count  = Signal(2)
        rx_align  = Signal()
        m.d.comb += self.o.p.data.eq(Cat(rx_buffer[2:], buffer.o.p.port.rx_data.i[1]))
        with m.If(sample):
            m.d.rxtx += rx_buffer.eq(self.o.p.data)
            with m.If(rx_align):
                m.d.rxtx += rx_count.eq(0)
                m.d.comb += self.o.valid.eq(1)
            with m.Else():
                m.d.rxtx += rx_count.eq(rx_count + 1)
                m.d.comb += self.o.valid.eq(rx_count == 3)

        with m.FSM(domain="rxtx", name="rx_fsm"):
            with m.State("Idle"):
                m.d.comb += self.o.p.end.eq(1)
                with m.If(sample):
                    with m.If(buffer.o.p.port.rx_data.i[1] != Cat(0, 0)):
                        m.next = "Preamble"

            with m.State("Preamble"):
                with m.If(sample):
                    with m.If(buffer.o.p.port.rx_data.i[1] == Cat(1, 1)):
                        m.d.comb += rx_align.eq(1)
                        m.next = "Frame"

            with m.State("Frame"):
                with m.If(sample):
                    # From the RMII specification:
                    #    If the PHY has additional bits to be presented on RXD[1:0] following
                    #    the initial deassertion of CRS_DV, then the PHY shall assert CRS_DV on
                    #    cycles of REF_CLK which present the second di-bit of each nibble and
                    #    deassert CRS_DV on cycles of REF_CLK which present the first di-bit of
                    #    a nibble.
                    # By switching the state to Idle on the second di-bit of an octet, the octet
                    # that is in the process of being shifted in during that is replaced with
                    # a packet end.
                    with m.If((rx_count == 1) & ~buffer.o.p.port.crs_dv.i[1]):
                        m.next = "Idle"

        return m


class EthernetRMIIInterface(AbstractEthernetInterface):
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 crs_dv: GlasgowPin, rx_data: GlasgowPin,
                 tx_en: GlasgowPin, tx_data: GlasgowPin,
                 ref_clk: GlasgowPin):
        ports = assembly.add_port_group(
            crs_dv=crs_dv, rx_data=rx_data, tx_en=tx_en, tx_data=tx_data, ref_clk=ref_clk)
        super().__init__(logger, assembly, driver=EthernetRMIIDriver(ports))


class EthernetRMIIApplet(AbstractEthernetApplet):
    logger = logging.getLogger(__name__)
    help = AbstractEthernetApplet.help + " via RMII"
    preview = True
    description = AbstractEthernetApplet.description.replace("$PHYIF$", "RGMII") + """

    RMII supports four modes; 10/100 Mbps × half/full duplex. This applet currently supports only
    10 Mbps full-duplex mode, but extending to support 100 Mbps would not be difficult.
    """
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "crs_dv",  default=True, required=True)
        access.add_pins_argument(parser, "rx_data", default=True, required=True, width=2)
        access.add_pins_argument(parser, "tx_en",   default=True, required=True)
        access.add_pins_argument(parser, "tx_data", default=True, required=True, width=2)
        access.add_pins_argument(parser, "mdc",     default=True, required=True)
        access.add_pins_argument(parser, "mdio",    default=True, required=True)
        access.add_pins_argument(parser, "ref_clk", default=True, required=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.eth_iface = EthernetRMIIInterface(self.logger, self.assembly,
                crs_dv =args.crs_dv, rx_data=args.rx_data,
                tx_en  =args.tx_en,  tx_data=args.tx_data,
                ref_clk=args.ref_clk)
            self.mdio_iface = ControlMDIOInterface(self.logger, self.assembly,
                mdc=args.mdc, mdio=args.mdio)

    async def setup(self, args):
        await super().setup(args)
        await self.mdio_iface.clock.set_frequency(1e6)

    @classmethod
    def tests(cls):
        from . import test
        return test.EthernetRMIIAppletTestCase
