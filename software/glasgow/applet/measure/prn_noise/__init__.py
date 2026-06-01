"""PRN Noise Source.

Generates a pseudo-random binary noise signal from a 31-bit maximal-length
LFSR running at 192 MHz with DDR output, giving an effective chip rate of
384 Mcps (48 MHz system clock x4 via iCE40 PLL, doubled by SB_IO DDR).

The output is a single GPIO pin.  The on-board 33 Ohm series resistor limits
drive current; an external low-pass filter shapes the spectrum for a
band-limited noise source.

Use case: characterising RF filters.  The 384 Mcps effective rate provides
flat spectral coverage to ~192 MHz; odd harmonics extend useful energy to
~960 MHz and beyond (attenuated by the 33 Ohm + parasitic-C channel response).

LFSR polynomial: x^31 + x^28 + 1  (maximal-length, period 2^31-1)
Sequence period at 384 Mcps: ~5.6 seconds before repeat.

Architecture::

    48 MHz system clock
      -> iCE40 SB_PLL40_CORE  (DIVF=15, DIVR=0, DIVQ=2 -> 192 MHz)
        -> 31-bit Galois LFSR, flattened double-step (1 LUT deep)
          -> DDR output register (posedge = step 1, negedge = step 2)
            -> io.DDRBuffer -> GPIO pin  (384 Mcps effective)

Host control (fire-and-forget via out-pipe):
    _Command.Start (0x01) + seed[3:0] (4 bytes little-endian, non-zero)
    _Command.Stop  (0x02)
"""

import asyncio
import logging
import struct

from amaranth import *
from amaranth.lib import enum, wiring, io, stream
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.wiring import In

from glasgow.applet import GlasgowAppletV2
from glasgow.gateware.pll import PLL


__all__ = ["PRNNoiseInterface"]


# ---------------------------------------------------------------------------
# Wire protocol (host -> FPGA out-pipe)
# ---------------------------------------------------------------------------
class _Command(enum.Enum, shape=8):
    Start = 0x01  # followed by 4 bytes seed (little-endian, must be non-zero)
    Stop  = 0x02  # no payload


# LFSR: x^31 + x^28 + 1, Galois form (right-shifting, XOR on feedback=1).
# Tap positions are 0-indexed from LSB.
_LFSR_WIDTH    = 31
_TAP_MASK      = (1 << 30) | (1 << 27)  # x^31 and x^28 terms
_DEFAULT_SEED  = 0xABCDEF01


def _lfsr_double_step(state):
    """Compute two Galois LFSR steps as a single combinatorial stage.

    For the Galois LFSR ``step(s) = (s >> 1) ^ (s[0] * TAP_MASK)``,
    the double-step expands to::

        step2(s) = (s >> 2) ^ (s[0] * (TAP_MASK >> 1)) ^ (s[1] * TAP_MASK)

    Because TAP_MASK[0] == 0, the intermediate LSB ``s1[0] == s[1]``,
    eliminating the cascaded mux.  Each output bit depends on at most
    three inputs from ``s``, fitting in a single iCE40 4-LUT — half the
    logic depth of two chained ``_lfsr_step`` calls.

    Returns (next_state, out_first, out_second) as Amaranth expressions.
    """
    out_first  = state[0]
    out_second = state[1]  # TAP_MASK[0] == 0, so s1[0] == s[1]

    shifted2 = Cat(state[2:], Const(0, 2))
    mask_s0  = Mux(state[0], _TAP_MASK >> 1, 0)
    mask_s1  = Mux(state[1], _TAP_MASK,      0)
    next_state = shifted2 ^ mask_s0 ^ mask_s1

    return next_state, out_first, out_second


