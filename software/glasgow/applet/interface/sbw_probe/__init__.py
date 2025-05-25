# Ref: MSP430™ Programming With the JTAG Interface
# Accession: G00038

import logging
from amaranth import *
from amaranth.lib import io, wiring, stream, data
from amaranth.lib.wiring import In, Out, flipped, connect
from amaranth.lib.cdc import FFSynchronizer

from glasgow.gateware.jtag.probe import Controller, Mode
from glasgow.applet import GlasgowAppletV2
from ..jtag_probe import JTAGProbeDriver, BaseJTAGProbeInterface


BIT_AUX_TCLK_LEVEL  = 0b001
BIT_AUX_TCLK_LATCH  = 0b010
BIT_AUX_TCLK_TOGGLE = 0b100


class OutputFrame(data.Struct):
    tms:    unsigned(1)
    tdi:    unsigned(1)
    tdo_en: unsigned(1)
    last:   unsigned(1)


class InputFrame(data.Struct):
    tdo:    unsigned(1)
    last:   unsigned(1)


class Enframer(wiring.Component):
    def __init__(self, *, width):
        super().__init__({
            "words": In(Controller.i_words_signature(width)),
            "frames": Out(stream.Signature(OutputFrame)),
        })

    def elaborate(self, platform):
        m = Module()

        offset = Signal.like(self.words.p.size)
        last   = (offset + 1 == self.words.p.size)

        with m.If(self.words.p.mode == Mode.ShiftTMS):
            m.d.comb += self.frames.p.tms.eq(self.words.p.data.bit_select(offset, 1))
        with m.Else():
            m.d.comb += self.frames.p.tms.eq(self.words.p.last & last)

        with m.If((self.words.p.mode == Mode.ShiftTDI) | (self.words.p.mode == Mode.ShiftTDIO)):
            m.d.comb += self.frames.p.tdi.eq(self.words.p.data.bit_select(offset, 1))
        with m.Else():
            # According to IEEE 1149.1, TDI idles at 1 (there is a pullup). In most cases this
            # should not matter but some devices are non-compliant and might misbehave if TDI
            # is left floating during operations where it should not matter.
            m.d.comb += self.frames.p.tdi.eq(1)

        m.d.comb += self.frames.p.last.eq(last)
        with m.If(self.words.p.mode == Mode.ShiftTDIO):
            m.d.comb += self.frames.p.tdo_en.eq(1)

        m.d.comb += self.frames.valid.eq(self.words.valid)
        with m.If(self.frames.valid & self.frames.ready):
            m.d.sync += offset.eq(offset + 1)
            with m.If(last):
                m.d.sync += offset.eq(0)
                m.d.comb += self.words.ready.eq(1)

        return m


