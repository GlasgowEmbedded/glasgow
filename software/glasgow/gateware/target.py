import argparse
from migen import *

from .platform import Platform
from .i2c import I2CSlave


__all__ = ['GlasgowBase', 'GlasgowTest']


class _CRG(Module):
    def __init__(self, platform):
        self.clock_domains.cd_sys = ClockDomain()

        clk_if = platform.request("clk_if")
        self.specials += Instance("SB_GB_IO",
            i_PACKAGE_PIN=clk_if,
            o_GLOBAL_BUFFER_OUTPUT=self.cd_sys.clk)


class GlasgowBase(Module):
    def __init__(self):
        self.platform = Platform()

        self.submodules.crg = _CRG(self.platform)

        self.submodules.i2c_slave = I2CSlave(self.platform.request("i2c"))
        self.comb += self.i2c_slave.address.eq(0b0001000)

    def build(self, *args, **kwargs):
        self.platform.build(self, *args, **kwargs)
