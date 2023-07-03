import hashlib
import os
import sys
import tempfile
import shutil
import logging
from amaranth import *
from amaranth.build import ResourceError

from ..gateware.i2c import I2CTarget
from ..gateware.registers import I2CRegisters
from ..gateware.fx2_crossbar import FX2Crossbar
from ..platform.all import *
from .analyzer import GlasgowAnalyzer


__all__ = ["GlasgowHardwareTarget"]


logger = logging.getLogger(__name__)


class GlasgowHardwareTarget(Elaboratable):
    def __init__(self, revision, multiplexer_cls=None, with_analyzer=False):
        if revision in ("A0", "B0"):
            self.platform = GlasgowPlatformRevAB()
            self.sys_clk_freq = 30e6
        elif revision in "C0":
            self.platform = GlasgowPlatformRevC0()
            self.sys_clk_freq = 48e6
        elif revision in ("C1", "C2", "C3"):
            self.platform = GlasgowPlatformRevC123()
            self.sys_clk_freq = 48e6
        else:
            raise ValueError("Unknown revision")

        try:
            self.platform.request("unused")
        except ResourceError:
            pass

        self._submodules = []

        self.i2c_target = I2CTarget(self.platform.request("i2c"))
        self.registers = I2CRegisters(self.i2c_target)

        self.fx2_crossbar = FX2Crossbar(self.platform.request("fx2", xdr={
            "sloe": 1, "slrd": 1, "slwr": 1, "pktend": 1, "fifoadr": 1, "flag": 2, "fd": 2
        }))

        self.ports = {
            "A": (8, lambda n: self.platform.request("port_a", n)),
            "B": (8, lambda n: self.platform.request("port_b", n)),
        }

        if multiplexer_cls:
            pipes = "PQ"
            self.multiplexer = multiplexer_cls(ports=self.ports, pipes="PQ",
                registers=self.registers, fx2_crossbar=self.fx2_crossbar)
        else:
            self.multiplexer = None

        if with_analyzer:
            self.analyzer = GlasgowAnalyzer(self.registers, self.multiplexer)
        else:
            self.analyzer = None

    def elaborate(self, platform):
        m = Module()

        m.submodules.i2c_target = self.i2c_target
        m.submodules.registers = self.registers
        m.submodules.fx2_crossbar = self.fx2_crossbar
        if self.multiplexer is not None:
            m.submodules.multiplexer = self.multiplexer
        if self.analyzer is not None:
            self.analyzer._finalize_pin_events()
            m.submodules.analyzer = self.analyzer
        m.submodules += self._submodules

        m.d.comb += self.i2c_target.address.eq(0b0001000)

        unused_pins = []
        for width, req in self.ports.values():
            for n in range(width):
                try:
                    unused_pins.append(req(n))
                except ResourceError:
                    pass
        for unused_pin in unused_pins:
            if hasattr(unused_pin, "oe"):
                m.d.comb += unused_pin.oe.o.eq(0)

        return m

    def add_submodule(self, sub):
        self._submodules.append(sub)

    def build_plan(self, **kwargs):
        overrides = {
            "synth_opts": "-abc9",
            "nextpnr_opts": "--placer heap",
        }
        overrides.update(kwargs)
        return GlasgowBuildPlan(self.platform.prepare(self, **overrides))


class GlasgowBuildPlan:
    def __init__(self, lower):
        self.lower   = lower
        self._digest = None

    @property
    def rtlil(self):
        return self.lower.files["top.il"]

    @property
    def bitstream_id(self):
        if self._digest is None:
            self._digest = self.lower.digest()[:16]
        return self._digest

    def archive(self, filename):
        self.lower.archive(filename)

    def execute(self, build_dir=None, *, debug=False):
        if build_dir is None:
            build_dir = tempfile.mkdtemp(prefix="glasgow_")
        try:
            products  = self.lower.execute_local(build_dir)
            bitstream = products.get("top.bin")
        except:
            if debug:
                logger.info("keeping build tree as %s", build_dir)
            raise
        finally:
            if not debug:
                shutil.rmtree(build_dir)
        return bitstream
