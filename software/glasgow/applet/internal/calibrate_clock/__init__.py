import logging
import struct
from amaranth import *
from amaranth.lib import io, wiring, stream
from amaranth.lib.wiring import Out
from amaranth.lib.cdc import FFSynchronizer

from glasgow.abstract import AbstractAssembly, GlasgowPin
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2


__all__ = ["CalibrateClockInterface"]


# Maximum gate time in seconds. Longer = more resolution but slower updates.
MAX_GATE_TIME_SEC = 10


class CalibrateClockComponent(wiring.Component):
    """Frequency counter gateware using free-running counters.

    All three counters (ref, sys, ext) run continuously.  Every
    ``ref_edges_per_gate`` reference edges the current counter values are
    snapshotted and streamed out.  Software subtracts consecutive snapshots
    to obtain the counts for each gate window, eliminating dead-time and
    first-window phase error.

    Reports 12 bytes per snapshot over o_stream (byte-at-a-time):
      bytes [0:4]  - ref_count  (uint32 LE): cumulative reference edges
      bytes [4:8]  - sys_count  (uint32 LE): cumulative system clock cycles
      bytes [8:12] - ext_count  (uint32 LE): cumulative external pin edges
    """

    o_stream: Out(stream.Signature(8))

    def __init__(self, *, ref_port: io.PortLike, ref_edges_per_gate: int,
                 ext_port: io.PortLike | None = None):
        self._ref_port           = ref_port
        self._ext_port           = ext_port
        self._ref_edges_per_gate = ref_edges_per_gate
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # --- Reference input: rising-edge detector ---
        m.submodules.ref_buf = ref_buf = io.Buffer("i", self._ref_port)
        ref_sync   = Signal()
        ref_sync_r = Signal()
        m.submodules.ref_cdc = FFSynchronizer(ref_buf.i, ref_sync)
        m.d.sync += ref_sync_r.eq(ref_sync)
        ref_edge = Signal()
        m.d.comb += ref_edge.eq(ref_sync & ~ref_sync_r)

        # --- External pin: rising-edge detector (optional) ---
        ext_edge = Signal()
        if self._ext_port is not None:
            m.submodules.ext_buf = ext_buf = io.Buffer("i", self._ext_port)
            ext_sync   = Signal()
            ext_sync_r = Signal()
            m.submodules.ext_cdc = FFSynchronizer(ext_buf.i, ext_sync)
            m.d.sync += ext_sync_r.eq(ext_sync)
            m.d.comb += ext_edge.eq(ext_sync & ~ext_sync_r)

        # --- Free-running counters (never reset) ---
        ref_count = Signal(32)
        sys_count = Signal(32)
        ext_count = Signal(32)

        m.d.sync += sys_count.eq(sys_count + 1)
        with m.If(ref_edge):
            m.d.sync += ref_count.eq(ref_count + 1)
        with m.If(ext_edge):
            m.d.sync += ext_count.eq(ext_count + 1)

        # --- Snapshot registers ---
        snap_ref = Signal(32)
        snap_sys = Signal(32)
        snap_ext = Signal(32)

        # Gate window trigger: snapshot counters every N reference edges
        gate_count = Signal(32)
        send_trigger = Signal()

        with m.If(ref_edge):
            with m.If(gate_count >= (self._ref_edges_per_gate - 1)):
                m.d.sync += [
                    gate_count.eq(0),
                    snap_ref.eq(ref_count),
                    snap_sys.eq(sys_count),
                    snap_ext.eq(ext_count),
                ]
                m.d.comb += send_trigger.eq(1)
            with m.Else():
                m.d.sync += gate_count.eq(gate_count + 1)

        # --- Byte-at-a-time output ---
        byte_idx = Signal(range(12))
        all_snaps = Cat(snap_ref, snap_sys, snap_ext)
        m.d.comb += self.o_stream.payload.eq(all_snaps.word_select(byte_idx, 8))

        with m.FSM():
            with m.State("IDLE"):
                with m.If(send_trigger):
                    m.next = "SEND"

            with m.State("SEND"):
                m.d.comb += self.o_stream.valid.eq(1)
                with m.If(self.o_stream.ready):
                    with m.If(byte_idx == 11):
                        m.d.sync += byte_idx.eq(0)
                        m.next = "IDLE"
                    with m.Else():
                        m.d.sync += byte_idx.eq(byte_idx + 1)

        return m


