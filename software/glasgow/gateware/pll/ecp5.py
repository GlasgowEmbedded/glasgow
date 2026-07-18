# Ref: ECP5 and ECP5-5G sysCLOCK PLL/DLL Design and User Guide Technical Note
# Document Number: FPGA-TN-02200-1.4
# Accession: G00127

# Calculations derived from Project Trellis, principally done by Myrtle Shah, then extended by
# Catherine 'whitequark'.

from __future__ import annotations
from typing import Literal, Any
from dataclasses import dataclass

from amaranth import *

from . import ConstraintError, Degrees, Absolute, Channel as GenericChannel, ClockPlan


__all__ = ["Channel"]


@dataclass(frozen=True, kw_only=True)
class Channel(GenericChannel): # importable as `ecp5.Channel`
    # Any clock output can be used with primary clock tree, but only CLKOP/CLKOS can be used]
    # to drive edge clocks (on the edges adjacent to the PLL's location).
    usage: Literal["primary", "edge"] = "primary"


_OUTPUT_NAMES = ["CLKOP", "CLKOS", "CLKOS2", "CLKOS3"]


@dataclass(frozen=True, kw_only=True)
class _InstanceChannel:
    name: Literal["CLKOP", "CLKOS", "CLKOS2", "CLKOS3"]
    frequency: float = 0.0 # in Hz; informational
    divisor: int = 1 # range(1, 129)
    cphase: int = 0 # range(0, 128); cycles of fVCO
    fphase: int = 0 # range(0, 8); 45° increments of fVCO
    feedback: bool = False
    domains: list[ClockDomain]

    def as_args(self, clk_signal: Signal) -> dict[str, Any]:
        args = {
            f"a_FREQUENCY_PIN_{self.name}": f"{self.frequency / 1e6:.3f}",
            f"p_{self.name}_ENABLE": "ENABLED",
            f"p_{self.name}_DIV": self.divisor,
            f"p_{self.name}_CPHASE": self.cphase,
            f"p_{self.name}_FPHASE": self.fphase,
            f"o_{self.name}": clk_signal,
        }
        if self.feedback:
            args.update({
                "p_FEEDBK_PATH": self.name,
                "i_CLKFB": clk_signal,
            })
        return args


