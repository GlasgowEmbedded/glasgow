import unittest
import re

from glasgow.gateware.clockgen import ClockGen


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
