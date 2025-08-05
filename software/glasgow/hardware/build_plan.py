from typing import Never, Optional, BinaryIO
import os
import sys
import logging
import hashlib
import pathlib
import tempfile
import shutil
from asyncio import subprocess

import platformdirs
from amaranth.build.run import BuildPlan

from .toolchain import Toolchain


__all__ = ["GlasgowBuildPlan"]


logger = logging.getLogger(__name__)


class GatewareBuildError(Exception):
    pass


class GlasgowBuildPlan:
    def __init__(self, inner: BuildPlan, toolchain: Toolchain):
        self._inner     = inner
        self._toolchain = toolchain

        hasher = hashlib.blake2s()
        hasher.update(self._inner.digest())
        hasher.update(self._toolchain.identifier)
        self._bitstream_id = hasher.digest()[:16]

    @property
    def rtlil(self) -> str:
        return self._inner.files["top.il"]

    def archive(self, file: os.PathLike | BinaryIO):
        self._inner.archive(file)

    @property
    def toolchain(self) -> Toolchain:
        return self._toolchain

    @property
    def bitstream_id(self) -> bytes:
        return self._bitstream_id

    def _report_build_failure(self, stdout_lines: list[str], exit_code: int) -> Never:
        if not logger.isEnabledFor(logging.TRACE): # don't print the log twice
            for stdout_line in stdout_lines:
                logger.info(f"build: %s", stdout_line.decode().rstrip())
        if logger.isEnabledFor(logging.INFO):
            raise GatewareBuildError(
                f"gateware build failed with exit code {exit_code}; "
                f"see build log above for details")
        else:
            raise GatewareBuildError(
                f"gateware build failed with exit code {exit_code}; "
                f"re-run `glasgow` without `-q` to view build log")

    # this function is only public for paranoid people who don't trust our excellent cache system.
    # it's very unlikely to fail, but people are rightfully distrustful of cache systems, so
    # be sympathetic to that.
    async def execute_shell(self, build_dir: Optional[os.PathLike] = None, *,
                            debug: bool = False) -> tuple[bytes, bytes]:
        if build_dir is None:
            build_dir = tempfile.mkdtemp(prefix="glasgow_")
        try:
            # copied from `BuildPlan.execute_local`, which was inlined into this function because
            # Glasgow has unique (caching) needs. see the comment in that function for details.
            self._inner.extract(build_dir)
            if os.name == 'nt':
                args = ["cmd", "/c", f"call {self._inner.script}.bat"]
            else:
                args = ["sh", f"{self._inner.script}.sh"]

            environ = self._toolchain.env_vars
            if os.name == 'nt':
                # Windows has some environment variables that are required by the OS runtime:
                # - SYSTEMROOT: required for child Python processes to initialize properly
                # - PROCESSOR_ARCHITECTURE: required for YoWASP (used by wasmtime)
                # - APPDATA: required for YoWASP (used by pip executable stub)
                for var in ("PROCESSOR_ARCHITECTURE", "SYSTEMROOT", "APPDATA"):
                    environ[var] = os.environ[var]

            # collect stdout (so that it can be reproduced if a log for a cached bitstream is
            # requested later) and also log it with the appropriate level
            stdout_lines = []
            process = await subprocess.create_subprocess_exec(
                *args, cwd=build_dir, env=environ,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            async for stdout_line in process.stdout:
                stdout_lines.append(stdout_line)
                logger.trace(f"build: %s", stdout_line.decode().rstrip())
            if await process.wait():
                self._report_build_failure(stdout_lines, process.returncode)

            bitstream_data = (pathlib.Path(build_dir) / "top.bin").read_bytes()
            stdout_data = b"".join(stdout_lines)
            return bitstream_data, stdout_data
        except:
            if debug:
                logger.info("keeping build tree as %s", build_dir)
            raise
        finally:
            if not debug:
                shutil.rmtree(build_dir)

    async def _execute_js(self) -> tuple[bytes, bytes]:
        import js
        import pyodide.ffi

        stdout_lines = []
        def on_stdout_line(stdout_line):
            stdout_lines.append(stdout_line)
            logger.trace(f"build: %s", stdout_line.rstrip())
        source_files = pyodide.ffi.to_js(self._inner.files, dict_converter=js.Object.fromEntries)
        build_script = f"{self._inner.script}.json"
        build_result = await js.glasgowToolchain.build(
            source_files, build_script, on_stdout_line)
        if build_result.code == 0:
            bitstream_data = build_result.files.as_object_map()["top.bin"].to_py()
            stdout_data = "".join(stdout_lines).encode()
            return bitstream_data, stdout_data
        else:
            self._report_build_failure(stdout_lines, build_result.code)
            assert False

    async def get_bitstream(self, *, debug=False) -> bytes:
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
            if sys.platform == "emscripten":
                build_result = await self._execute_js()
            else:
                build_result = await self.execute_shell(debug=debug)
            bitstream_data, stdout_data = build_result
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
