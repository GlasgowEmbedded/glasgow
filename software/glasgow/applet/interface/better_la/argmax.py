from typing import List
from amaranth import *

class ArgMax(Elaboratable):
    """
    Find the maximum value and the index of the maximum value of a list of signals using a 
    comparison-tree.
    """
    def __init__(self, signals: List[Signal], sync_levels=[]):
        self.signals = signals

        self.sync_levels = sync_levels

        self.max_value = Signal.like(signals[0])
        self.max_idx = Signal(range(len(signals)))

    def elaborate(self, platform):
        m = Module()

        def build_tree(signals, offset=0, level=0):
            suffix = f"l{level}_{offset}to{offset+len(signals)}"

            domain = m.d.sync if level in self.sync_levels else m.d.comb

            if len(signals) == 1:
                return signals[0], offset
            elif len(signals) == 2:
                a, b = signals
                value = Signal.like(self.signals[0], name=f"max_val_{suffix}")
                index = Signal.like(self.max_idx, name=f"max_idx_{suffix}")
                domain += [
                    value.eq(Mux(a > b, a, b)),
                    index.eq(Mux(a > b, offset, offset + 1))
                ]
                return value, index
            else:
                half = len(signals) // 2
                a, a_idx = build_tree(signals[:half], offset=offset, level=level+1)
                b, b_idx = build_tree(signals[half:], offset=offset + half, level=level+1)
                value = Signal.like(self.signals[0], name=f"max_val_{suffix}")
                index = Signal.like(self.max_idx, name=f"max_idx_{suffix}")
                domain += [
                    value.eq(Mux(a > b, a, b)),
                    index.eq(Mux(a > b, a_idx, b_idx))
                ]
                return value, index
            
        val, idx = build_tree(self.signals)
        m.d.comb += self.max_value.eq(val)
        m.d.comb += self.max_idx.eq(idx)

        return m
