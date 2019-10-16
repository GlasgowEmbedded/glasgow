import asyncio
from nmigen import *
from nmigen.vendor.lattice_ice40 import *

from ..device.hardware import *
from ..gateware import GatewareBuildError


__all__ = ["GlasgowPlatformICE40"]


class GlasgowPlatformICE40(LatticeICE40Platform):
    @property
    def file_templates(self):
        # Do not require yosys to be present for toolchain_prepare() to finish.
        file_templates = dict(super().file_templates)
        del file_templates["{{name}}.debug.v"]
        return file_templates

    def toolchain_program(self, products, name):
        bitstream = products.get("{}.bin".format(name))
        async def do_program():
            device = GlasgowHardwareDevice()
            await device.download_bitstream(bitstream)
            device.close()
        asyncio.get_event_loop().run_until_complete(do_program())

    def get_pll(self, pll, simple_feedback=True):
        if not 10e6 <= pll.f_in <= 133e6:
            pll.logger.error("PLL: f_in (%.3f MHz) must be between 10 and 133 MHz",
                             pll.f_in / 1e6)
            raise GatewareBuildError("PLL f_in out of range")

        if not 16e6 <= pll.f_out <= 275e6:
            pll.logger.error("PLL: f_out (%.3f MHz) must be between 16 and 275 MHz",
                             pll.f_out / 1e6)
            raise GatewareBuildError("PLL f_out out of range")

        # The documentation in the iCE40 PLL Usage Guide incorrectly lists the
        # maximum value of DIVF as 63, when it is only limited to 63 when using
        # feedback modes other that SIMPLE.
        if simple_feedback:
            divf_max = 128
        else:
            divf_max = 64

        variants = []
        for divr in range(0, 16):
            f_pfd = pll.f_in / (divr + 1)
            if not 10e6 <= f_pfd <= 133e6:
                continue

            for divf in range(0, divf_max):
                if simple_feedback:
                    f_vco = f_pfd * (divf + 1)
                    if not 533e6 <= f_vco <= 1066e6:
                        continue

                    for divq in range(1, 7):
                        f_out = f_vco * (2 ** -divq)
                        variants.append((divr, divf, divq, f_pfd, f_out))

                else:
                    for divq in range(1, 7):
                        f_vco = f_pfd * (divf + 1) * (2 ** divq)
                        if not 533e6 <= f_vco <= 1066e6:
                            continue

                        f_out = f_vco * (2 ** -divq)
                        variants.append((divr, divf, divq, f_pfd, f_out))

        if not variants:
            pll.logger.error("PLL: f_in (%.3f MHz) to f_out (%.3f) constraints not satisfiable",
                             pll.f_in / 1e6, pll.f_out / 1e6)
            raise GatewareBuildError("PLL f_in/f_out out of range")

        def f_out_diff(variant):
            *_, f_out = variant
            return abs(f_out - pll.f_out)
        divr, divf, divq, f_pfd, f_out = min(variants, key=f_out_diff)

        if f_pfd < 17:
            filter_range = 1
        elif f_pfd < 26:
            filter_range = 2
        elif f_pfd < 44:
            filter_range = 3
        elif f_pfd < 66:
            filter_range = 4
        elif f_pfd < 101:
            filter_range = 5
        else:
            filter_range = 6

        if simple_feedback:
            feedback_path = "SIMPLE"
        else:
            feedback_path = "NON_SIMPLE"

        ppm = abs(pll.f_out - f_out) / pll.f_out * 1e6

        pll.logger.debug("PLL: f_in=%.3f f_out(req)=%.3f f_out(act)=%.3f [MHz] ppm=%d",
                         pll.f_in / 1e6, pll.f_out / 1e6, f_out / 1e6, ppm)
        pll.logger.trace("iCE40 PLL: feedback_path=%s divr=%d divf=%d divq=%d filter_range=%d",
                         feedback_path, divr, divf, divq, filter_range)

        return Instance("SB_PLL40_CORE",
            p_FEEDBACK_PATH=feedback_path,
            p_PLLOUT_SELECT="GENCLK",
            p_DIVR=divr,
            p_DIVF=divf,
            p_DIVQ=divq,
            p_FILTER_RANGE=filter_range,
            i_REFERENCECLK=ClockSignal(pll.idomain),
            o_PLLOUTCORE=ClockSignal(pll.odomain),
            i_RESETB=~ResetSignal(pll.idomain),
            i_BYPASS=Const(0),
        )
