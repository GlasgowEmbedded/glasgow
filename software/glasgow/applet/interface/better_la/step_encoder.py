from typing import List
from amaranth import *

class StepEncoder(Elaboratable):
    def __init__(self, input: Signal, possible_values: List[int]):
        self.input = input
        self.possible_values = possible_values

        self.output = Signal(range(len(possible_values)))

    def elaborate(self, platform):
        m = Module()

        for i, v in enumerate(self.possible_values):
            with m.If(self.input >= v):
                m.d.comb += self.output.eq(i)

        # we add this to have a sync domain and be able to use the simulation helpers
        a = Signal()
        m.d.sync += a.eq(~a)

        return m