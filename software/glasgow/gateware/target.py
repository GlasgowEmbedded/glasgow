import os
import sys
import tempfile
import shutil
from migen import *

from .platform import Platform
from .i2c import I2CSlave
from .registers import Registers
from .fx2 import FX2Arbiter


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


class _IOTriple:
    def __init__(self, nbits):
        self.o = Signal(nbits)
        self.oe = Signal()
        self.i = Signal(nbits)


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

    def __getitem__(self, index):
        if isinstance(index, int):
            nbits = 1
        elif isinstance(index, slice):
            nbits = len(range(index.start or 0, index.stop or nbits, index.step or 1))
        else:
            raise ValueError("I/O port indices must be integers or slices, not {}"
                             .format(type(index).__name__))

        t = _IOTriple(nbits)
        self.comb += [
            self.o[index].eq(t.o),
            self.oe[index].eq(Replicate(t.oe, nbits)),
            t.i.eq(self.i[index])
        ]
        return t


class GlasgowTarget(Module):
    def __init__(self, out_count=0, in_count=0, fifo_depth=128, reg_count=0):
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

        self.submodules.sync_port = _SyncPort(self.platform.request("sync"))
        self.io_ports = [_IOPort(self.platform.request("io")) for _ in range(2)]
        self.submodules += self.io_ports

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

    def get_out_fifo(self, spec):
        """Return an OUT FIFO for I/O port ``spec``."""
        num = self._port_spec_to_number(spec)
        return self.arbiter.out_fifos[num]

    def get_in_fifo(self, spec):
        """Return an IN FIFO for I/O port ``spec``."""
        num = self._port_spec_to_number(spec)
        return self.arbiter.in_fifos[num]

    def get_inout_fifo(self, spec):
        """Return an (IN, OUT) FIFO pair for I/O port ``spec``."""
        num = self._port_spec_to_number(spec)
        return (self.arbiter.in_fifos[num], self.arbiter.out_fifos[num])
