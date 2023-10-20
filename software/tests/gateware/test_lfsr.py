import unittest
from amaranth import *

from glasgow.gateware import simulation_test
from glasgow.gateware.lfsr import LinearFeedbackShiftRegister


class LFSRTestbench(Elaboratable):
    def __init__(self, **kwargs):
        self.dut = LinearFeedbackShiftRegister(**kwargs)

    def elaborate(self, platform):
        return self.dut


class LFSRTestCase(unittest.TestCase):
    def setUp(self):
        self.tb = LFSRTestbench(degree=16, taps=(16, 14, 13, 11))

    @simulation_test
    def test_generate(self, tb):
        soft_values = list(self.tb.dut.generate())
        hard_values = []
        for _ in range(len(soft_values)):
            hard_values.append((yield self.tb.dut.value))
            yield

        self.assertEqual(len(soft_values), 65535)
        self.assertEqual(hard_values, soft_values)
