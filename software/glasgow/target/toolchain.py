from abc import ABCMeta, abstractmethod
import os
import sys
import hashlib
import importlib.metadata
import shutil
import sysconfig
import logging
import subprocess
import re
from ..support.lazy import lazy


__all__ = ["ToolchainNotFound", "find_toolchain"]


logger = logging.getLogger(__name__)


class ToolchainNotFound(Exception):
    pass


class Tool(metaclass=ABCMeta):
    def __init__(self, name):
        self.name = str(name)

    @property
    def env_var_name(self):
        """Name of environment variable used by Amaranth to configure tool location."""
        # Identical to amaranth._toolchain.tool_env_var.
        return self.name.upper().replace("-", "_").replace("+", "X")

    @property
    @abstractmethod
    def command(self):
        """Command name for invoking the tool.

        Full path to the executable that can be used to run the tool, or ``None`` if the tool
        is not available.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def available(self):
        """Tool availability.

        ``True`` if the tool is installed, ``False`` otherwise. Installed binary may still not
        be runnable, or might be too old to be useful.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def version(self):
        """Tool version number.

        ``None`` if version number could not be determined, or a tool-specific tuple if it could.
        """
        raise NotImplementedError

    @property
    @abstractmethod
    def identifier(self):
        """Unique tool identifier.

        Returns an array of 16 bytes that uniquely identifies the behavior of this particular tool
        in its entirety, but has no other meaning. Typically implemented by hashing the binary and
        its data files.
        """

    def __repr__(self):
        return f"<{self.__class__.__module__}.{self.__class__.__name__} {self.name}>"



class WasmTool(Tool):
    PREFIX = "yowasp-"

    @property
    def python_package(self):
        if self.name == "yosys" or self.name.startswith("nextpnr-"):
            return self.PREFIX + self.name
        if self.name == "icepack":
            return self.PREFIX + "nextpnr-ice40"
        if self.name == "ecppack":
            return self.PREFIX + "nextpnr-ecp5"
        raise NotImplementedError(f"Python package for tool {self.name} is not known")

    @property
    def available(self):
        try:
            importlib.metadata.metadata(self.python_package)
            return True
        except importlib.metadata.PackageNotFoundError:
            return False

    @property
    def command(self):
        if self.available:
            basename = self.PREFIX + self.name
            # We cannot assume that the command is on PATH and accessible by its basename. This
            # will not be true when Glasgow is running from a pipx virtual environment (which isn't
            # activated when the `glasgow` script is run). Also, our build environment does not
            # even *have* PATH.
            return os.path.join(sysconfig.get_path('scripts'), basename)

    @property
    def version(self):
        if self.available:
            # Running Wasm tools for the first time can incur a significant delay, so use
            # the version from the Python package metadata (which is guaranteed to be the same).
            # This makes querying the version at least as fast as for the native tools.
            return (*importlib.metadata.version(self.python_package).split("."),)

    @property
    def identifier(self):
        if self.available:
            hasher = hashlib.blake2s()
            for file_entry in importlib.metadata.files(self.python_package):
                if file_entry.hash is None:
                    continue # RECORD, *.pyc, etc
                hasher.update(file_entry.hash.value.encode("utf-8"))
            return hasher.digest()[:16]


