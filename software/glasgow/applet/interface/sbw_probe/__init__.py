# Ref: MSP430™ Programming With the JTAG Interface
# Accession: G00038

import logging
import asyncio
from migen import *
from migen.genlib.cdc import MultiReg

from ....gateware.pads import *
from ... import *
from ..jtag_probe import JTAGProbeDriver, JTAGProbeInterface


class SpyBiWireProbeBus(Module):
    def __init__(self, pads):
        self.sbwtck  = Signal(reset=0)
        self.sbwtd_z = Signal(reset=0)
        self.sbwtd_o = Signal(reset=1)
        self.sbwtd_i = Signal()

        ###

        self.comb += [
            pads.sbwtck_t.oe.eq(1),
            pads.sbwtck_t.o.eq(self.sbwtck),
            pads.sbwtdio_t.oe.eq(~self.sbwtd_z),
            pads.sbwtdio_t.o.eq(self.sbwtd_o),
        ]
        self.specials += [
            MultiReg(pads.sbwtdio_t.i, self.sbwtd_i),
        ]


BIT_AUX_TCLK_LEVEL  = 0b001
BIT_AUX_TCLK_LATCH  = 0b010
BIT_AUX_TCLK_TOGGLE = 0b100


class SpyBiWireProbeAdapter(Module):
    def __init__(self, bus, period_cyc):
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

        ###

        half_cyc  = int(period_cyc // 2)
        quart_cyc = int(period_cyc // 4)
        timer     = Signal(max=half_cyc)
        self.sync += [
            If(self.rdy | (timer == 0),
                timer.eq(half_cyc - 1)
            ).Else(
                timer.eq(timer - 1)
            )
        ]

        self.submodules.fsm = FSM()
        # This logic follows "JTAG Access Entry Sequences (for Devices That Support SBW)",
        # Case 1a: SBW entry sequence in section 2.3.1.1.
        #
        # Note that because SBW does not have any way to re-synchronize its time slots, the only
        # way to restore lost SBW synchronization is to reset the entire applet for >100 us, which
        # will reset the DUT and restart the SBW entry sequence.
        self.fsm.act("RESET-1",
            If(timer == 0,
                NextValue(bus.sbwtck, 1),
                NextState("RESET-2")
            )
        )
        self.fsm.act("RESET-2",
            If(timer == 0,
                NextValue(bus.sbwtck, 0),
                NextState("RESET-3")
            )
        )
        self.fsm.act("RESET-3",
            If(timer == 0,
                NextValue(bus.sbwtck, 1),
                NextState("IDLE")
            )
        )
        self.fsm.act("IDLE",
            If(self.stb,
                NextState("TMS-SETUP")
            ).Else(
                self.rdy.eq(1)
            )
        )
        self.fsm.act("TMS-SETUP",
            NextValue(bus.sbwtd_o, self.tms),
            NextState("TMS-HOLD")
        )
        self.fsm.act("TMS-HOLD",
            If(timer == 0,
                NextValue(bus.sbwtck,  0),
                NextState("TDI-SETUP")
            )
        )
        self.fsm.act("TDI-SETUP",
            If(timer == quart_cyc,
                # This logic follows "Synchronization of TDI and TCLK During Run-Test/Idle" in
                # section 2.2.3.5.1.
                If(self.tclk_latch | self.tclk_toggle,
                    NextValue(bus.sbwtd_o, self.tclk)
                ),
                If(self.tclk_latch,
                    NextValue(self.tclk, self.tclk_level)
                ).Elif(self.tclk_toggle,
                    NextValue(self.tclk, ~self.tclk)
                )
            ),
            If(timer == 0,
                NextValue(bus.sbwtck,  1),
                If(~(self.tclk_latch | self.tclk_toggle),
                    NextValue(bus.sbwtd_o, self.tdi)
                ),
                NextState("TDI-HOLD")
            )
        )
        self.fsm.act("TDI-HOLD",
            If(timer == quart_cyc,
                # Same as above.
                If(self.tclk_latch | self.tclk_toggle,
                    NextValue(bus.sbwtd_o, self.tclk)
                )
            ),
            If(timer == 0,
                NextValue(bus.sbwtck,  0),
                NextState("TDO-TURNAROUND")
            )
        )
        self.fsm.act("TDO-TURNAROUND",
            If(timer == 0,
                NextValue(bus.sbwtck,  1),
                NextValue(bus.sbwtd_z, 1),
                NextState("TDO-SETUP")
            )
        )
        self.fsm.act("TDO-SETUP",
            If(timer == 0,
                NextValue(bus.sbwtck,  0),
                NextState("TDO-CAPTURE")
            )
        )
        self.fsm.act("TDO-CAPTURE",
            If(timer == 0,
                NextValue(bus.sbwtck,  1),
                NextValue(bus.sbwtd_z, 0),
                NextValue(self.tdo,    bus.sbwtd_i),
                NextState("IDLE")
            )
        )


class SpyBiWireProbeSubtarget(Module):
    def __init__(self, pads, out_fifo, in_fifo, period_cyc):
        self.submodules.bus     = SpyBiWireProbeBus(pads)
        self.submodules.adapter = SpyBiWireProbeAdapter(self.bus, period_cyc)
        self.submodules.driver  = JTAGProbeDriver(self.adapter, out_fifo, in_fifo)


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
            in_fifo=iface.get_in_fifo(),
            period_cyc=target.sys_clk_freq // (args.frequency * 1000),
        ))

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        return SpyBiWireProbeInterface(iface, self.logger, __name__=__name__)

    async def interact(self, device, args, sbw_iface):
        await sbw_iface.test_reset()
        version_bits = await sbw_iface.read_ir(8)
        version = int(version_bits.reversed())
        if version == 0xff:
            self.logger.error("no target detected; connection problem?")
        else:
            self.logger.info("found MSP430 core with JTAG ID %#04x", version)

# -------------------------------------------------------------------------------------------------

class SpyBiWireProbeAppletTestCase(GlasgowAppletTestCase, applet=SpyBiWireProbeApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
