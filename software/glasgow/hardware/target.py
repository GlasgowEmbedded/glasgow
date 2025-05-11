import logging

from amaranth import *
from amaranth.lib import io
from amaranth.build import ResourceError

from ..gateware.i2c import I2CTarget
from ..gateware.registers import I2CRegisters
from ..gateware.fx2_crossbar import FX2Crossbar
from .toolchain import find_toolchain
from .build_plan import GlasgowBuildPlan


__all__ = ["GlasgowHardwareTarget"]


logger = logging.getLogger(__name__)


class GlasgowHardwareTarget(Elaboratable):
    def __init__(self, revision, multiplexer_cls=None):
        if revision in ("A0", "B0"):
            from .platform.rev_ab import GlasgowRevABPlatform
            self.platform = GlasgowRevABPlatform()
            self.sys_clk_freq = 30e6
        elif revision in "C0":
            from .platform.rev_c import GlasgowRevC0Platform
            self.platform = GlasgowRevC0Platform()
            self.sys_clk_freq = 48e6
        elif revision in ("C1", "C2", "C3"):
            from .platform.rev_c import GlasgowRevC123Platform
            self.platform = GlasgowRevC123Platform()
            self.sys_clk_freq = 48e6
        else:
            raise ValueError("Unknown revision")

        self._submodules = []

        self.i2c_target = I2CTarget(self.platform.request("i2c", dir={"scl": "-", "sda": "-"}))
        self.registers = I2CRegisters(self.i2c_target)

        # Always add a register at address 0x00, to be able to check that the FPGA configuration
        # succeeded and that I2C communication works.
        addr_health_check = self.registers.add_existing_ro(0xa5)
        assert addr_health_check == 0x00

        self.fx2_crossbar = FX2Crossbar(self.platform.request("fx2", dir={
            "sloe": "-", "slrd": "-", "slwr": "-", "pktend": "-", "fifoadr": "-",
            "flag": "-", "fd": "-"
        }))

        self.ports = {
            "A": (8, lambda n: self.platform.request("port_a", n, dir={"io": "-", "oe": "-"})),
            "B": (8, lambda n: self.platform.request("port_b", n, dir={"io": "-", "oe": "-"})),
        }

        if multiplexer_cls:
            self.multiplexer = multiplexer_cls(ports=self.ports, pipes="PQ",
                registers=self.registers, fx2_crossbar=self.fx2_crossbar)
        else:
            self.multiplexer = None

    def elaborate(self, platform):
        m = Module()

        m.submodules.i2c_target = self.i2c_target
        m.submodules.registers = self.registers
        m.submodules.fx2_crossbar = self.fx2_crossbar
        if self.multiplexer is not None:
            m.submodules.multiplexer = self.multiplexer
        m.submodules += self._submodules

        m.d.comb += self.i2c_target.address.eq(0b0001000)

        unused_pins = []
        for width, request in self.ports.values():
            for idx in range(width):
                try:
                    unused_pins.append(request(idx))
                except ResourceError:
                    pass
        for idx, unused_pin in enumerate(unused_pins):
            if hasattr(unused_pin, "oe"):
                m.submodules[f"unused_pin_{idx}"] = io.Buffer("o", unused_pin.oe)

        try:
            # See note in `rev_c.py`.
            unused_balls = self.platform.request("unused", dir="-")
            m.submodules[f"unused_balls"] = io.Buffer("io", unused_balls)
        except ResourceError:
            pass

        return m

    def add_submodule(self, sub):
        self._submodules.append(sub)

    def build_plan(self, **kwargs):
        overrides = {
            # always emit complete build log to stdout; whether it's displayed is controlled by
            # the usual logging options, e.g. `-vv` or `-v -F build`
            "verbose": True,
            # don't flush cache if all that's changed is the location of a Signal; nobody really
            # looks at the RTLIL src attributes anyway
            "emit_src": False,
            # latest yosys and nextpnr versions default to this configuration, but we support some
            # older ones in case yowasp isn't available and this keeps the configuration consistent
            "synth_opts": "-abc9",
            "nextpnr_opts": "--placer heap",
        }
        overrides.update(kwargs)
        return GlasgowBuildPlan(find_toolchain(), self.platform.prepare(self, **overrides))
