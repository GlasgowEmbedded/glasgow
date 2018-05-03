import os
import sys
import tempfile
import shutil
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

    def build(self, **kwargs):
        self.platform.build(self, **kwargs)

    def get_verilog(self, **kwargs):
        return self.platform.get_verilog(self)

    def get_bitstream(self, build_dir=None, debug=False, **kwargs):
        if build_dir is None:
            build_dir = tempfile.mkdtemp(prefix="glasgow_")
        try:
            self.build(build_dir=build_dir)
            with open(os.path.join(build_dir, "top.bin"), "rb") as f:
                bitstream = f.read()
            if debug:
                shutil.rmtree(build_dir)
        except:
            if debug:
                print("Keeping build tree as " + build_dir, file=sys.stderr)
            raise
        finally:
            if not debug:
                shutil.rmtree(build_dir)
        return bitstream


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
