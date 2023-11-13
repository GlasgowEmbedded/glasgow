import re
import os
import sys
import traceback
import importlib.metadata
import packaging.requirements
import pathlib
import sysconfig
import logging


__all__ = ["PluginRequirementsUnmet", "PluginLoadError", "PluginMetadata"]


logger = logging.getLogger(__loader__.name)


# TODO(py3.10): remove
# Ubuntu 20.04 ships an outdated Python version with a serious bug impacting importlib.metadata:
# https://github.com/python/importlib_metadata/issues/369
# It is a pain to update Python on that Ubuntu version, so just patch it here to match the fixed
# method from the later version. The same bug affects >=3.10.0 <3.10.3, but installation of these
# versions is prohibited in pyproject.toml to avoid excessive CI matrix size.
if sys.version_info >= (3, 9, 0) and sys.version_info < (3, 9, 11):
    @property
    def _EntryPoint_extras(self):
        match = self.pattern.match(self.value)
        return re.findall(r'\w+', match.group('extras') or '')
    importlib.metadata.EntryPoint.extras = _EntryPoint_extras


# There are subtle differences between Python versions for both importlib.metadata (the built-in
# package) and importlib_metadata (the PyPI installable shim), so implement this function the way
# we need ourselves based on the Python 3.9 API. Once we drop Python 3.9 support this abomination
# can be removed.
def _entry_points(*, group, name=None):
    for distribution in importlib.metadata.distributions():
        if not hasattr(distribution, "name"):
            distribution.name = distribution.metadata["Name"]
        for entry_point in distribution.entry_points:
            if entry_point.group == group and (name is None or entry_point.name == name):
                if not hasattr(entry_point, "dist"):
                    entry_point.dist = distribution
                yield entry_point


def _requirements_for_optional_dependencies(distribution, depencencies):
    requirements = map(packaging.requirements.Requirement, distribution.requires)
    selected_requirements = set()
    for dependency in depencencies:
        for requirement in requirements:
            if requirement.marker and requirement.marker.evaluate({"extra": dependency}):
                requirement = packaging.requirements.Requirement(str(requirement))
                requirement.marker = None
                selected_requirements.add(requirement)
    return selected_requirements


def _unmet_requirements_in(requirements):
    unmet_requirements = set()
    for requirement in requirements:
        try:
            version = importlib.metadata.version(requirement.name)
        except importlib.metadata.PackageNotFoundError:
            unmet_requirements.add(requirement)
            continue
        if not requirement.specifier.contains(version):
            unmet_requirements.add(requirement)
            continue
        if requirement.extras:
            raise NotImplementedError("Optional dependency requirements within plugin dependencies "
                                      "are not supported yet")
    return unmet_requirements


def _install_command_for_requirements(requirements):
    requirement_args = " ".join(f"'{r}'" for r in requirements)
    if (pathlib.Path(sysconfig.get_path("data")) / "pipx_metadata.json").exists():
        return f"pipx inject glasgow {requirement_args}"
    if (pathlib.Path(sysconfig.get_path("data")) / "pyvenv.cfg").exists():
        return f"pip install {requirement_args}"
    else:
        return f"pip install --user {requirement_args}"


class PluginRequirementsUnmet(Exception):
    def __init__(self, metadata):
        self.metadata = metadata

    def __str__(self):
        return (f"{self.metadata.GROUP_NAME} plugin {self.metadata.handle!r} has unmet "
                f"requirements: {', '.join(str(r) for r in self.metadata.unmet_requirements)}")


class PluginLoadError(Exception):
    def __init__(self, metadata):
        self.metadata = metadata

    def __str__(self):
        return (f"{self.metadata.GROUP_NAME} plugin {self.metadata.handle!r} raised an exception "
                f"while being loaded")


class PluginMetadata:
    # Name of the 'entry point' group that contains plugin registration entries.
    #
    # E.g. if the name is `"glasgow.applet"` then the `pyproject.toml` section will be
    # `[project.entry-points."glasgow.applet"]`.
    GROUP_NAME = None

    _out_of_tree_warning_printed_for = set()

    @classmethod
    def _loadable(cls, entry_point):
        dist_name = entry_point.dist.name
        if dist_name == "glasgow":
            return True # in-tree
        if os.getenv("GLASGOW_OUT_OF_TREE_APPLETS") == "I-am-okay-with-breaking-changes":
            if dist_name not in cls._out_of_tree_warning_printed_for:
                logger.warn(f"loading out-of-tree plugin {dist_name!r}; plugin API is currently "
                            f"unstable and subject to change without warning")
                cls._out_of_tree_warning_printed_for.add(dist_name)
            return True
        return False

    @classmethod
    def get(cls, handle):
        entry_point, *_ = _entry_points(group=cls.GROUP_NAME, name=handle)
        return cls(entry_point)

    @classmethod
    def all(cls):
        return {ep.name: cls(ep) for ep in _entry_points(group=cls.GROUP_NAME) if cls._loadable(ep)}

    def __init__(self, entry_point):
        assert self._loadable(entry_point)

        # Python-side metadata (how to load it, etc.)
        self.module = entry_point.module
        self.cls_name = entry_point.attr
        self.dist_name = entry_point.dist.name
        self.requirements = _requirements_for_optional_dependencies(
            entry_point.dist, entry_point.extras)

        # Person-side metadata (how to display it, etc.)
        self.handle = entry_point.name
        if not self.unmet_requirements:
            try:
                self._cls = entry_point.load()
                self.synopsis = self._cls.help
                self.description = self._cls.description
            except Exception as exn:
                self._cls = None
                # traceback.format_exception_only can return multiple lines
                self.synopsis = (
                    f"/!\\ unavailable due to a load error: "
                    "".join(traceback.format_exception_only(exn)).splitlines()[0])
                # traceback.format_exception can return lines with internal newlines
                self.description = (
                    f"\nThis plugin is unavailable because attempting to load it has raised "
                    f"an exception. The exception is:\n\n    " +
                    "".join(traceback.format_exception(exn)).replace("\n", "\n    "))
        else:
            self._cls = None
            self.synopsis = (
                f"/!\\ unavailable due to unmet requirements: "
                f"{', '.join(str(r) for r in self.unmet_requirements)}")
            self.description = (
                f"\nThis plugin is unavailable because it requires additional packages to function "
                f"that are not installed. To install them, run:\n\n    " +
                _install_command_for_requirements(self.unmet_requirements) +
                f"\n")

    @property
    def unmet_requirements(self):
        return _unmet_requirements_in(self.requirements)

    @property
    def available(self):
        return not self.unmet_requirements

    @property
    def loadable(self):
        return self._cls is not None

    def load(self):
        if self.unmet_requirements:
            raise PluginRequirementsUnmet(self)
        if self._cls is None:
            raise PluginLoadError(self)
        return self._cls

    def __repr__(self):
        return (f"<{self.__class__.__name__} {self.module}:{self.cls_name}>")
