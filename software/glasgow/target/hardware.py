import hashlib
import os
import sys
import tempfile
import shutil
import logging
from migen import *
import migen.build.generic_platform

from ..gateware.pads import Pads
from ..gateware.i2c import I2CSlave
from ..gateware.registers import I2CRegisters
from ..gateware.fx2 import FX2Arbiter
from ..gateware.platform.lattice import special_overrides
from ..platform import GlasgowPlatformRevAB, GlasgowPlatformRevC
from .analyzer import GlasgowAnalyzer


__all__ = ["GlasgowHardwareTarget"]


logger = logging.getLogger(__name__)


class _CRG(Module):
    def __init__(self, platform):
        self.clock_domains.cd_sys = ClockDomain()
        self.specials += [
            Instance("SB_GB_IO",
                p_PIN_TYPE=C(0b000001, 6),
                io_PACKAGE_PIN=platform.request("clk_if"),
                o_GLOBAL_BUFFER_OUTPUT=self.cd_sys.clk,
            ),
        ]

        self.clock_domains.cd_por = ClockDomain(reset_less=True)
        reset_delay = Signal(max=2047, reset=2047)
        self.comb += [
            self.cd_por.clk.eq(self.cd_sys.clk),
            self.cd_sys.rst.eq(reset_delay != 0)
        ]
        self.sync.por += [
            If(reset_delay != 0,
                reset_delay.eq(reset_delay - 1)
            )
        ]


class GlasgowHardwareTarget(Module):
    sys_clk_freq = 30e6

    def __init__(self, revision, multiplexer_cls=None, with_analyzer=False):
        if revision in ("A0", "B0"):
            self.platform = GlasgowPlatformRevAB()
        elif revision in ("C0",):
            self.platform = GlasgowPlatformRevC()
        else:
            raise ValueError("Unknown revision")

        try:
            unused = self.platform.request("unused")
            self.specials += TSTriple(len(unused)).get_tristate(unused)
        except migen.build.generic_platform.ConstraintError:
            pass

        self.submodules.crg = _CRG(self.platform)
        self.platform.add_period_constraint(self.crg.cd_sys.clk, 1e9 / self.sys_clk_freq)

        self.submodules.i2c_pads  = Pads(self.platform.request("i2c"))
        self.submodules.i2c_slave = I2CSlave(self.i2c_pads)
        self.submodules.registers = I2CRegisters(self.i2c_slave)
        self.comb += self.i2c_slave.address.eq(0b0001000)

        self.submodules.fx2_arbiter = FX2Arbiter(self.platform.request("fx2"))

        self.ports = {
            "A": (8, lambda n: self.platform.request("port_a", n)),
            "B": (8, lambda n: self.platform.request("port_b", n)),
        }

        if multiplexer_cls:
            pipes = "PQ"
            self.submodules.multiplexer = multiplexer_cls(ports=self.ports, pipes="PQ",
                registers=self.registers, fx2_arbiter=self.fx2_arbiter)
        else:
            self.multiplexer = None

        if with_analyzer:
            self.submodules.analyzer = GlasgowAnalyzer(self.registers, self.multiplexer)
        else:
            self.analyzer = None

    # TODO: adjust the logic in do_finalize in migen to recurse?
    def finalize(self, *args, **kwargs):
        if not self.finalized:
            if self.analyzer:
                self.analyzer._finalize_pin_events()

            unused_pins = []
            for width, req in self.ports.values():
                for n in range(width):
                    try:
                        unused_pins.append(req(n))
                    except migen.build.generic_platform.ConstraintError:
                        pass
            for unused_pin in unused_pins:
                self.specials += TSTriple().get_tristate(unused_pin.io)
                if hasattr(unused_pin, "oe"):
                    self.comb += unused_pin.oe.eq(0)

            super().finalize(*args, **kwargs)

    def get_fragment(self):
        # TODO: shouldn't this be done in migen?
        if self.get_fragment_called:
            return self._fragment
        return super().get_fragment()

    def build(self, **kwargs):
        self.platform.build(self, special_overrides=special_overrides, **kwargs)

    def get_verilog(self, **kwargs):
        return self.platform.get_verilog(self, special_overrides=special_overrides)

    def get_bitstream_id(self, **kwargs):
        verilog = str(self.get_verilog(**kwargs))
        return hashlib.sha256(verilog.encode("utf-8")).digest()[:16]

    def get_bitstream(self, build_dir=None, debug=False, **kwargs):
        if build_dir is None:
            build_dir = tempfile.mkdtemp(prefix="glasgow_")
        try:
            self.build(build_dir=build_dir, **kwargs)
            with open(os.path.join(build_dir, "top.bin"), "rb") as f:
                bitstream = f.read()
            if debug:
                shutil.rmtree(build_dir)
        except:
            if debug:
                logger.info("keeping build tree as %s", build_dir)
            raise
        finally:
            if not debug:
                shutil.rmtree(build_dir)
        return bitstream

    def get_build_tree(self, **kwargs):
        build_dir = tempfile.TemporaryDirectory(prefix="glasgow_")
        self.build(build_dir=build_dir.name, run=False)
        return build_dir
