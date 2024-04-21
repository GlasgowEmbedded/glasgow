import operator

from amaranth import *
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out


class Accumulator(wiring.Component):
    """Pipelined arithmetic accumulator.

    Computes :py:`new_sum = old_sum + addend` using at most :py:`stage_width` wide adders, with
    a latency of :py:`(width + stage_width - 1) // stage_width + 1` cycles and throughput of one
    addition per cycle.

    Members
    -------
    addend : In(width)
        Addend.
    sum : Out(width)
        Accumulated sum.
    """
    def __init__(self, width, *, stage_width=16):
        self._width = operator.index(width)
        self._stage_width = operator.index(stage_width)
        assert self._width >= 1 and self._stage_width >= 1
        self._stages = 1 + (self._width + self._stage_width - 1) // self._stage_width
        super().__init__({
            "addend": In(self._width),
            "sum": Out(self._width)
        })

    @property
    def stages(self):
        return self._stages

    def elaborate(self, platform):
        m = Module()

        carry = Const(0)
        addend = Signal.like(self.addend)
        result = Cat()

        m.d.sync += addend.eq(self.addend)

        for index, start_at in enumerate(range(0, self._width, self._stage_width)):
            stage_width = min(self._width - start_at, self._stage_width)

            carry_next = Signal(name=f"carry{index}")
            addend_next = Signal.like(addend[stage_width:], name=f"addend{index}")
            result_next = Signal.like(result, name=f"result{index}")
            stage = Signal(stage_width, name=f"stage{index}")

            m.d.sync += Cat(stage, carry_next).eq(stage + addend[:stage_width] + carry)
            m.d.sync += addend_next.eq(addend[stage_width:])
            m.d.sync += result_next.eq(result)

            carry = carry_next
            addend = addend_next
            result = Cat(result_next, stage)

        m.d.comb += self.sum.eq(result)

        return m