class Frontend(wiring.Component):
    o_stream:    In(stream.Signature(OutputFrame))
    i_stream:    Out(stream.Signature(InputFrame))

    tclk:        Out(1)
    tclk_level:  In(1)
    tclk_latch:  In(1)
    tclk_toggle: In(1)

    def __init__(self, ports, period_cyc):
        self._ports = ports
        self._period_cyc = period_cyc

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        half_cyc    = int(self._period_cyc // 2)
        quart_cyc   = int(self._period_cyc // 4)
        timer       = Signal(range(half_cyc))
        reset_timer = Signal()
        with m.If(reset_timer):
            m.d.sync += timer.eq(half_cyc - 1)
        with m.Elif(timer != 0):
            m.d.sync += timer.eq(timer - 1)

        sbwtck  = Signal(init=0)
        sbwtd_z = Signal(init=0)
        sbwtd_o = Signal(init=1)
        sbwtd_i = Signal()

        m.submodules.sbwtck_buffer  = sbwtck_buffer  = io.Buffer("o", self._ports.sbwtck)
        m.submodules.sbwtdio_buffer = sbwtdio_buffer = io.Buffer("io", self._ports.sbwtdio)
        m.d.comb += [
            sbwtck_buffer.o.eq(sbwtck),
            sbwtdio_buffer.oe.eq(~sbwtd_z),
            sbwtdio_buffer.o.eq(sbwtd_o),
        ]
        m.submodules += [
            FFSynchronizer(sbwtdio_buffer.i, sbwtd_i),
        ]

        with m.FSM():
            # This logic follows "JTAG Access Entry Sequences (for Devices That Support SBW)",
            # Case 1a: SBW entry sequence in section 2.3.1.1.
            #
            # Note that because SBW does not have any way to re-synchronize its time slots,
            # the only way to restore lost SBW synchronization is to reset the entire applet
            # for >100 us, which will reset the DUT and restart the SBW entry sequence.
            with m.State("RESET-1"):
                with m.If(timer == 0):
                    m.d.comb += reset_timer.eq(1)
                    m.d.sync += sbwtck.eq(1)
                    m.next = "RESET-2"

            with m.State("RESET-2"):
                with m.If(timer == 0):
                    m.d.comb += reset_timer.eq(1)
                    m.d.sync += sbwtck.eq(0)
                    m.next = "RESET-3"

            with m.State("RESET-3"):
                with m.If(timer == 0):
                    m.d.sync += sbwtck.eq(1)
                    m.next = "IDLE"

            with m.State("IDLE"):
                with m.If(self.o_stream.valid):
                    m.d.comb += reset_timer.eq(1)
                    m.d.sync += sbwtd_o.eq(self.o_stream.p.tms)
                    m.next = "TMS-HOLD"

            with m.State("TMS-HOLD"):
                with m.If(timer == 0):
                    m.d.comb += reset_timer.eq(1)
                    m.d.sync += sbwtck.eq(0)
                    m.next = "TDI-SETUP"

            with m.State("TDI-SETUP"):
                with m.If(timer == quart_cyc):
                    # This logic follows "Synchronization of TDI and TCLK During Run-Test/Idle" in
                    # section 2.2.3.5.1.
                    with m.If(self.tclk_latch | self.tclk_toggle):
                        m.d.sync += sbwtd_o.eq(self.tclk)
                    with m.If(self.tclk_latch):
                        m.d.sync += self.tclk.eq(self.tclk_level)
                    with m.Elif(self.tclk_toggle):
                        m.d.sync += self.tclk.eq(~self.tclk)

                with m.Elif(timer == 0):
                    m.d.comb += reset_timer.eq(1)
                    m.d.sync += sbwtck.eq(1)
                    with m.If(~(self.tclk_latch | self.tclk_toggle)):
                        m.d.sync += sbwtd_o.eq(self.o_stream.p.tdi)
                    m.next = "TDI-HOLD"

            with m.State("TDI-HOLD"):
                with m.If(timer == quart_cyc):
                    # Same as above.
                    with m.If(self.tclk_latch | self.tclk_toggle):
                        m.d.sync += sbwtd_o.eq(self.tclk)

                with m.Elif(timer == 0):
                    m.d.comb += reset_timer.eq(1)
                    m.d.sync += sbwtck.eq(0)
                    m.next = "TDO-TURNAROUND"

            with m.State("TDO-TURNAROUND"):
                with m.If(timer == 0):
                    m.d.comb += reset_timer.eq(1)
                    m.d.sync += sbwtck.eq(1)
                    m.d.sync += sbwtd_z.eq(1)
                    m.next = "TDO-SETUP"

            with m.State("TDO-SETUP"):
                with m.If(timer == 0):
                    m.d.comb += reset_timer.eq(1)
                    m.d.sync += sbwtck.eq(0)
                    m.next = "TDO-CAPTURE"

            with m.State("TDO-CAPTURE"):
                with m.If(timer == 0):
                    m.d.sync += sbwtck.eq(1)
                    m.d.sync += sbwtd_z.eq(0)
                    m.d.comb += self.o_stream.ready.eq(1)
                    with m.If(self.o_stream.p.tdo_en):
                        m.d.sync += self.i_stream.p.tdo.eq(sbwtd_i)
                        m.d.sync += self.i_stream.p.last.eq(self.o_stream.p.last)
                        m.next = "TDO-RETURN"
                    with m.Else():
                        m.next = "IDLE"

            with m.State("TDO-RETURN"):
                m.d.comb += self.i_stream.valid.eq(1)
                with m.If(self.i_stream.ready):
                    m.next = "IDLE"

        return m


class Deframer(wiring.Component):
    def __init__(self, *, width):
        super().__init__({
            "frames": In(stream.Signature(InputFrame)),
            "words": Out(Controller.o_words_signature(width)),
        })

    def elaborate(self, platform):
        m = Module()

        offset = self.words.p.size

        with m.FSM():
            with m.State("More"):
                m.d.sync += self.words.p.data.bit_select(offset, 1).eq(self.frames.p.tdo)
                m.d.comb += self.frames.ready.eq(1)
                with m.If(self.frames.valid):
                    m.d.sync += offset.eq(offset + 1)
                    with m.If(self.frames.p.last):
                        m.next = "Last"

            with m.State("Last"):
                m.d.comb += self.words.valid.eq(1)
                with m.If(self.words.ready):
                    m.d.sync += offset.eq(0)
                    m.d.sync += self.words.p.data.eq(0)
                    m.next = "More"

        return m


class SpyBiWireProbeController(wiring.Component):
    def __init__(self, ports, *, width, period_cyc):
        self._ports = ports
        self._width = width
        self._period_cyc = period_cyc

        super().__init__({
            "i_words":     In(Controller.i_words_signature(width)),
            "o_words":     Out(Controller.o_words_signature(width)),
            "tclk":        Out(1),
            "tclk_level":  In(1),
            "tclk_latch":  In(1),
            "tclk_toggle": In(1),
        })

    def elaborate(self, platform):
        m = Module()

        m.submodules.enframer = enframer = Enframer(width=self._width)
        connect(m, controller=flipped(self.i_words), enframer=enframer.words)

        m.submodules.frontend = frontend = Frontend(self._ports, period_cyc=self._period_cyc)
        connect(m, enframer=enframer.frames, frontend=frontend.o_stream)
        m.d.comb += [
            self.tclk.eq(frontend.tclk),
            frontend.tclk_level.eq(self.tclk_level),
            frontend.tclk_latch.eq(self.tclk_latch),
            frontend.tclk_toggle.eq(self.tclk_toggle),
        ]

        m.submodules.deframer = deframer = Deframer(width=self._width)
        connect(m, frontend=frontend.i_stream, deframer=deframer.frames)

        connect(m, deframer=deframer.words, controller=flipped(self.o_words))

        return m


class SpyBiWireProbeComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))
    o_flush:  Out(1)

    def __init__(self, ports, *, period_cyc, us_cycles):
        self._ports      = ports
        self._period_cyc = period_cyc
        self._us_cycles  = us_cycles

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.controller = controller = SpyBiWireProbeController(self._ports,
            width=8, period_cyc=self._period_cyc)
        m.submodules.driver     = driver     = JTAGProbeDriver(us_cycles=self._us_cycles)

        connect(m, flipped(self.i_stream), driver.i_stream)
        connect(m, flipped(self.o_stream), driver.o_stream)
        m.d.comb += self.o_flush.eq(driver.o_flush)

        connect(m, driver.o_words, controller.i_words)
        connect(m, driver.i_words, controller.o_words)

        m.d.comb += [
            driver.aux_i.eq(controller.tclk),
            Cat(controller.tclk_level, controller.tclk_latch, controller.tclk_toggle).eq(
                driver.aux_o),
        ]

        return m


