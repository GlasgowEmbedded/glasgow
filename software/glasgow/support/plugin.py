import importlib.metadata
import packaging.requirements
import pathlib
import sysconfig
import textwrap


__all__ = ["PluginRequirementsUnmet", "PluginMetadata"]


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
    if (pathlib.Path(sysconfig.get_path("data")) / "pipx_metadata.json").exists():
        return f"pipx inject glasgow {' '.join(str(r) for r in requirements)}"
    if (pathlib.Path(sysconfig.get_path("data")) / "pyvenv.cfg").exists():
        return f"pip install {' '.join(str(r) for r in requirements)}"
    else:
        return f"pip install --user {' '.join(str(r) for r in requirements)}"


class PluginRequirementsUnmet(Exception):
    def __init__(self, metadata):
        self.metadata = metadata

    def __str__(self):
        return (f"plugin {self.metadata.handle} has unmet requirements: "
                f"{', '.join(str(r) for r in self.metadata.unmet_requirements)}")


class PluginMetadata:
    # Name of the 'entry point' group that contains plugin registration entries.
    #
    # E.g. if the name is `"glasgow.applet"` then the `pyproject.toml` section will be
    # `[project.entry-points."glasgow.applet"]`.
    GROUP_NAME = None

    @classmethod
    def get(cls, handle):
        entry_point, *_ = _entry_points(group=cls.GROUP_NAME, name=handle)
        return cls(entry_point)

    @classmethod
    def all(cls):
        return {ep.name: cls(ep) for ep in _entry_points(group=cls.GROUP_NAME)}

    def __init__(self, entry_point):
        if entry_point.dist.name != "glasgow":
            raise Exception("Out-of-tree plugins are not supported yet")

        # Python-side metadata (how to load it, etc.)
        self.module = entry_point.module
        self.cls_name = entry_point.attr
        self.dist_name = entry_point.dist.name
        self.requirements = _requirements_for_optional_dependencies(
            entry_point.dist, entry_point.extras)

        # Person-side metadata (how to display it, etc.)
        self.handle = entry_point.name
        if self.available:
            self._cls = entry_point.load()
            self.synopsis = self._cls.help
            self.description = self._cls.description
        else:
            self.synopsis = (f"/!\\ unavailable due to unmet requirements: "
                             f"{', '.join(str(r) for r in self.unmet_requirements)}")
            self.description = textwrap.dedent(f"""
            This plugin is unavailable because it requires additional packages that are
            not installed. To install them, run:

                {_install_command_for_requirements(self.unmet_requirements)}
            """)

    @property
    def unmet_requirements(self):
        return _unmet_requirements_in(self.requirements)

    @property
    def available(self):
        return not self.unmet_requirements

    def load(self):
        if not self.available:
            raise PluginRequirementsUnmet(self)
        return self._cls

    def __repr__(self):
        return (f"<{self.__class__.__name__} {self.module}:{self.cls_name}>")
