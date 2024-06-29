import os
import sys
import tempfile
import shutil
import logging
import hashlib
import pathlib
import subprocess
import platformdirs
from amaranth import *
from amaranth.lib import io
from amaranth.build import ResourceError

from ..gateware import GatewareBuildError
from ..gateware.i2c import I2CTarget
from ..gateware.registers import I2CRegisters
from ..gateware.fx2_crossbar import FX2Crossbar
from .analyzer import GlasgowAnalyzer
from .toolchain import find_toolchain


__all__ = ["GlasgowHardwareTarget"]


logger = logging.getLogger(__name__)


class GlasgowHardwareTarget(Elaboratable):
    def __init__(self, revision, multiplexer_cls=None, with_analyzer=False):
        if revision in ("A0", "B0"):
            from ..platform.rev_ab import GlasgowRevABPlatform
            self.platform = GlasgowRevABPlatform()
            self.sys_clk_freq = 30e6
        elif revision in "C0":
            from ..platform.rev_c import GlasgowRevC0Platform
            self.platform = GlasgowRevC0Platform()
            self.sys_clk_freq = 48e6
        elif revision in ("C1", "C2", "C3"):
            from ..platform.rev_c import GlasgowRevC123Platform
            self.platform = GlasgowRevC123Platform()
            self.sys_clk_freq = 48e6
        else:
            raise ValueError("Unknown revision")

        try:
            self.platform.request("unused", dir="-")
        except ResourceError:
            pass

        self._submodules = []

        self.i2c_target = I2CTarget(self.platform.request("i2c", dir={"scl": "-", "sda": "-"}))
        self.registers = I2CRegisters(self.i2c_target)

        self.fx2_crossbar = FX2Crossbar(self.platform.request("fx2", dir={
            "sloe": "-", "slrd": "-", "slwr": "-", "pktend": "-", "fifoadr": "-",
            "flag": "-", "fd": "-"
        }))

        self.ports = {
            "A": (8, lambda n: self.platform.request("port_a", n, dir={"io": "-", "oe": "-"})),
            "B": (8, lambda n: self.platform.request("port_b", n, dir={"io": "-", "oe": "-"})),
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

        # FIXME: amaranth-lang/amaranth#1402
        m.domains.sync = ClockDomain()
        m.submodules.clk_buffer = clk_buffer = io.Buffer("i", platform.request("clk_if", dir="-"))
        m.d.comb += ClockSignal().eq(clk_buffer.i)
        platform.add_clock_constraint(clk_buffer.i, platform.default_clk_frequency)

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
                m.submodules += io.Buffer("o", unused_pin.oe)

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


class GlasgowBuildPlan:
    def __init__(self, toolchain, lower):
        self.toolchain = toolchain
        self.lower = lower
        self._bitstream_id = None

    @property
    def rtlil(self):
        return self.lower.files["top.il"]

    @property
    def bitstream_id(self):
        if self._bitstream_id is None:
            hasher = hashlib.blake2s()
            hasher.update(self.toolchain.identifier)
            hasher.update(self.lower.digest())
            self._bitstream_id = hasher.digest()[:16]
        return self._bitstream_id

    def archive(self, filename):
        self.lower.archive(filename)

    # this function is only public for paranoid people who don't trust our excellent cache system.
    # it's very unlikely to fail, but people are rightfully distrustful of cache systems, so
    # be sympathetic to that.
    def execute(self, build_dir=None, *, debug=False):
        if build_dir is None:
            build_dir = tempfile.mkdtemp(prefix="glasgow_")
        try:
            # copied from `BuildPlan.execute_local`, which was inlined into this function because
            # Glasgow has unique (caching) needs. see the comment in that function for details.
            self.lower.extract(build_dir)
            if os.name == 'nt':
                args = ["cmd", "/c", f"call {self.lower.script}.bat"]
            else:
                args = ["sh", f"{self.lower.script}.sh"]

            environ = self.toolchain.env_vars
            if os.name == 'nt':
                # Windows has some environment variables that are required by the OS runtime:
                # - SYSTEMROOT: required for child Python processes to initialize properly
                # - PROCESSOR_ARCHITECTURE: required for YoWASP (used by wasmtime)
                for var in ("PROCESSOR_ARCHITECTURE", "SYSTEMROOT"):
                    environ[var] = os.environ[var]

            # collect stdout (so that it can be reproduced if a log for a cached bitstream is
            # requested later) and also log it with the appropriate level
            stdout_lines = []
            with subprocess.Popen(
                    args, cwd=build_dir, env=environ, text=True,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT) as proc:
                for stdout_line in proc.stdout:
                    stdout_lines.append(stdout_line)
                    logger.trace(f"build: %s", stdout_line.rstrip())
                if proc.wait():
                    if not logger.isEnabledFor(logging.TRACE): # don't print the log twice
                        for stdout_line in stdout_lines:
                            logger.info(f"build: %s", stdout_line.rstrip())
                    if logger.isEnabledFor(logging.INFO):
                        raise GatewareBuildError(
                            f"gateware build failed with exit code {proc.returncode}; "
                            f"see build log above for details")
                    else:
                        raise GatewareBuildError(
                            f"gateware build failed with exit code {proc.returncode}; "
                            f"re-run `glasgow` without `-q` to view build log")

            bitstream_data = (pathlib.Path(build_dir) / "top.bin").read_bytes()
            stdout_data = "".join(stdout_lines).encode()
        except:
            if debug:
                logger.info("keeping build tree as %s", build_dir)
            raise
        finally:
            if not debug:
                shutil.rmtree(build_dir)
        return bitstream_data, stdout_data

    def get_bitstream(self, *, debug=False):
        # locate the caches in the platform-appropriate cache directory; bitstreams aren't large,
        # but it is good etiquette to indicate to the OS that they can be wiped without concern
        cache_path = platformdirs.user_cache_path("GlasgowEmbedded", appauthor=False)
        bitstream_filename = cache_path / "bitstreams" / self.bitstream_id.hex()
        stdout_filename = bitstream_filename.with_suffix(".output")
        # ensure that the cache and the build log (a) exist, (b) aren't corrupted; if anything goes
        # wrong at this stage, proceed as-if the cache was never there
        cache_exists = (bitstream_filename.exists() and stdout_filename.exists())
        if cache_exists:
            with bitstream_filename.open("rb") as bitstream_file:
                bitstream_hash = bitstream_file.read(hashlib.blake2s().digest_size)
                bitstream_data = bitstream_file.read()
                if hashlib.blake2s(bitstream_data).digest() != bitstream_hash:
                    cache_exists = False
            with stdout_filename.open("rb") as stdout_file:
                stdout_hash = stdout_file.read(hashlib.blake2s().digest_size * 2 + 1)
                stdout_data = stdout_file.read()
                if hashlib.blake2s(stdout_data).hexdigest().encode() != stdout_hash.rstrip():
                    cache_exists = False
        if cache_exists:
            # the cache exists; skip building the bitstream, and reproduce the stdout to our log
            # if anyone would actually see it
            logger.debug(f"bitstream ID {self.bitstream_id.hex()} is cached")
            logger.trace(f"bitstream was read from {str(bitstream_filename)!r}")
            if logger.isEnabledFor(logging.TRACE):
                for stdout_line in stdout_data.decode().splitlines():
                    logger.trace(f"build: %s", stdout_line)
        else:
            # the cache does not exist; build it (`execute` directs the stdout to our log, so we
            # don't have to forward it here) and write the artifacts to the platform-appropriate
            # cache directory
            logger.debug(f"bitstream ID {self.bitstream_id.hex()} is not cached, executing build")
            bitstream_data, stdout_data = self.execute(debug=debug)
            bitstream_hash = hashlib.blake2s(bitstream_data).digest()
            stdout_hash = hashlib.blake2s(stdout_data).hexdigest().encode()
            bitstream_filename.parent.mkdir(parents=True, exist_ok=True)
            with bitstream_filename.open("wb") as bitstream_file:
                bitstream_file.write(bitstream_hash)
                bitstream_file.write(bitstream_data)
            with stdout_filename.open("wb") as stdout_file:
                stdout_file.write(stdout_hash + b"\n") # keep it a text file
                stdout_file.write(stdout_data)
            logger.trace(f"bitstream was written to {str(bitstream_filename)!r}")
        # finally, we have a bitstream! and chances are, we have obtained it much faster than we
        # would have otherwise.
        return bitstream_data