class SpyBiWireProbeInterface(BaseJTAGProbeInterface):
    def __init__(self, logger, assembly, *, sbwtck, sbwtdio, period_cyc):
        ports = assembly.add_port_group(sbwtck=sbwtck, sbwtdio=sbwtdio)
        component = assembly.add_submodule(SpyBiWireProbeComponent(ports, period_cyc=period_cyc,
            us_cycles=int(1 / (assembly.sys_clk_period * 1_000_000))))
        pipe = assembly.add_inout_pipe(
            component.o_stream, component.i_stream, in_flush=component.o_flush)

        super().__init__(logger, pipe)

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


class SpyBiWireProbeApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "probe microcontrollers via TI Spy-Bi-Wire"
    description = """
    Probe Texas Instruments microcontrollers via Spy-Bi-Wire 2-wire JTAG transport layer.
    """
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)

        access.add_pins_argument(parser, "sbwtck", default=True)
        access.add_pins_argument(parser, "sbwtdio", default=True)

        # set up for f_TCLK=350 kHz
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=2100,
            help="(advanced) set clock frequency to FREQ kHz (default: %(default)s)")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.sbw_iface = SpyBiWireProbeInterface(self.logger, self.assembly,
                sbwtck=args.sbwtck, sbwtdio=args.sbwtdio,
                period_cyc=round(1 / (self.assembly.sys_clk_period * args.frequency * 1000)),
            )

    async def run(self, args):
        await self.sbw_iface.test_reset()
        jtag_id_bits = await self.sbw_iface.read_ir(8)
        jtag_id = int(jtag_id_bits.reversed())
        if jtag_id == 0xff:
            self.logger.error("no target detected; connection problem?")
        else:
            self.logger.info("found MSP430 core with JTAG ID %#04x", jtag_id)

    @classmethod
    def tests(cls):
        from . import test
        return test.SpyBiWireProbeAppletTestCase
