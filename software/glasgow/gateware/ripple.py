import logging
from nmigen import *

__all__ = ["RippleCounter"]

class RippleCounter(Elaboratable):
    def __init__(self, clk, clk_en=None, rst=None, width=8, logger=None):
        self.logger = logger or logging.getLogger(__name__)
        self.clk    = clk
        self.clk_en = clk_en
        self.rst    = rst
        self.width  = width
        self.count  = Signal(width)

    def elaborate(self, platform):
        if not hasattr(platform, "get_ripple_ff_stage"):
            raise NotImplementedError("No Ripple Counter support for platform")

        m = Module()

        clk_chain = self.clk

        for i in range(self.width):
            d_out = Signal()
            clk_en = self.clk_en if i == 0 else None
            m.submodules += platform.get_ripple_ff_stage(d_out, clk_chain, clk_en, self.rst)
            m.d.comb += self.count[i].eq(d_out)
            clk_chain = d_out

        return m
