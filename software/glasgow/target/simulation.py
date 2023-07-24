from amaranth import *

from ..gateware.registers import Registers


__all__ = ["GlasgowSimulationTarget"]


class GlasgowSimulationTarget(Elaboratable):
    sys_clk_freq = 30e6

    def __init__(self, multiplexer_cls=None):
        self.registers = Registers()
        if multiplexer_cls is not None:
            self.multiplexer = multiplexer_cls()
        else:
            self.multiplexer = None
        self._submodules = []

    def add_submodule(self, sub):
        self._submodules.append(sub)

    def elaborate(self, platform):
        m = Module()

        m.submodules.registers = self.registers
        if self.multiplexer is not None:
            m.submodules.multiplexer = self.multiplexer
        m.submodules += self._submodules

        return m
