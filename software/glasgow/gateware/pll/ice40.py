# Ref: iCE40 sysCLOCK PLL Design and Usage Guide Technical Note
# Document Number: FPGA-TN-02052-1.2
# Accession: G00077

from __future__ import annotations
from dataclasses import dataclass

from amaranth import *

from . import ConstraintError, Degrees, Absolute, Channel, ClockPlan


__all__ = []


@dataclass(frozen=True)
class _Parameters:
    input_div:    int # range(0, 16)
    feedbk_div:   int # range(0, 128)
    vco_div:      int # range(1, 7)
    pfd_period:   float


def _solve(ref_period: float, out_period: float, *,
           tolerance: float, simple_feedback: bool) -> _Parameters:
    # The documentation in the iCE40 PLL Usage Guide incorrectly lists the
    # maximum value of DIVF as 63, when it is only limited to 63 when using
    # feedback modes other that SIMPLE.
    divr_range = range(0, 16)
    divf_range = range(0, 128) if simple_feedback else range(0, 64)
    divq_range = range(1, 7)

    for divr in divr_range:
        pfd_period = ref_period * (divr + 1)
        if not (10e6 <= 1/pfd_period <= 133e6):
            continue # out of PFD frequency range
        for divf in divf_range:
            if simple_feedback:
                vco_period = pfd_period / (divf + 1)
                if not (533e6 <= 1/vco_period <= 1066e6):
                    continue # out of VCO frequency range
            for divq in divq_range:
                if not simple_feedback:
                    vco_period = pfd_period / (divf + 1) / (2 ** divq)
                    if not 533e6 <= 1/vco_period <= 1066e6:
                        continue # out of VCO frequency range
                gen_period = vco_period * (2 ** divq)
                if not (16e6 <= 1/gen_period <= 450e6):
                    continue
                gen_error = abs(gen_period - out_period) / out_period
                if gen_error < tolerance:
                    return _Parameters(divr, divf, divq, pfd_period)

    raise ConstraintError("no acceptable solution found")


