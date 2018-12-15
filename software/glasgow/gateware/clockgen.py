from nmigen.compat import *


__all__ = ["ClockGen"]


class ClockGen(Module):
    """
    A clock generator. The purpose of a clock generator is to use an input clock signal to
    generate an output clock (50% duty cycle pulses) and rising/falling strobe (1 input clock
    period wide pulses preceding the rising/falling edge of output clock pulses) signals using
    nothing but LUT/FF logic, i.e. no PLLs, hard dividers, etc. This implies that the output clock
    has no precise phase relationship to the input clock.

    There are two primary contexts where this is useful. The first is using the system clock
    to generate a derived clocks for some synchronous interface, which does not have to be very
    precise or in phase to any other clock, but has to cover a very wide range of frequencies.
    For example, an SPI interface with a user-defined frequency should cover the range from,
    at least, 20 MHz to 1 kHz--that's five orders of magnitude. A PLL is flexible, but would
    not be able to cover most of this range, and it is also a very scarce resource; a counter
    is cheap and limited only in resolution.

    The second is triggering events in the system clock domain at an approximate phase relationship
    to the derived clock domain, typically to a) setup or sample a bus, and b) insert wait cycles.
    The output of a PLL can be used to do so, but it complicates timing; a strobe signal fully
    synchronous to the system clock domain is guaranteed to work.

    The primary limitations of this approach is that the output frequency is at most the same as
    the input frequency, and the maximum error, i.e. discrepancy between requested and actual
    output frequency, can be as high as 33.(3)%, generally increasing towards the higher end of
    the output frequency range.

    While the gateware may appear trivial (a counter and a register), there are two edge cases
    that need to be handled, namely output of 50% of input frequency and 100% of input frequency.

    :type cyc: int
    :param cyc:
        Output clock period, in terms of input clock periods. Use :meth:`derive` to compute this
        value, check for edge cases, and (optionally) log the deviation from requested frequency
        as well as 50% duty cycle.
    """

    def __init__(self, cyc):
        self.clk   = Signal()
        self.stb_r = Signal()
        self.stb_f = Signal()

        ###

        if cyc == 0:
            # Special case: output frequency equal to input frequency.
            # Implementation: wire.
            self.comb += [
                self.clk.eq(ClockSignal()),
                self.stb_r.eq(1),
                self.stb_f.eq(1),
            ]

        if cyc == 1:
            # Special case: output frequency half of input frequency.
            # Implementation: flip-flop.
            self.sync += [
                self.clk.eq(~self.clk),
            ]
            self.comb += [
                self.stb_r.eq(~self.clk),
                self.stb_f.eq(self.clk),
            ]

        if cyc >= 2:
            # General case.
            # Implementation: counter.
            counter = Signal(max=cyc)
            clk_r   = Signal()
            self.sync += [
                counter.eq(counter - 1),
                If(counter == 0,
                    counter.eq(cyc - 1),
                ),
                If(counter == cyc // 2,
                    self.clk.eq(1),
                ).Elif(counter == 0,
                    self.clk.eq(0),
                ),
                clk_r.eq(self.clk),
            ]
            self.comb += [
                self.stb_r.eq(~clk_r &  self.clk),
                self.stb_f.eq( clk_r & ~self.clk),
            ]

    @staticmethod
    def calculate(input_hz, output_hz, max_deviation_ppm=None, min_cyc=None):
        """
        Calculate the integer period ratio for dividing an ``input_hz`` clock to an approximately
        ``output_hz`` clock, and return the divisor as well as the actual output frequency and
        its deviation from requested output frequency.

        Raises ``ValueError`` on any of the following conditions:

            * The output frequency is higher than input frequency.
            * The output frequency differs from requested output frequency by more than
              ``max_deviation_ppm`` parts per million.
            * The output period is lower than ``min_cyc`` input periods.
        """
        if output_hz <= 0:
            raise ValueError("output frequency {:.3f} kHz is not positive"
                             .format(output_hz / 1000))
        if output_hz > input_hz:
            raise ValueError("output frequency {:.3f} kHz is higher than input frequency "
                             "{:.3f} kHz"
                             .format(output_hz / 1000, input_hz / 1000))
        if min_cyc is not None and output_hz * min_cyc > input_hz:
            raise ValueError("output frequency {:.3f} kHz requires a period smaller than {:d} "
                             "cycles at input frequency {:.3f} kHz"
                             .format(output_hz / 1000, min_cyc, input_hz / 1000))

        cyc = round(input_hz // output_hz) - 1
        actual_output_hz = input_hz / (cyc + 1)
        deviation_ppm = round(1000000 * (actual_output_hz - output_hz) // output_hz)

        if max_deviation_ppm is not None and deviation_ppm > max_deviation_ppm:
            raise ValueError("output frequency {:.3f} kHz deviates from requested frequency "
                             "{:.3f} kHz by {:d} ppm, which is higher than {:d} ppm"
                             .format(actual_output_hz / 1000, output_hz / 1000,
                                     deviation_ppm, max_deviation_ppm))

        return cyc, actual_output_hz, deviation_ppm

    @classmethod
    def derive(cls, input_hz, output_hz, max_deviation_ppm=None, min_cyc=None,
               logger=None, clock_name=None):
        """
        Derive the parameter for :class:`ClockGen`, and log the input frequency, requested
        output frequency, actual output frequency, frequency deviation, and actual duty cycle.

        See :meth:`calculate` for details.
        """
        cyc, actual_output_hz, deviation_ppm = \
            cls.calculate(input_hz, output_hz, max_deviation_ppm, min_cyc)

        if logger is not None:
            if clock_name is None:
                clock = "clock"
            else:
                clock = "clock {}".format(clock_name)
            if cyc in (0, 1):
                duty = 50
            else:
                duty = (cyc // 2) / cyc * 100
            logger.debug("%s in=%.3f req=%.3f out=%.3f [kHz] error=%d [ppm] duty=%.1f%%",
                         clock, input_hz / 1000, output_hz / 1000, actual_output_hz / 1000,
                         deviation_ppm, duty)

        return cyc

# -------------------------------------------------------------------------------------------------

import unittest
import re


class ClockGenTestCase(unittest.TestCase):
    def test_freq_negative(self):
        with self.assertRaisesRegex(ValueError,
                re.escape("output frequency -0.001 kHz is not positive")):
            ClockGen.calculate(input_hz=1e6, output_hz=-1)

    def test_freq_too_high(self):
        with self.assertRaisesRegex(ValueError,
                re.escape("output frequency 2000.000 kHz is higher than input frequency "
                          "1000.000 kHz")):
            ClockGen.calculate(input_hz=1e6, output_hz=2e6)

    def test_period_too_low(self):
        with self.assertRaisesRegex(ValueError,
                re.escape("output frequency 500.000 kHz requires a period smaller than 3 cycles "
                          "at input frequency 1000.000 kHz")):
            ClockGen.calculate(input_hz=1e6, output_hz=500e3, min_cyc=3)

    def test_deviation_too_high(self):
        with self.assertRaisesRegex(ValueError,
                re.escape("output frequency 30000.000 kHz deviates from requested frequency "
                          "18000.000 kHz by 666666 ppm, which is higher than 50000 ppm")):
            ClockGen.calculate(input_hz=30e6, output_hz=18e6, max_deviation_ppm=50000)
