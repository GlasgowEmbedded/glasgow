import csv
import json
import logging
import asyncio

from glasgow.applet import GlasgowAppletError, GlasgowAppletV2


__all__ = ["CurveTraceInterface", "DiodeTraceInterface"]


# Voltage range of the Glasgow I/O supply
MIN_VIO = 1.8
MAX_VIO = 5.0

# Default voltage step in volts
DEFAULT_STEP_V = 0.050

# Settling time after voltage change, in seconds
DEFAULT_SETTLE_S = 0.050

# Default reference voltage for diode mode
DEFAULT_REF_V = 2.5


def _load_cal(path):
    """Load a calibration CSV (open-circuit run) and return a dict mapping voltage to current."""
    cal = {}
    with open(path, newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        if header[0] != "voltage_V" or header[1] != "current_A":
            raise GlasgowAppletError(
                f"calibration CSV must have header 'voltage_V,current_A', got {header}")
        for row in reader:
            cal[round(float(row[0]), 4)] = float(row[1])
    return cal


class CurveTraceInterface:
    """Software interface for the curve tracing applet.

    Sweeps the I/O supply voltage on a single port from ``v_start`` to ``v_stop``
    in steps of ``step_v``, measuring voltage and current at each point via the
    on-board INA233 shunt monitor.
    """

    def __init__(self, logger, *, port, v_start, v_stop, step_v=DEFAULT_STEP_V,
                 settle_s=DEFAULT_SETTLE_S, sense_voltage=False, cal=None,
                 stop_current=None):
        self._logger        = logger
        self._port          = port
        self._v_start       = v_start
        self._v_stop        = v_stop
        self._step_v        = step_v
        self._settle_s      = settle_s
        self._sense_voltage = sense_voltage
        self._cal           = cal or {}
        self._stop_current  = stop_current

    async def sweep(self, device):
        """Generator-style sweep: yields (voltage_V, current_A) tuples."""
        results = []
        voltage = self._v_start
        while voltage <= self._v_stop + self._step_v / 2:
            v_set = min(voltage, self._v_stop)
            await device.set_voltage(self._port, v_set)
            await asyncio.sleep(self._settle_s)

            if self._sense_voltage:
                v_meas = await device.measure_voltage(self._port)
            else:
                v_meas = await device.get_voltage(self._port)
            i_meas = await device.measure_current(self._port)

            # Subtract no-load baseline current from calibration data
            v_key = round(v_meas, 4)
            i_cal = self._cal.get(v_key, 0.0)
            i_meas = max(0.0, i_meas - i_cal)

            self._logger.log(logging.DEBUG,
                "curve-trace: V=%.4f V  I=%.6f A", v_meas, i_meas)
            results.append((v_meas, i_meas))

            if self._stop_current is not None and i_meas >= self._stop_current:
                self._logger.info("stop current %.3f mA reached at %.4f V",
                    self._stop_current * 1000, v_meas)
                break

            voltage += self._step_v

        # Turn off port supply after sweep
        await device.set_voltage(self._port, 0)
        return results


class DiodeTraceInterface:
    """Software interface for diode curve tracing using two ports.

    Port A is swept from ``v_start`` to ``v_stop`` while port B is held at a
    fixed reference voltage.  The DUT is connected between port A Vio and
    port B Vio.  Output voltages are relative to the reference (V_A - V_ref),
    so forward-biased readings are positive and reverse-biased readings are
    negative.
    """

    def __init__(self, logger, *, v_start, v_stop, v_ref=DEFAULT_REF_V,
                 step_v=DEFAULT_STEP_V, settle_s=DEFAULT_SETTLE_S,
                 sense_voltage=False, cal=None, stop_current=None):
        self._logger        = logger
        self._v_start       = v_start
        self._v_stop        = v_stop
        self._v_ref         = v_ref
        self._step_v        = step_v
        self._settle_s      = settle_s
        self._sense_voltage = sense_voltage
        self._cal           = cal or {}
        self._stop_current  = stop_current

    async def sweep(self, device):
        """Sweep port A relative to port B reference.  Returns (voltage_V, current_A) tuples
        where voltage_V is the voltage across the DUT (V_A - V_ref).
        """
        # Bring up the reference port first
        await device.set_voltage("B", self._v_ref)
        await asyncio.sleep(self._settle_s)

        results = []
        voltage = self._v_start
        while voltage <= self._v_stop + self._step_v / 2:
            v_set = min(voltage, self._v_stop)
            await device.set_voltage("A", v_set)
            await asyncio.sleep(self._settle_s)

            if self._sense_voltage:
                v_meas = await device.measure_voltage("A")
            else:
                v_meas = await device.get_voltage("A")
            i_meas = await device.measure_current("A")

            # Subtract no-load baseline current from calibration data
            v_key = round(v_meas, 4)
            i_cal = self._cal.get(v_key, 0.0)
            i_meas = max(0.0, i_meas - i_cal)

            v_rel = v_meas - self._v_ref

            self._logger.log(logging.DEBUG,
                "diode-trace: V_A=%.4f V  V_rel=%.4f V  I=%.6f A",
                v_meas, v_rel, i_meas)
            results.append((v_rel, i_meas))

            if self._stop_current is not None and i_meas >= self._stop_current:
                self._logger.info("stop current %.3f mA reached at %.4f V (relative)",
                    self._stop_current * 1000, v_rel)
                break

            voltage += self._step_v

        # Turn off both port supplies after sweep
        await device.set_voltage("A", 0)
        await device.set_voltage("B", 0)
        return results


class CurveTraceApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "trace voltage-current curves using the on-board INA233"
    description = """
    Sweep the I/O supply voltage on a port and record voltage and current at each
    step, producing a V-I curve suitable for characterising LEDs, diodes, and other
    two-terminal devices.

    The device under test is connected between the port power rail and ground.
    A series resistor is recommended to keep the current within the INA233's
    measurement range (~546 mA max with the 0.15 ohm on-board shunt).

    Trace a red LED on port A from 1.8 V to 3.3 V in 50 mV steps (CSV):

    ::

        glasgow run curve-trace --port A --start 1.8 --stop 3.3 --step 0.05

    Same measurement, JSON output:

    ::

        glasgow run curve-trace --port A --start 1.8 --stop 3.3 --format json

    Stop the sweep early if current exceeds 20 mA (useful for LEDs):

    ::

        glasgow run curve-trace --port A --start 1.8 --stop 3.3 --stop-current 20

    To subtract the no-load buffer current, first run a sweep with no DUT attached
    and save it as a calibration file, then pass it with ``--cal``:

    ::

        glasgow run curve-trace --port A --start 1.8 --stop 3.3 > cal.csv
        glasgow run curve-trace --port A --start 1.8 --stop 3.3 --cal cal.csv

    In ``--diode`` mode, port A is swept while port B is held at a fixed reference
    voltage (default 2.5 V).  The DUT is connected between port A Vio and port B
    Vio.  Output voltages are relative to the reference (V_A - V_ref), so the
    sweep covers reverse bias (negative voltages) through forward conduction
    (positive voltages).  The maximum voltage across the DUT is limited by the
    1.8–5.0 V Vio range: with the default 2.5 V reference, the sweep covers
    -0.7 V (reverse) to +2.5 V (forward).

    Trace a silicon diode with 10 mV steps, stopping at 50 mA:

    ::

        glasgow run curve-trace --port A --diode --step 0.010 --stop-current 50

    Characterise a 2.7 V zener diode (raise the reference to 5.0 V so the full
    -3.2 V to 0 V reverse range is available):

    ::

        glasgow run curve-trace --port A --diode --ref-voltage 5.0 --step 0.010

    Use a 3.5 V reference to see both forward conduction and moderate reverse
    bias (-1.7 V to +1.5 V), useful for general-purpose diode characterisation:

    ::

        glasgow run curve-trace --port A --diode --ref-voltage 3.5 --stop-current 50
    """
    required_revision = "C2"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        parser.add_argument(
            "--port", type=str, required=True, choices=("A", "B"),
            help="I/O port to sweep (A or B)")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self._port = args.port

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument(
            "--start", type=float, default=MIN_VIO, metavar="VOLTS",
            help="sweep start voltage (default: %(default).1f)")
        parser.add_argument(
            "--stop", type=float, default=MAX_VIO, metavar="VOLTS",
            help="sweep stop voltage (default: %(default).1f)")
        parser.add_argument(
            "--step", type=float, default=DEFAULT_STEP_V, metavar="VOLTS",
            help="voltage step size (default: %(default).3f)")
        parser.add_argument(
            "--settle", type=float, default=DEFAULT_SETTLE_S, metavar="SEC",
            help="settling time after each voltage change (default: %(default).3f)")
        parser.add_argument(
            "--cal", type=str, default=None, metavar="FILE",
            help="open-circuit calibration CSV to subtract no-load current "
                 "(run a sweep with no DUT attached to generate one)")
        parser.add_argument(
            "--sense-voltage", default=False, action="store_true",
            help="read voltage from the Vsense pin (must be wired) instead of the "
                 "commanded DAC voltage")
        parser.add_argument(
            "--stop-current", type=float, default=None, metavar="MILLIAMPS",
            help="stop sweep when current exceeds this value in mA")
        parser.add_argument(
            "--diode", default=False, action="store_true",
            help="diode mode: sweep port A with port B as fixed reference; "
                 "DUT between port A Vio and port B Vio")
        parser.add_argument(
            "--ref-voltage", type=float, default=DEFAULT_REF_V, metavar="VOLTS",
            help="reference voltage on port B in diode mode (default: %(default).1f)")
        parser.add_argument(
            "--format", type=str, default="csv", choices=("csv", "json"),
            help="output format (default: %(default)s)")

    async def run(self, args):
        if args.start < MIN_VIO:
            raise GlasgowAppletError(
                f"start voltage {args.start} V is below minimum {MIN_VIO} V")
        if args.stop > MAX_VIO:
            raise GlasgowAppletError(
                f"stop voltage {args.stop} V is above maximum {MAX_VIO} V")
        if args.start > args.stop:
            raise GlasgowAppletError("start voltage must be <= stop voltage")

        stop_current = None
        if args.stop_current is not None:
            stop_current = args.stop_current / 1000  # mA to A

        cal = {}
        if args.cal is not None:
            cal = _load_cal(args.cal)
            self.logger.info("loaded calibration from %s (%d points)", args.cal, len(cal))

        if args.diode:
            if args.ref_voltage < MIN_VIO or args.ref_voltage > MAX_VIO:
                raise GlasgowAppletError(
                    f"reference voltage {args.ref_voltage} V is outside "
                    f"{MIN_VIO}–{MAX_VIO} V range")

            iface = DiodeTraceInterface(
                self.logger,
                v_start=args.start,
                v_stop=args.stop,
                v_ref=args.ref_voltage,
                step_v=args.step,
                settle_s=args.settle,
                sense_voltage=args.sense_voltage,
                cal=cal,
                stop_current=stop_current,
            )

            n_points = int((args.stop - args.start) / args.step) + 1
            self.logger.info("diode mode: sweeping port A %.3f–%.3f V, "
                "port B ref %.3f V, %d steps of %.0f mV",
                args.start, args.stop, args.ref_voltage, n_points, args.step * 1000)
        else:
            iface = CurveTraceInterface(
                self.logger,
                port=self._port,
                v_start=args.start,
                v_stop=args.stop,
                step_v=args.step,
                settle_s=args.settle,
                sense_voltage=args.sense_voltage,
                cal=cal,
                stop_current=stop_current,
            )

            n_points = int((args.stop - args.start) / args.step) + 1
            self.logger.info("sweeping port %s: %.3f V to %.3f V in %d steps of %.0f mV",
                self._port, args.start, args.stop, n_points, args.step * 1000)

        results = await iface.sweep(self.device)

        if args.format == "csv":
            print("voltage_V,current_A")
            for v, i in results:
                print(f"{v:.4f},{i:.6f}")
        elif args.format == "json":
            data = {
                "v_start": args.start,
                "v_stop": args.stop,
                "step_v": args.step,
                "settle_s": args.settle,
                "points": [{"voltage_V": v, "current_A": i} for v, i in results],
            }
            if args.diode:
                data["mode"] = "diode"
                data["ref_voltage"] = args.ref_voltage
            else:
                data["port"] = self._port
            if args.stop_current is not None:
                data["stop_current_mA"] = args.stop_current
            print(json.dumps(data, indent=2))

        self.logger.info("sweep complete: %d points recorded", len(results))