def _create(plan: ClockPlan, ref_domain: str = "sync", *, debug: bool):
    if not (10e6 <= 1 / plan.ref_period <= 133e6):
        raise ConstraintError(f"iCE40 PLL requires input clock frequency to be between 10..133 MHz")
    for chan in plan:
        if not (16e6 <= 1 / chan.period <= 275e6):
            raise ConstraintError(
                f"iCE40 PLL requires output clock frequency to be between 16..275 MHz; "
                f"{1e-6/chan.period:7.3f} MHz requested")

    # t_fdtap = 195e-12 # specified in DS1040
    t_fdtap = 150e-12 # specified in FPGA-TN-02052-1.4; seems more accurate

    # The iCE40 PLL primitive is very restrictive and it is not possible to implement a general
    # algorithm matching outputs to modes. Instead, we match predefined channel configurations
    # that correspond to well-defined configurations. Not all possible configurations are included
    # below; additional cases may be added as necessary.
    use_div7 = False
    out_delay = 0
    feedbk_delay = 0
    match [*plan]:
        case [Channel(phase=None) as ch1]:
            # Single channel. Always use SIMPLE feedback mode.
            out_period = ch1.period
            channels = [(ch1, "GENCLK")]
            feedback = "SIMPLE"

        case [Channel(phase=Absolute(delay)) as ch1] if 0 <= delay <= 15*t_fdtap:
            # Single channel with delay. Use EXTERNAL feedback mode, not DELAY; see the note at
            # the end of the function for an explanation why.
            out_period = ch1.period
            channels = [(ch1, "GENCLK")]
            feedback = "EXTERNAL"
            feedbk_delay = 4
            out_delay = round(delay / t_fdtap)
            assert out_delay in range(0, 16)

        case [Channel(phase=None) as ch1, Channel(phase=None) as ch2]:
            # Dual channel with integer ratio. Use SIMPLE or PHASE_AND_DELAY feedback mode
            # depending on whether DIV/4 or DIV/7 modes are needed.
            if ch1.period < ch2.period:
                ch1, ch2 = ch2, ch1

            if ch1.period == ch2.period * 2:
                out_period = ch2.period
                channels = [(ch1, "GENCLK_HALF"), (ch2, "GENCLK")]
                feedback = "SIMPLE"

            elif ch1.period == ch2.period * 4:
                out_period = ch1.period
                channels = [(ch1, "SHIFTREG_0deg"), (ch2, "GENCLK")]
                feedback = "PHASE_AND_DELAY"
                use_div7 = False

            elif abs(ch1.period - ch2.period * 7) / ch1.period < 1e-6:
                out_period = ch1.period
                channels = [(ch1, "SHIFTREG_0deg"), (ch2, "GENCLK")]
                feedback = "PHASE_AND_DELAY"
                use_div7 = True

            else:
                raise ConstraintError("could not match dual channel frequency ratio")

        case ([Channel(phase=Degrees( 0)) as ch1, Channel(phase=Degrees(90)) as ch2] |
              [Channel(phase=Degrees(90)) as ch2, Channel(phase=Degrees( 0)) as ch1]) \
                if ch1.period == ch2.period:
            out_period = ch1.period
            channels = [(ch1, "SHIFTREG_0deg"), (ch2, "SHIFTREG_90deg")]
            feedback = "PHASE_AND_DELAY"

        case _:
            raise ConstraintError("could not match channel configuration")

    params = _solve(plan.ref_period, out_period, simple_feedback=(feedback == "SIMPLE"),
        tolerance=min(ch.tolerance for ch in plan))
    if 1/params.pfd_period < 17e6:
        filter_range = 1
    elif 1/params.pfd_period < 26e6:
        filter_range = 2
    elif 1/params.pfd_period < 44e6:
        filter_range = 3
    elif 1/params.pfd_period < 66e6:
        filter_range = 4
    elif 1/params.pfd_period < 101e6:
        filter_range = 5
    else:
        filter_range = 6

    m = Module()

    locked = Signal()
    inst_args = dict(
        p_FEEDBACK_PATH=feedback,
        p_SHIFTREG_DIV_MODE=1 if use_div7 else 0,
        p_DIVR=params.input_div,
        p_DIVF=params.feedbk_div,
        p_DIVQ=params.vco_div,
        p_FILTER_RANGE=filter_range,
        p_DELAY_ADJUSTMENT_MODE_FEEDBACK="FIXED",
        p_FDA_FEEDBACK=feedbk_delay,
        p_DELAY_ADJUSTMENT_MODE_RELATIVE="FIXED",
        p_FDA_RELATIVE=out_delay,
        i_REFERENCECLK=ClockSignal(ref_domain),
        i_RESETB=~ResetSignal(ref_domain, allow_reset_less=True),
        o_LOCK=locked,
    )
    if plan.location is not None:
        inst_args.update(dict(
            a_BEL=plan.location,
        ))

    for (chan, out_mode), out_name in zip(channels, ("A", "B")):
        chan_clk = Signal(name=f"PORT{out_name}_clk")
        inst_args.update({
            f"p_PLLOUT_SELECT_PORT{out_name}": out_mode,
            f"o_PLLOUTGLOBAL{out_name}": chan_clk,
        })

        # Synchronize the loss of lock flag to ensure reset is deasserted at the same time in
        # every domain, regardless of skew to the synchronizer.
        chan_lol = Signal(name=f"{out_name}_lol")
        m.submodules[f"{out_name}_lol_reg"] = \
            Instance("SB_DFF", i_C=chan_clk, i_D=~locked, o_Q=chan_lol)

        for domain in plan[chan]:
            # Construct a reset synchronizer out of instances; `cdc.AsyncFFSynchronizer` requires
            # a local clock domain, which could cause naming conflicts in this context.
            rst_flop = {"pos": "SB_DFFS", "neg": "SB_DFFNS"}[domain.clk_edge]
            chan_rst0 = Signal(name=f"PORT{out_name}_{domain.name}_rst0")
            m.submodules[f"PORT{out_name}_{domain.name}_rst_sync0"] = \
                Instance(rst_flop, i_S=chan_lol, i_C=chan_clk, i_D=0,         o_Q=chan_rst0)
            chan_rst1 = Signal(name=f"PORT{out_name}_{domain.name}_rst1")
            m.submodules[f"PORT{out_name}_{domain.name}_rst_sync1"] = \
                Instance(rst_flop, i_S=chan_lol, i_C=chan_clk, i_D=chan_rst0, o_Q=chan_rst1)
            m.d.comb += domain.clk.eq(chan_clk), domain.rst.eq(chan_rst1)

    if feedback == "EXTERNAL":
        # This appears to be the only way to implement a true Zero Delay Buffer on iCE40. It seems
        # like using feedback mode DELAY would work, but the range of FDA_FEEDBACK in this mode is
        # not enough to cancel out the phase shift without using FDA_RELATIVE. Also, using a global
        # output for port B, besides permanently consuming one global network, doesn't result in
        # the correct phase shift in the feedback network either.
        clkfb = Signal()
        inst_args.update(dict(
            p_EXTERNAL_DIVIDE_FACTOR=1,
            i_EXTFEEDBACK=clkfb,
            p_PLLOUT_SELECT_PORTB="GENCLK",
            o_PLLOUTCOREB=clkfb,
        ))

    m.submodules.inst = Instance("SB_PLL40_2F_CORE", **inst_args)

    if debug:
        print(f'Instance("SB_PLL40_2F_CORE",')
        for name, value in inst_args.items():
            print(f"    {name} = {value!r},")
        print(f")")

    return m
