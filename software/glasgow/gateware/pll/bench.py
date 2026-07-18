import textwrap
import argparse
import importlib

from amaranth import *
from amaranth.lib import io
from amaranth.build.dsl import Resource, Pins

from . import *


__all__ = []


def main():
    def frequency(arg) -> float:
        if arg.endswith("M"):
            return 1e-6/float(arg[:-1])
        else:
            raise argparse.ArgumentTypeError(f"invalid frequency {arg}")

    def phase(arg) -> Degrees | Absolute | None:
        if arg == "":
            return None
        elif arg.endswith("deg"):
            return Degrees(float(arg[:-3]))
        elif arg.endswith("ns"):
            return Absolute(1e-9*float(arg[:-2]))
        else:
            raise argparse.ArgumentTypeError(f"invalid phase {arg}")

    def phase_ref(arg) -> int:
        return int(arg)

    def channel(arg) -> tuple[str, float, Degrees | Absolute | None, int | None]:
        match arg.split(","):
            case [pin, arg_freq]:
                return pin, frequency(arg_freq), None, None
            case [pin, arg_freq, arg_phase]:
                return pin, frequency(arg_freq), phase(arg_phase), None
            case [pin, arg_freq, arg_phase, arg_phase_ref]:
                return pin, frequency(arg_freq), phase(arg_phase), phase_ref(arg_phase_ref)
            case _:
                raise argparse.ArgumentTypeError(f"invalid channel {arg}")

    parser = argparse.ArgumentParser("pll-bench", description=textwrap.dedent("""
    PLL hardware testing tool. Generates and programs a bitstream with the specified clock plan,
    allowing confirmation of its function with an oscilloscope.

    Channel configuration can be specified as follows:
        1. `A0,10M`: output 10 MHz via pin A0
        2. `A0,10M,90deg`: same as (1), but delay by 90 degrees
        3. `A0,10M,10ns`: same as (1), but delay by 10 nanoseconds
        4. `A0,10M,90deg,0`: same as (1), but use channel 0 (indexing is zero-based) as reference
    """), formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument(
        "-p", "--platform", metavar="CLASS", type=str, required=True,
        help="platform class path (e.g.: `glasgow.hardware.platform.rev_d:GlasgowRevD0Platform`)")
    parser.add_argument(
        "-X", "--program", default=False, action="store_true",
        help="program the generated bitstream")
    parser.add_argument(
        "--ref-output", metavar="PIN", type=str,
        help="also output reference clock on PIN")
    parser.add_argument(
        "channels", metavar="CHANNEL", type=channel, nargs="+",
        help="channel configuration(s)")

    args = parser.parse_args()

    mod_path, mod_attr = args.platform.split(":")
    platform_cls = getattr(importlib.import_module(mod_path), mod_attr)
    platform = platform_cls()

    m = Module()

    def add_output(pin, domain):
        platform.add_resources([Resource(f"{domain}_clk", 0, Pins(pin))])
        io_pin = platform.request(f"{domain}_clk", dir="-")
        m.submodules += (clk_buf := io.DDRBuffer("o", io_pin, o_domain=domain))
        m.d.comb += clk_buf.o.eq(Mux(ResetSignal(domain, allow_reset_less=True), 0, Cat(0,1)))

    if args.ref_output is not None:
        add_output(args.ref_output, "sync")

    plan = ClockPlan(ref_period=1/platform.default_clk_frequency)
    channels = []
    for index, (ch_pin, ch_period, ch_phase, ch_phase_ref) in enumerate(args.channels):
        channels.append(channel := Channel(
            period=ch_period,
            phase=ch_phase,
            phase_ref=channels[ch_phase_ref] if ch_phase_ref is not None else None,
        ))
        m.domains += plan.add_domain(channel, name=f"output{index}")
        add_output(ch_pin, f"output{index}")

    m.submodules.pll = plan.create(platform, debug=True)

    platform.build(m, do_program=args.program)


if __name__ == "__main__":
    main()