class PRNNoiseComponent(wiring.Component):
    """31-bit LFSR noise source at 192 MHz with DDR output (384 Mcps effective).

    The iCE40 PLL multiplies the 48 MHz system clock to 192 MHz.  The LFSR
    advances two steps per clock cycle; both output bits are presented via
    DDR (posedge and negedge) through SB_IO, doubling the effective chip rate.

    The command FSM runs in the sync (48 MHz) domain and accepts bytes from
    ``ctrl_stream``.  Control signals cross into the fast domain via
    FFSynchronizer (2-FF).
    """

    ctrl_stream: In(stream.Signature(8))

    def __init__(self, *, out_port, sys_clk_freq):
        self._out_port = out_port
        self._sys_clk_freq = sys_clk_freq
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # --- PLL: 48 MHz -> 192 MHz ---
        m.domains.fast = ClockDomain("fast")
        m.submodules.pll = PLL(
            f_in=self._sys_clk_freq, f_out=192e6, odomain="fast")

        # --- Control registers (sync domain) ---
        seed_reg = Signal(_LFSR_WIDTH, init=1)
        run_reg  = Signal()

        # --- Command FSM (sync domain) ---
        cmd    = Signal(8)
        seed_b = Signal(32)
        byte_n = Signal(range(4))

        with m.FSM(name="cmd_fsm", domain="sync"):
            with m.State("IDLE"):
                m.d.comb += self.ctrl_stream.ready.eq(1)
                with m.If(self.ctrl_stream.valid):
                    m.d.sync += cmd.eq(self.ctrl_stream.payload)
                    m.next = "DISPATCH"

            with m.State("DISPATCH"):
                with m.Switch(cmd):
                    with m.Case(_Command.Start):
                        m.d.sync += byte_n.eq(0)
                        m.next = "READ_SEED"
                    with m.Case(_Command.Stop):
                        m.d.sync += run_reg.eq(0)
                        m.next = "IDLE"
                    with m.Default():
                        m.next = "IDLE"

            with m.State("READ_SEED"):
                m.d.comb += self.ctrl_stream.ready.eq(1)
                with m.If(self.ctrl_stream.valid):
                    m.d.sync += seed_b.word_select(byte_n, 8).eq(
                        self.ctrl_stream.payload)
                    with m.If(byte_n == 3):
                        m.next = "LATCH_SEED"
                    with m.Else():
                        m.d.sync += byte_n.eq(byte_n + 1)

            with m.State("LATCH_SEED"):
                # Zero is a forbidden LFSR state; clamp to 1.
                safe_seed = Mux(seed_b[:_LFSR_WIDTH] == 0, 1, seed_b[:_LFSR_WIDTH])
                m.d.sync += seed_reg.eq(safe_seed)
                m.next = "ASSERT_RUN"

            with m.State("ASSERT_RUN"):
                # Extra cycle: seed_reg is stable before run_reg propagates
                # through the FFSynchronizer into the fast domain.
                m.d.sync += run_reg.eq(1)
                m.next = "IDLE"

        # --- LFSR with 2x unrolling (fast domain, 192 MHz) ---
        lfsr = Signal(_LFSR_WIDTH, init=1)

        seed_fast = Signal(_LFSR_WIDTH)
        run_fast  = Signal()

        m.submodules.seed_sync = FFSynchronizer(seed_reg, seed_fast, o_domain="fast")
        m.submodules.run_sync  = FFSynchronizer(run_reg,  run_fast,  o_domain="fast")

        # Detect rising edge of run_fast to latch seed on start.
        run_fast_prev = Signal()
        m.d.fast += run_fast_prev.eq(run_fast)
        run_rise = run_fast & ~run_fast_prev

        # Two LFSR steps per clock via flattened double-step (1 LUT deep).
        # See _lfsr_double_step: the two-step update is algebraically collapsed
        # so that each output bit depends only on the registered lfsr state,
        # avoiding the cascaded-mux critical path of two chained _lfsr_step calls.
        step2_state, step1_out, step2_out = _lfsr_double_step(lfsr)

        # Output registers (updated on fast posedge, DDR buffer handles both edges)
        out_posedge = Signal()  # chip output on rising edge  (step 1)
        out_negedge = Signal()  # chip output on falling edge (step 2)

        with m.If(run_rise):
            m.d.fast += lfsr.eq(seed_fast)
            m.d.fast += out_posedge.eq(0)
            m.d.fast += out_negedge.eq(0)
        with m.Elif(run_fast):
            m.d.fast += lfsr.eq(step2_state)
            m.d.fast += out_posedge.eq(step1_out)
            m.d.fast += out_negedge.eq(step2_out)
        with m.Else():
            m.d.fast += out_posedge.eq(0)
            m.d.fast += out_negedge.eq(0)

        # --- DDR output buffer ---
        # o[0] is driven on the rising edge, o[1] on the falling edge.
        m.submodules.out_ddr = out_ddr = io.DDRBuffer("o", self._out_port,
                                                       o_domain="fast")
        m.d.comb += [
            out_ddr.o[0].eq(out_posedge),
            out_ddr.o[1].eq(out_negedge),
        ]

        return m


