import argparse
from migen import *

from .platform import Platform
from .i2c import I2CSlave
from .registers import Registers


__all__ = ['GlasgowBase']


class _CRG(Module):
    def __init__(self, platform):
        self.clock_domains.cd_sys = ClockDomain()

        clk_if = platform.request("clk_if")
        self.specials += Instance("SB_GB_IO",
            i_PACKAGE_PIN=clk_if,
            o_GLOBAL_BUFFER_OUTPUT=self.cd_sys.clk)


class GlasgowBase(Module):
    def __init__(self, reg_count=0):
        self.platform = Platform()

        self.submodules.crg = _CRG(self.platform)

        if reg_count > 0:
            self.submodules.i2c_slave = I2CSlave(self.platform.request("i2c"))
            self.comb += self.i2c_slave.address.eq(0b0001000)

            self.submodules.registers = Registers(self.i2c_slave, reg_count)

    def build(self, *args, **kwargs):
        self.platform.build(self, *args, **kwargs)


class TestToggleIO(GlasgowBase):
    def __init__(self):
        super().__init__(reg_count=1)

        cnt = Signal(15)
        out = Signal()
        self.sync += [
            cnt.eq(cnt + 1),
            If(cnt == 0,
                out.eq(~out))
        ]

        sync = self.platform.request("sync")
        ioa = self.platform.request("io")
        iob = self.platform.request("io")
        self.comb += [
            sync.eq(out),
            ioa.eq(Replicate(out, 8)),
            iob.eq(Replicate(out, 8)),
        ]
