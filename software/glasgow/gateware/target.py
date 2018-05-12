import os
import sys
import tempfile
import shutil
from migen import *

from .platform import Platform
from .i2c import I2CSlave
from .registers import Registers
from .fx2 import FX2Arbiter


__all__ = ['GlasgowBase']


class _CRG(Module):
    def __init__(self, platform):
        clk_if = platform.request("clk_if")

        self.clock_domains.cd_por = ClockDomain(reset_less=True)
        self.clock_domains.cd_sys = ClockDomain()
        self.specials += [
            Instance("SB_GB_IO",
                i_PACKAGE_PIN=clk_if,
                o_GLOBAL_BUFFER_OUTPUT=self.cd_por.clk),
        ]

        reset_delay = Signal(max=2047, reset=2047)
        self.comb += [
            self.cd_sys.clk.eq(self.cd_por.clk),
            self.cd_sys.rst.eq(reset_delay != 0)
        ]
        self.sync.por += [
            If(reset_delay != 0,
                reset_delay.eq(reset_delay - 1)
            )
        ]


class GlasgowBase(Module):
    def __init__(self, out_count=0, in_count=0, fifo_depth=511, reg_count=0):
        self.platform = Platform()

        self.submodules.crg = _CRG(self.platform)

        self.submodules.i2c_slave = I2CSlave(self.platform.request("i2c"))
        self.comb += self.i2c_slave.address.eq(0b0001000)

        if reg_count > 0:
            self.submodules.registers = Registers(self.i2c_slave, reg_count)

        self.submodules.arbiter = FX2Arbiter(self.platform.request("fx2"),
                                             out_count=out_count,
                                             in_count=in_count,
                                             depth=fifo_depth)

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
        super().__init__()

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


class TestMirrorI2C(GlasgowBase):
    def __init__(self):
        super().__init__()

        i2c = self.platform.request("i2c")
        ioa = self.platform.request("io")
        self.comb += ioa[0:2].eq(Cat(i2c.scl, i2c.sda))


class TestGenSeq(GlasgowBase):
    def __init__(self):
        super().__init__(out_count=1, in_count=2)

        out0 = self.arbiter.get_out(0)
        in0 = self.arbiter.get_in(0)
        in1 = self.arbiter.get_in(1)

        stb = Signal()
        re  = Signal()
        self.sync += [
            out0.re.eq(out0.readable),
            re.eq(out0.re),
            stb.eq(out0.re & ~re)
        ]

        act = Signal()
        nam = Signal()
        cnt = Signal(8)
        lim = Signal(8)
        self.sync += [
            If(stb,
                act.eq(1),
                nam.eq(1),
                lim.eq(out0.dout),
                cnt.eq(0),
            ),
            If(act,
                nam.eq(~nam),
                in0.we.eq(1),
                in1.we.eq(1),
                If(nam,
                    in0.din.eq(b'A'[0]),
                    in1.din.eq(b'B'[0]),
                ).Else(
                    in0.din.eq(cnt),
                    in1.din.eq(cnt),
                    cnt.eq(cnt + 1),
                    If(cnt + 1 == lim,
                        act.eq(0)
                    )
                ),
            ).Else(
                in0.we.eq(0),
                in1.we.eq(0),
            ),
        ]
