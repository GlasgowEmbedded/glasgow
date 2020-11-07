# Ref: MSP430™ Programming With the JTAG Interface
# Accession: G00038

import logging
import asyncio
from nmigen import *
from nmigen.lib.cdc import FFSynchronizer

from ....gateware.pads import *
from ... import *
from ..jtag_probe import JTAGProbeDriver, JTAGProbeInterface


class SpyBiWireProbeBus(Elaboratable):
    def __init__(self, pads):
        self._pads = pads
        self.sbwtck  = Signal(reset=0)
        self.sbwtd_z = Signal(reset=0)
        self.sbwtd_o = Signal(reset=1)
        self.sbwtd_i = Signal()

    def elaborate(self, platform):
        m = Module()
        pads = self._pads
        m.d.comb += [
            pads.sbwtck_t.oe.eq(1),
            pads.sbwtck_t.o.eq(self.sbwtck),
            pads.sbwtdio_t.oe.eq(~self.sbwtd_z),
            pads.sbwtdio_t.o.eq(self.sbwtd_o),
        ]
        m.submodules += [
            FFSynchronizer(pads.sbwtdio_t.i, self.sbwtd_i),
        ]
        return m


BIT_AUX_TCLK_LEVEL  = 0b001
BIT_AUX_TCLK_LATCH  = 0b010
BIT_AUX_TCLK_TOGGLE = 0b100