def _solve(plan: ClockPlan, *, debug: bool):
    if (count := len(plan)) > 4:
        raise ConstraintError(f"ECP5 PLL has 4 output channels, {count} requested")
    if not (8e6 <= 1 / plan.ref_period <= 400e6):
        raise ConstraintError(f"ECP5 PLL requires input clock frequency to be between 8..400 MHz")

    # Only CLKOP and CLKOS can be routed to edge clocks. Make sure channels that will be used for
    # edge clocks (if any) are using those outputs.
    if (count := len([ch for ch in plan if isinstance(ch, Channel) and ch.usage == "edge"])) > 2:
        raise ConstraintError(f"ECP5 PLL has 2 edge-capable output channels, {count} requested")
    sorted_plan = sorted(plan, key=lambda ch:
        0 if isinstance(ch, Channel) and ch.usage == "edge" else 1)

    for input_div in range(1, 129):
        pfd_period = plan.ref_period * input_div
        if not (3.125e6 <= 1 / pfd_period <= 400e6):
            continue # out of PFD frequency range
        for feedbk_div in range(1, 81):
            # We need to select one of the outputs to take feedback from, since the multiplication
            # factor combines both the feedback divider and the output divider.
            for feedbk_chan in sorted_plan:
                if feedbk_chan.phase is not None:
                    continue # feedback channel cannot be phase shifted
                for output_div in range(1, 129):
                    vco_period = pfd_period / (feedbk_div * output_div)
                    if not (400e6 <= 1 / vco_period <= 800e6):
                        continue # out of VCO frequency range
                    # We found a valid configuration for the feedback path, but it may not
                    # result in the desired output frequencies.
                    valid = True
                    for idx, chan in enumerate(sorted_plan):
                        if chan == feedbk_chan:
                            chan_div = output_div
                        else:
                            chan_div = round(chan.period / vco_period)
                            if chan_div not in range(1, 129):
                                valid = False # out of range
                                break
                        chan_period = vco_period * chan_div
                        chan_error = abs(chan_period - chan.period) / chan.period
                        if debug:
                            vco_freq = 1e-6 / vco_period
                            chan_freq = 1e-6 / chan_period
                            error_ppm = round(chan_error * 1e6)
                            print(f"[ch{idx}] {vco_freq=:7.3f} {chan_freq=:7.3f} {error_ppm=}")
                        if chan_error > chan.tolerance:
                            valid = False
                            break
                    if not valid:
                        continue
                    # Phase calculations. This has to happen recursively, since channels can refer
                    # to each other in any order.
                    def get_phase(chan: GenericChannel,
                            output_div=output_div, vco_period=vco_period):
                        if chan.phase_ref is None:
                            # Shift feedback channel by 180 degrees using coarse adjustment only.
                            # Diamond does this, but the exact reason is not known. Hardware tests
                            # reveal no actual difference in phase.
                            ref_phase = (output_div // 2) << 3
                        else:
                            ref_phase = get_phase(chan.phase_ref)
                        match chan.phase:
                            case None:
                                chan_shift = 0
                            case Absolute(delay):
                                chan_shift = delay
                            case Degrees(delay):
                                chan_shift = chan.period * (delay / 360)
                            case _:
                                raise TypeError(f"expected phase delay, not {chan.phase!r}")
                        return ref_phase + chan_shift / vco_period * 8
                    # We found a configuration that produces the desired output frequencies.
                    # Convert it to an instance argument list.
                    result = []
                    for chan, name in zip(sorted_plan, _OUTPUT_NAMES):
                        chan_div = round(chan.period / vco_period)
                        chan_phase = round(get_phase(chan))
                        result.append(_InstanceChannel(
                            name=name,
                            divisor=chan_div,
                            frequency=1 / (vco_period * chan_div), # (actual)
                            cphase=chan_phase >> 3,
                            fphase=chan_phase & 7,
                            feedback=(chan == feedbk_chan),
                            domains=plan[chan],
                        ))
                    return input_div, feedbk_div, result

    raise ConstraintError("no acceptable solution found")


def _create(plan: ClockPlan, ref_domain: str = "sync", *, debug: bool):
    input_div, feedbk_div, channels = _solve(plan, debug=False) # debug=True is noisy

    m = Module()

    locked = Signal()
    inst_args = dict(
        a_FREQUENCY_PIN_CLKI=f"{1e-6 / plan.ref_period:.3f}",
        p_PLLRST_ENA="ENABLED",
        p_CLKI_DIV=input_div,
        p_CLKFB_DIV=feedbk_div,
        i_CLKI=ClockSignal(ref_domain),
        i_RST=ResetSignal(ref_domain, allow_reset_less=True),
        o_LOCK=locked,
    )
    # These hardcoded values are taken from ecppll, where they are also hardcoded. This does
    # not match the complex algorithm Diamond has that is implemented in C++.
    inst_args.update(dict(
        a_ICP_CURRENT="12",
        a_LPF_RESISTOR="8",
    ))
    if plan.location is not None:
        inst_args.update(dict(
            a_BEL=plan.location,
        ))

    for chan in channels:
        chan_clk = Signal(name=f"{chan.name}_clk")
        inst_args.update(chan.as_args(chan_clk))

        # Synchronize the loss of lock flag to ensure reset is deasserted at the same time in
        # every domain, regardless of skew to the synchronizer.
        chan_lol = Signal(name=f"{chan.name}_lol")
        m.submodules[f"{chan.name}_lol_reg"] = \
            Instance("FD1S3AX", i_CK=chan_clk, i_D=~locked, o_Q=chan_lol)

        for domain in chan.domains:
            # Construct a reset synchronizer out of instances; `cdc.AsyncFFSynchronizer` requires
            # a local clock domain, which could cause naming conflicts in this context.
            rst_flop = {"pos": "FD1S3BX", "neg": "FD1S2BX"}[domain.clk_edge]
            chan_rst0 = Signal(name=f"{chan.name}_{domain.name}_rst0")
            m.submodules[f"{chan.name}_{domain.name}_rst_sync0"] = \
                Instance(rst_flop, i_PD=chan_lol, i_CK=chan_clk, i_D=0,         o_Q=chan_rst0)
            chan_rst1 = Signal(name=f"{chan.name}_{domain.name}_rst1")
            m.submodules[f"{chan.name}_{domain.name}_rst_sync1"] = \
                Instance(rst_flop, i_PD=chan_lol, i_CK=chan_clk, i_D=chan_rst0, o_Q=chan_rst1)

            m.d.comb += domain.clk.eq(chan_clk), domain.rst.eq(chan_rst1)

    m.submodules.inst = Instance("EHXPLLL", **inst_args)

    if debug:
        print(f'Instance("EHXPLLL",')
        for name, value in inst_args.items():
            print(f"    {name} = {value!r},")
        print(f")")

    return m
