import unittest
import re
import random

from amaranth import Elaboratable, Module
from amaranth.sim import Tick

from glasgow.gateware import simulation_test
from glasgow.gateware.clockgen import ClockGen


class ClockGenTestbench(Elaboratable):
    def __init__(self):
        self.cyc = None

    def elaborate(self, platform):
        m = Module()

        assert self.cyc is not None
        m.submodules.dut = self.dut = ClockGen(self.cyc)

        return m


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

    def test_freq_exact(self):
        cyc, actual_output_hz, deviation_ppm = ClockGen.calculate(input_hz=100, output_hz=2)
        self.assertEqual(cyc, 50)
        self.assertEqual(actual_output_hz, 2)
        self.assertEqual(deviation_ppm, 0)


class ClockGenSimTestCase(unittest.TestCase):
    def setUp(self):
        self.tb = ClockGenTestbench()

    def configure(self, tb, cyc):
        tb.cyc = cyc

    @simulation_test(cyc=2)
    def test_half_freq(self, tb):
        for _ in range(5):
            yield Tick()
            self.assertEqual((yield tb.dut.clk), 1)
            self.assertEqual((yield tb.dut.stb_r), 1)
            yield Tick()
            self.assertEqual((yield tb.dut.clk), 0)
            self.assertEqual((yield tb.dut.stb_f), 1)

    @simulation_test(cyc=random.randrange(3, 101))
    def test_freq_counter(self, tb):
        while (yield tb.dut.clk) != 1:
            yield Tick()

        for _ in range(5):
            self.assertEqual((yield tb.dut.stb_r), 1)
            for _ in range(tb.cyc // 2):
                self.assertEqual((yield tb.dut.clk), 1)
                yield Tick()
                self.assertEqual((yield tb.dut.stb_r), 0)

            self.assertEqual((yield tb.dut.stb_f), 1)
            for _ in range(tb.cyc - tb.cyc // 2):
                self.assertEqual((yield tb.dut.clk), 0)
                yield Tick()
                self.assertEqual((yield tb.dut.stb_f), 0)