class CalibrateClockInterface:
    """Software interface for the clock calibration applet."""

    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 ref_pin: GlasgowPin,
                 ref_freq: float,
                 gate_time_sec: float = MAX_GATE_TIME_SEC,
                 nominal_sys_clk: float = 48e6,
                 initial_ppm: float = 0.0,
                 ext_pin: GlasgowPin | None = None,
                 ext_freq: float | None = None):
        self._logger       = logger
        self._level        = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._ref_freq     = ref_freq
        self._ext_freq     = ext_freq
        self._has_ext      = ext_pin is not None

        # Apply initial PPM correction to the nominal system clock so reported
        # errors are relative to the corrected baseline.
        self._nominal_sys_clk = nominal_sys_clk * (1 + initial_ppm / 1e6)

        self._ref_edges_per_gate = max(1, int(ref_freq * gate_time_sec))

        ref_port = assembly.add_port(ref_pin, name="ref")
        ext_port = assembly.add_port(ext_pin, name="ext") if ext_pin is not None else None

        component = assembly.add_submodule(
            CalibrateClockComponent(ref_port=ref_port, ref_edges_per_gate=self._ref_edges_per_gate,
                ext_port=ext_port))
        self._pipe = assembly.add_in_pipe(component.o_stream)
        self._prev_snap = None

    def _log(self, message, *args):
        self._logger.log(self._level, "calibrate-clock: " + message, *args)

    async def measure(self) -> dict:
        """Wait for one gate window and return a result dict.

        The gateware sends cumulative counter snapshots; we subtract
        consecutive snapshots to get the counts for each window.  The first
        snapshot is used only as a baseline and is discarded.
        """
        while True:
            data = await self._pipe.recv(12)
            curr_ref, curr_sys, curr_ext = struct.unpack("<III", data)

            if self._prev_snap is None:
                self._logger.info("baseline snapshot acquired, measuring first full window...")
                self._prev_snap = (curr_ref, curr_sys, curr_ext)
                continue

            prev_ref, prev_sys, prev_ext = self._prev_snap
            self._prev_snap = (curr_ref, curr_sys, curr_ext)

            # 32-bit unsigned wrap-around safe
            diff_ref = (curr_ref - prev_ref) & 0xFFFFFFFF
            diff_sys = (curr_sys - prev_sys) & 0xFFFFFFFF
            diff_ext = (curr_ext - prev_ext) & 0xFFFFFFFF

            if diff_ref == 0:
                continue

            gate_time    = diff_ref / self._ref_freq
            sys_clk_hz   = diff_sys / gate_time
            sys_ppm      = (sys_clk_hz - self._nominal_sys_clk) / self._nominal_sys_clk * 1e6

            ext_hz  = None
            ext_ppm = None
            if self._has_ext and self._ext_freq is not None and diff_ext > 0:
                ext_hz  = diff_ext / gate_time
                ext_ppm = (ext_hz - self._ext_freq) / self._ext_freq * 1e6

            return {
                "ref_count":     diff_ref,
                "sys_count":     diff_sys,
                "ext_count":     diff_ext,
                "sys_clk_hz":    sys_clk_hz,
                "sys_ppm":       sys_ppm,
                "ext_hz":        ext_hz,
                "ext_ppm":       ext_ppm,
                "gate_time_sec": gate_time,
            }


class CalibrateClockApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "measure clock accuracy against an external reference"
    description = """
    Measure clock accuracy against a stable external reference signal.

    By default measures the internal Glasgow system clock. With ``--ext-pin``, measures
    a second clock source (e.g. Si5351A output) against the reference instead.

    Measure system clock vs GPS PPS reference (1 Hz) on pin B1:

    ::

        glasgow run calibrate-clock -V 3.3 --ref-pin B1 --ref-freq 1

    The reference input expects a signal that crosses the logic threshold cleanly.
    A 2 V pk-pk sine centred at 1 V works well with the I/O bank set to 2 V.

    Measure system clock vs Rubidium reference (2^23 Hz) on pin B1:

    ::

        glasgow run calibrate-clock -V 2.0 --ref-pin B1 --ref-freq 8388608

    Measure Si5351A 10 MHz output on A0 vs same Rb reference on B1:

    ::

        glasgow run calibrate-clock -V 2.0 \\
            --ref-pin B1 --ref-freq 8388608 --ext-pin A0 --ext-freq 10000000

    Apply a known rough correction to the baseline before measuring:

    ::

        glasgow run calibrate-clock -V 2.0 \\
            --ref-pin B1 --ref-freq 8388608 --ppm -12.5
    """
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "ref_pin", required=True,
            help="stable reference clock input pin (e.g. B1 for Rb standard)")
        access.add_pins_argument(parser, "ext_pin", required=False,
            help="optional external clock to measure (e.g. A0 for Si5351A output); "
                 "if omitted the system clock is measured")

        parser.add_argument(
            "--ref-freq", type=float, required=True, metavar="HZ",
            help="exact frequency of the reference clock in Hz (e.g. 8388608 for 2^23 Hz)")
        parser.add_argument(
            "--ext-freq", type=float, default=None, metavar="HZ",
            help="nominal frequency of the external clock in Hz (required with --ext-pin)")
        parser.add_argument(
            "--nominal-sys-clk", type=float, default=48e6, metavar="HZ",
            help="nominal system clock frequency in Hz (default: %(default).0f)")
        parser.add_argument(
            "--gate-time", type=float, default=MAX_GATE_TIME_SEC, metavar="SEC",
            help="gate window duration in seconds; longer gives more resolution "
                 "(default: %(default)s)")
        parser.add_argument(
            "--ppm", type=float, default=0.0, metavar="PPM",
            help="initial PPM correction applied to the nominal frequency before measuring "
                 "(default: %(default)s)")

    def build(self, args):
        if args.ext_pin is not None and args.ext_freq is None:
            raise GlasgowAppletError("--ext-freq is required when --ext-pin is given")

        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.cal_iface = CalibrateClockInterface(
                self.logger, self.assembly,
                ref_pin=args.ref_pin,
                ref_freq=args.ref_freq,
                gate_time_sec=args.gate_time,
                nominal_sys_clk=args.nominal_sys_clk,
                initial_ppm=args.ppm,
                ext_pin=args.ext_pin,
                ext_freq=args.ext_freq,
            )

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument(
            "--count", type=int, default=0, metavar="N",
            help="number of measurements to take then exit (default: 0 = run forever)")

    async def run(self, args):
        gate_sec = self.cal_iface._ref_edges_per_gate / args.ref_freq
        measuring = f"ext pin {args.ext_pin} ({args.ext_freq:.0f} Hz)" \
            if args.ext_pin is not None else "system clock"

        self.logger.info("reference:   pin %s @ %.6f Hz", args.ref_pin, args.ref_freq)
        self.logger.info("measuring:   %s", measuring)
        self.logger.info("gate time:   %.2f s per measurement", gate_sec)
        if args.ppm != 0.0:
            self.logger.info("initial ppm correction: %+.3f ppm", args.ppm)
        self.logger.info("waiting for first measurement window...")

        n = 0
        ppms = []
        while args.count == 0 or n < args.count:
            result = await self.cal_iface.measure()

            if args.ext_pin is not None:
                ppm = result["ext_ppm"]
                self.logger.info(
                    "ext = %.3f Hz  |  error = %+.3f ppm  |  gate = %.3f s",
                    result["ext_hz"], ppm, result["gate_time_sec"])
            else:
                ppm = result["sys_ppm"]
                self.logger.info(
                    "sys_clk = %.3f Hz  |  error = %+.3f ppm  |  gate = %.3f s",
                    result["sys_clk_hz"], ppm, result["gate_time_sec"])

            ppms.append(ppm)
            n += 1

        if ppms:
            avg = sum(ppms) / len(ppms)
            self.logger.info("--- average over %d measurements: %+.3f ppm ---", len(ppms), avg)
            self.logger.info("use:  --clock-ppm %+.3f ", avg)
