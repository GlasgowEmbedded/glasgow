from nmigen.compat import *

from ..gateware.registers import Registers


__all__ = ["GlasgowSimulationTarget"]


class GlasgowSimulationTarget(Module):
    sys_clk_freq = 30e6

    def __init__(self):
        self.submodules.registers = Registers()