class PRNNoiseInterface:
    """Host-side interface for the PRN noise source."""

    def __init__(self, *, logger, pipe):
        self._logger = logger
        self._level  = logging.DEBUG if logger.name == __name__ else logging.TRACE
        self._pipe   = pipe

    def _log(self, msg, *args):
        self._logger.log(self._level, "PRNNoise: " + msg, *args)

    async def start(self, seed=_DEFAULT_SEED):
        """Start the LFSR noise output.

        Zero seeds are clamped to 1 by the gateware.
        """
        seed = seed & 0xFFFFFFFF
        self._log("start seed=%#010x", seed)
        await self._pipe.send(struct.pack("<BI", _Command.Start, seed))
        await self._pipe.flush()

    async def stop(self):
        """Stop noise output (hold pin low)."""
        self._log("stop")
        await self._pipe.send(bytes([_Command.Stop]))
        await self._pipe.flush()


class GeneratePRNNoiseApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help   = "384 Mcps PRN noise source for RF filter characterisation"
    description = """
    Generates pseudo-random binary noise at 384 Mcps effective chip rate on
    a single GPIO pin.  Uses a 31-bit maximal-length LFSR (x^31 + x^28 + 1,
    Galois form) running at 192 MHz with DDR output (2 chips per clock via
    SB_IO posedge/negedge).

    The on-board 33 Ohm series resistor and parasitic capacitance form a
    low-pass channel; calibrate source flatness by measuring the output
    directly before inserting the DUT.

    For audio-frequency work, the on-board series resistor can be
    combined with an external 240 nF film capacitor to ground to form a ~20 kHz
    single-pole low-pass filter.  The filtered output closely approximates
    Additive White Gaussian Noise (AWGN): each filter time constant integrates
    ~19,200 chips, giving near-Gaussian amplitude distribution via the central limit theorem.

    LFSR period: 2^31 - 1 = 2,147,483,647 chips (~5.6 s at 384 Mcps).

    PLL: 48 MHz x16 / 4 = 192 MHz  (VCO = 768 MHz), DDR -> 384 Mcps.

    Example:

    ::

        glasgow run generate-prn-noise --voltage B=3.3 --out B0 start
    """

    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "out", required=True, default=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            out_port = self.assembly.add_port(args.out, name="out")
            sys_clk_freq = round(1 / self.assembly.sys_clk_period)
            component = self.assembly.add_submodule(
                PRNNoiseComponent(out_port=out_port, sys_clk_freq=sys_clk_freq))
            self._pipe = self.assembly.add_out_pipe(component.ctrl_stream)

    @classmethod
    def add_run_arguments(cls, parser):
        p_op = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_op.add_parser("start", help="start noise output")

        p_op.add_parser("stop", help="stop noise output (hold pin low)")

    async def run(self, args):
        iface = PRNNoiseInterface(logger=self.logger, pipe=self._pipe)

        if args.operation == "start":
            await iface.start()
            self.logger.info(
                "noise started: 384 Mcps (192 MHz DDR), "
                "LFSR x^31+x^28+1, period ~5.6 s")
            self.logger.info("press Ctrl+C to stop")
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                await iface.stop()

        elif args.operation == "stop":
            await iface.stop()
            self.logger.info("noise output stopped")