class SystemTool(Tool):
    @staticmethod
    def get_output(args):
        return subprocess.run(args,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8").stdout.strip()

    @property
    def available(self):
        return self.command is not None

    @property
    def command(self):
        return shutil.which(os.environ.get(self.env_var_name, self.name))

    @property
    def version(self):
        if self.available:
            if self.name == "yosys":
                # Yosys 0.26+50 (git sha1 ef8ed21a2, ccache clang 11.0.1-2 -O0 -fPIC)
                raw_version = self.get_output([self.command, "--version"])
                if matches := re.match(r"^Yosys ([^\s]+) \(git sha1 ([0-9a-f]+)", raw_version):
                    version = matches[1].replace("+", ".").split(".")
                    return (*version, "g" + matches[2])

            elif self.name.startswith("nextpnr-"):
                # nextpnr-ice40 -- Nex... ...ce and Route (Version nextpnr-0.2-48-g20e595e2)
                raw_version = self.get_output([self.command, "--version"])
                if matches := re.match(r".+?\(Version .+?-(.+)\)$", raw_version):
                    return (*matches[1].replace("-", ".").split("."),)

            elif self.name == "icepack":
                # does not have versions; does not have an option to return version
                return ("0",)

            elif self.name == "ecppack":
                # Project Trellis ecppack Version 1.3-3-g6845f33
                raw_version = self.get_output([self.command, "--version"])
                if matches := re.match(r".+?Version (.+)$", raw_version):
                    return (*matches[1].replace("-", ".").split("."),)

            else:
                raise NotImplementedError(f"Cannot extract version from tool {self.name!r}")

    def _iter_data_files(self):
        def iter_files(start):
            for root, dirs, files in os.walk(start):
                for file in files:
                    yield os.path.join(root, file)

        if self.available:
            if self.name == "yosys":
                if yosys_datdir := self.get_output([f"{self.command}-config", "--datdir"]):
                    return iter_files(yosys_datdir)
            else:
                # It is unclear if it is feasible to get at the data files and other dependencies
                # for nextpnr. However, while it is possible to ship chipdb separately (and Wasm
                # builds do so), the overwhelming majority of native builds is likely shipping
                # nxetpnr as a self-contained binary that loads no data.
                #
                # Icepack is a self-contained binary. Ecppack is similar to nextpnr.
                #
                # This is likely fine.
                return iter([])

    _identifier_cache = None

    # To the Nix person who replaces this with something more sensible: please message @whitequark
    @property
    def identifier(self):
        if self.available:
            if self._identifier_cache is None:
                hasher = hashlib.blake2s()
                with open(self.command, "rb") as file:
                    hasher.update(file.read())
                for data_filename in self._iter_data_files():
                    with open(data_filename, "rb") as file:
                        hasher.update(file.read())
                self._identifier_cache = hasher.digest()[:16]
            return self._identifier_cache


class Toolchain:
    def __init__(self, tools):
        self.tools = list(tools)

    @property
    def available(self):
        """Toolchain availability.

        ``True`` if every tool is available, ``False`` otherwise.
        """
        return all(tool.available for tool in self.tools)

    @property
    def missing(self):
        """Tools that are missing from the toolchain.

        An iterator that yields the name of every tool whose version could not be determined,
        because it is either unavailable or crashes when run.
        """
        return (tool.name for tool in self.tools if not tool.available or tool.version is None)

    @property
    def env_vars(self):
        """Environment variables to bring the toolchain in scope.

        An environment dictionary that includes entries for every of the tools included in this
        toolchain, and nothing else.

        Can be passed to :meth:`amaranth.build.run.BuildPlan.execute_local()` as the `env`
        argument in order to build a bitstream using this toolchain while isolating the build
        from any environmental impurity.
        """
        return {tool.env_var_name: tool.command for tool in self.tools}

    @property
    def versions(self):
        """Versions of tools.

        A dictionary that maps names of tools to their versions.
        """
        return {tool.name: tool.version for tool in self.tools}

    @property
    def identifier(self):
        """Unique toolchain identifier.

        Returns an array of 16 bytes that uniquely identifies this particular collection of tools,
        but has no other meaning.
        """
        hasher = hashlib.blake2s()
        for tool in self.tools:
            if not tool.available:
                return None
            hasher.update(tool.identifier)
        return hasher.digest()[:16]

    def __str__(self):
        return ", ".join(f"{name} {'.'.join(ver or ('(unavailable)',))}"
                         for name, ver in self.versions.items())

    def __repr__(self):
        return (f"<{self.__class__.__module__}.{self.__class__.__name__} " +
                " ".join(f"{tool.command}=={'.'.join(tool.version or ('unavailable',))}"
                         for tool in self.tools) +
                f">")


def find_toolchain(tools=("yosys", "nextpnr-ice40", "icepack"), *, quiet=False):
    """Discover a toolchain.

    Returns a :class:`Toolchain` that includes all of the requested tools chosen according to
    the ``GLASGOW_TOOLCHAIN`` environment variable, or raises :exn:`ToolchainNotFound` if such
    toolchain isn't available within the constraints.
    """
    env_var_name = "GLASGOW_TOOLCHAIN"
    available_toolchains = {
        "builtin": Toolchain(map(WasmTool,   tools)),
        "system":  Toolchain(map(SystemTool, tools)),
    }

    kinds = os.environ.get(env_var_name, ",".join(available_toolchains.keys())).split(",")
    for kind in kinds:
        if kind not in available_toolchains:
            if quiet:
                return
            logger.error(f"the {env_var_name} environment variable contains "
                         f"an unrecognized toolchain kind {kind!r}, available: "
                         f"{', '.join(available_toolchains)}")
            raise ToolchainNotFound(f"Unknown toolchain kind {kind!r} in {env_var_name}")

    selected_toolchains = {kind: available_toolchains[kind] for kind in kinds}
    for kind, toolchain in selected_toolchains.items():
        if toolchain.available:
            logger.debug(f"using toolchain {kind!r} ({toolchain})")
            for tool in toolchain.tools:
                logger.trace(f"tool {tool.name!r} is invoked as {tool.command!r}")
            logger.trace(f"toolchain ID is %s", lazy(lambda: toolchain.identifier.hex()))
            for tool in toolchain.tools:
                logger.trace(f"tool ID of {tool.name!r} is %s", lazy(lambda: tool.identifier.hex()))
            return toolchain

    else:
        if quiet:
            return
        examined = ", ".join(f"{kind} (missing {', '.join(selected_toolchains[kind].missing)})"
                             for kind in kinds)
        if env_var_name in os.environ:
            logger.error(f"could not find a usable FPGA toolchain; "
                         f"examined (according to {env_var_name}): {examined}")
        else:
            logger.error(f"could not find a usable FPGA toolchain; examined: {examined}")
            logger.error(f"consider reinstalling the package with the 'builtin-toolchain' "
                         f"feature enabled, "
                         f"e.g.: `pipx install --force -e glasgow/software[builtin-toolchain]`")
        raise ToolchainNotFound(f"No usable toolchain is available (examined: {', '.join(kinds)})")