class SpyBiWireProbeAdapter(Elaboratable):
    def __init__(self, bus, period_cyc):
        self.bus = bus
        self._period_cyc = period_cyc

        self.stb = Signal()
        self.rdy = Signal()

        self.tms  = Signal()
        self.tdi  = Signal()
        self.tdo  = Signal()
        self.tclk = Signal()

        self.tclk_level  = Signal()
        self.tclk_latch  = Signal()
        self.tclk_toggle = Signal()
        self.aux_i = Cat(self.tclk)
        self.aux_o = Cat(self.tclk_level, self.tclk_latch, self.tclk_toggle)

    def elaborate(self, platform):
        m = Module()
        bus = self.bus

        half_cyc  = int(self._period_cyc // 2)
        quart_cyc = int(self._period_cyc // 4)
        timer     = Signal(range(half_cyc))
        with m.If(self.rdy | (timer == 0)):
            m.d.sync += timer.eq(half_cyc - 1)
        with m.Else():
            m.d.sync += timer.eq(timer - 1)

        with m.FSM():
            # This logic follows "JTAG Access Entry Sequences (for Devices That Support SBW)",
            # Case 1a: SBW entry sequence in section 2.3.1.1.
            #
            # Note that because SBW does not have any way to re-synchronize its time slots,
            # the only way to restore lost SBW synchronization is to reset the entire applet
            # for >100 us, which will reset the DUT and restart the SBW entry sequence.
            with m.State("RESET-1"):
                with m.If(timer == 0):
                    m.d.sync += bus.sbwtck.eq(1),
                    m.next = "RESET-2"

            with m.State("RESET-2"):
                with m.If(timer == 0):
                    m.d.sync += bus.sbwtck.eq(0),
                    m.next = "RESET-3"

            with m.State("RESET-3"):
                with m.If(timer == 0):
                    m.d.sync += bus.sbwtck.eq(1),
                    m.next = "IDLE"

            with m.State("IDLE"):
                with m.If(self.stb):
                    m.next = "TMS-SETUP"
                with m.Else():
                    m.d.comb += self.rdy.eq(1)

            with m.State("TMS-SETUP"):
                m.d.sync += bus.sbwtd_o.eq(self.tms)
                m.next = "TMS-HOLD"

            with m.State("TMS-HOLD"):
                with m.If(timer == 0):
                    m.d.sync += bus.sbwtck.eq(0)
                    m.next = "TDI-SETUP"

            with m.State("TDI-SETUP"):
                with m.If(timer == quart_cyc):
                    # This logic follows "Synchronization of TDI and TCLK During Run-Test/Idle" in
                    # section 2.2.3.5.1.
                    with m.If(self.tclk_latch | self.tclk_toggle):
                        m.d.sync += bus.sbwtd_o.eq(self.tclk)
                    with m.If(self.tclk_latch):
                        m.d.sync += self.tclk.eq(self.tclk_level)
                    with m.Elif(self.tclk_toggle):
                        m.d.sync += self.tclk.eq(self.tclk)

                with m.Elif(timer == 0):
                    m.d.sync += bus.sbwtck.eq(1),
                    with m.If(~(self.tclk_latch | self.tclk_toggle)):
                        m.d.sync += bus.sbwtd_o.eq(self.tdi)
                    m.next = "TDI-HOLD"

            with m.State("TDI-HOLD"):
                with m.If(timer == quart_cyc):
                    # Same as above.
                    with m.If(self.tclk_latch | self.tclk_toggle):
                        m.d.sync += bus.sbwtd_o.eq(self.tclk)

                with m.Elif(timer == 0):
                    m.d.sync += bus.sbwtck.eq(0),
                    m.next = "TDO-TURNAROUND"

            with m.State("TDO-TURNAROUND"):
                with m.If(timer == 0):
                    m.d.sync += bus.sbwtck.eq(1)
                    m.d.sync += bus.sbwtd_z.eq(1)
                    m.next = "TDO-SETUP"

            with m.State("TDO-SETUP"):
                with m.If(timer == 0):
                    m.d.sync += bus.sbwtck.eq(0)
                    m.next = "TDO-CAPTURE"

            with m.State("TDO-CAPTURE"):
                with m.If(timer == 0):
                    m.d.sync += bus.sbwtck.eq(1)
                    m.d.sync += bus.sbwtd_z.eq(0)
                    m.d.sync += self.tdo.eq(bus.sbwtd_i)
                    m.next = "IDLE"

        return m


class SpyBiWireProbeSubtarget(Elaboratable):
    def __init__(self, pads, out_fifo, in_fifo, period_cyc):
        self._pads       = pads
        self._out_fifo   = out_fifo
        self._in_fifo    = in_fifo
        self._period_cyc = period_cyc

    def elaborate(self, platform):
        m = Module()
        m.submodules.bus     = SpyBiWireProbeBus(self._pads)
        m.submodules.adapter = SpyBiWireProbeAdapter(m.submodules.bus, self._period_cyc)
        m.submodules.driver  = JTAGProbeDriver(m.submodules.adapter, self._out_fifo, self._in_fifo)
        return m


class SpyBiWireProbeInterface(JTAGProbeInterface):
    def _log_s(self, message, *args):
        self._logger.log(self._level, "SBW: " + message, *args)

    async def set_tclk(self, active):
        self._log_s("set tclk=%d", active)
        await self.enter_run_test_idle()
        await self.set_aux(BIT_AUX_TCLK_LATCH|(BIT_AUX_TCLK_LEVEL if active else 0))
        await self.pulse_tck(1)
        await self.set_aux(0)

    async def pulse_tclk(self, count):
        self._log_s("pulse tclk count=%d", count)
        await self.enter_run_test_idle()
        await self.set_aux(BIT_AUX_TCLK_TOGGLE)
        await self.pulse_tck(count)
        await self.set_aux(0)


class SpyBiWireProbeApplet(GlasgowApplet, name="sbw-probe"):
    logger = logging.getLogger(__name__)
    help = "probe microcontrollers via TI Spy-Bi-Wire"
    description = """
    Probe Texas Instruments microcontrollers via Spy-Bi-Wire 2-wire JTAG transport layer.
    """
    required_revision = "C0"

    __pins = ("sbwtck", "sbwtdio")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in cls.__pins:
            access.add_pin_argument(parser, pin, default=True)

        # set up for f_TCLK=350 kHz
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=2100,
            help="(advanced) set clock frequency to FREQ kHz (default: %(default)s)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(SpyBiWireProbeSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(auto_flush=False),
            period_cyc=target.sys_clk_freq // (args.frequency * 1000),
        ))

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        return SpyBiWireProbeInterface(iface, self.logger, __name__=__name__)

    async def interact(self, device, args, sbw_iface):
        await sbw_iface.test_reset()
        jtag_id_bits = await sbw_iface.read_ir(8)
        jtag_id = int(jtag_id_bits.reversed())
        if jtag_id == 0xff:
            self.logger.error("no target detected; connection problem?")
        else:
            self.logger.info("found MSP430 core with JTAG ID %#04x", jtag_id)

# -------------------------------------------------------------------------------------------------

class SpyBiWireProbeAppletTestCase(GlasgowAppletTestCase, applet=SpyBiWireProbeApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
