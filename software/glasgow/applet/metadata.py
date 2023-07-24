import importlib.metadata
import packaging.requirements
import pathlib
import sysconfig
import textwrap


__all__ = ["GlasgowAppletUnavailable", "GlasgowAppletMetadata"]


def _requirements_for_optional_dependencies(distribution, depencencies):
    requirements = map(packaging.requirements.Requirement, distribution.requires)
    selected_requirements = set()
    for dependency in depencencies:
        for requirement in requirements:
            if requirement.marker and requirement.marker.evaluate({"extra": dependency}):
                requirement = packaging.requirements.Requirement(str(requirement))
                requirement.marker = ""
                selected_requirements.add(requirement)
    return selected_requirements


def _unsatisfied_requirements_in(requirements):
    unsatisfied_requirements = set()
    for requirement in requirements:
        try:
            version = importlib.metadata.version(requirement.name)
        except importlib.metadata.PackageNotFoundError:
            unsatisfied_requirements.add(requirement)
            continue
        if not requirement.specifier.contains(version):
            unsatisfied_requirements.add(requirement)
            continue
        if requirement.extras:
            raise NotImplementedError("Optional dependency requirements within optional applet "
                                      "dependencies are not supported yet")
    return unsatisfied_requirements


def _install_command_for_requirements(requirements):
    if (pathlib.Path(sysconfig.get_path("data")) / "pipx_metadata.json").exists():
        return f"pipx inject glasgow {' '.join(str(r) for r in requirements)}"
    if (pathlib.Path(sysconfig.get_path("data")) / "pyvenv.cfg").exists():
        return f"pip install {' '.join(str(r) for r in requirements)}"
    else:
        return f"pip install --user {' '.join(str(r) for r in requirements)}"


class GlasgowAppletUnavailable(Exception):
    def __init__(self, metadata):
        self.metadata = metadata

    def __str__(self):
        return (f"applet {self.metadata.handle} has unsatisfied requirements: "
                f"{', '.join(str(r) for r in self.metadata.unsatisfied_requirements)}")


class GlasgowAppletMetadata:
    @classmethod
    def get(cls, handle):
        return cls(importlib.metadata.entry_points(group="glasgow.applet", name=handle)[0])

    @classmethod
    def all(cls):
        return {ep.name: cls(ep) for ep in importlib.metadata.entry_points(group="glasgow.applet")}

    def __init__(self, entry_point):
        if entry_point.dist.name != "glasgow":
            raise Exception("Out-of-tree applets are not supported yet")

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
            self.synopsis = (f"/!\\ unavailable due to unsatisfied requirements: "
                             f"{', '.join(str(r) for r in self.unsatisfied_requirements)}")
            self.description = textwrap.dedent(f"""
            This applet is unavailable because it requires additional packages that are
            not installed. To install them, run:

                {_install_command_for_requirements(self.unsatisfied_requirements)}
            """)

    @property
    def unsatisfied_requirements(self):
        return _unsatisfied_requirements_in(self.requirements)

    @property
    def available(self):
        return not self.unsatisfied_requirements

    @property
    def applet_cls(self):
        if not self.available:
            raise GlasgowAppletUnavailable(self)
        return self._cls

    def __repr__(self):
        return (f"<{self.__class__.__name__} {self.module}:{self.cls_name}>")
