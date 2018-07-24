import hashlib
import os
import sys
import tempfile
import shutil
from migen import *

from .platform import Platform
from ..gateware.pads import Pads
from ..gateware.i2c import I2CSlave
from ..gateware.i2c_regs import I2CRegisters
from ..gateware.fx2 import FX2Arbiter


__all__ = ["GlasgowTarget"]


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


class _SyncPort(Module):
    def __init__(self, inout):
        self.oe = Signal()
        self.i  = Signal()

        self.specials += \
            Instance("SB_IO",
                p_PIN_TYPE=0b101001, # PIN_OUTPUT_TRISTATE|PIN_INPUT
                io_PACKAGE_PIN=inout,
                i_OUTPUT_ENABLE=self.oe,
                i_D_OUT_0=0,
                o_D_IN_0=self.i,
            )


class _IOPort(Module):
    def __init__(self, inout, nbits=8):
        self.nbits = nbits
        self.o  = Signal(nbits)
        self.oe = Signal(nbits)
        self.i  = Signal(nbits)

        for n in range(nbits):
            self.specials += \
                Instance("SB_IO",
                    p_PIN_TYPE=0b101001, # PIN_OUTPUT_TRISTATE|PIN_INPUT
                    io_PACKAGE_PIN=inout[n],
                    i_OUTPUT_ENABLE=self.oe[n],
                    i_D_OUT_0=self.o[n],
                    o_D_IN_0=self.i[n],
                )

    def __getitem__(self, key):
        if key is None:
            return None
        elif isinstance(key, int):
            indices = (key,)
        elif isinstance(key, slice):
            indices = range(key.start or 0, key.stop or self.nbits, key.step or 1)
        elif isinstance(key, (tuple, list)):
            indices = tuple(key)
        else:
            raise ValueError("I/O port indices must be integers, slices, tuples or lists, not {}"
                             .format(type(key).__name__))

        res = TSTriple(len(indices))
        for res_idx, port_idx in enumerate(indices):
            self.comb += [
                self.o[port_idx].eq(res.o[res_idx]),
                self.oe[port_idx].eq(res.oe),
                res.i[res_idx].eq(self.i[port_idx])
            ]
        return res


class GlasgowTarget(Module):
    def __init__(self):
        self.platform = Platform()

        self.submodules.crg = _CRG(self.platform)

        self.submodules.i2c_slave = I2CSlave(Pads(self.platform.request("i2c")))
        self.submodules.registers = I2CRegisters(self.i2c_slave)
        self.comb += self.i2c_slave.address.eq(0b0001000)

        self.submodules.arbiter = FX2Arbiter(self.platform.request("fx2"))

        self.submodules.sync_port = _SyncPort(self.platform.request("sync"))
        self.io_ports = [_IOPort(self.platform.request("io")) for _ in range(2)]
        self.submodules += self.io_ports

    def get_fragment(self):
        # TODO: shouldn't this be done in migen?
        if self.get_fragment_called:
            return self._fragment
        return super().get_fragment()

    def build(self, **kwargs):
        self.platform.build(self, **kwargs)

    def get_verilog(self, **kwargs):
        return self.platform.get_verilog(self)

    def get_bitstream_id(self, **kwargs):
        verilog = str(self.get_verilog(**kwargs))
        return hashlib.sha256(verilog.encode("utf-8")).digest()[:16]

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

    @staticmethod
    def _port_spec_to_number(spec):
        if spec == "A":
            return 0
        if spec == "B":
            return 1
        raise ValueError("Unknown I/O port {}".format(spec))

    def get_io_port(self, spec):
        """Return an I/O port ``spec``."""
        num = self._port_spec_to_number(spec)
        return self.io_ports[num]

    def get_out_fifo(self, spec, **kwargs):
        """Return an OUT FIFO for I/O port ``spec``."""
        num = self._port_spec_to_number(spec)
        return self.arbiter.get_out_fifo(num, **kwargs)

    def get_in_fifo(self, spec, **kwargs):
        """Return an IN FIFO for I/O port ``spec``."""
        num = self._port_spec_to_number(spec)
        return self.arbiter.get_in_fifo(num, **kwargs)

    def get_inout_fifo(self, spec, **kwargs):
        """Return an (IN, OUT) FIFO pair for I/O port ``spec``."""
        num = self._port_spec_to_number(spec)
        return (self.arbiter.get_in_fifo(num, **kwargs),
                self.arbiter.get_out_fifo(num, **kwargs))
