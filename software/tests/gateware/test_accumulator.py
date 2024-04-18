import unittest
from amaranth import *
from amaranth.sim import Tick

from glasgow.gateware import simulation_test
from glasgow.gateware.accumulator import Accumulator


class AccumulatorTestCase(unittest.TestCase):
    def setUp(self):
        self.tb = Accumulator(5, stage_width=2)

    @simulation_test()
    def test_counter(self, tb):
        total = 0
        queue = [0] * (self.tb.stages + 1)
        for i in range(100):
            addend = i * 2137 % 32
            total += addend
            total %= 32
            queue.append(total)
            self.assertEqual(queue[0], (yield self.tb.sum))
            del queue[0]
            yield self.tb.addend.eq(addend)
            yield Tick()
