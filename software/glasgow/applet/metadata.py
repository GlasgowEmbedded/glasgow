import importlib.metadata


__all__ = ["GlasgowAppletMetadata"]


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
        # Person-side metadata (how to display it, etc.)
        self._cls = entry_point.load()
        self.handle = entry_point.name
        self.synopsis = self._cls.help
        self.description = self._cls.description

    @property
    def applet_cls(self):
        return self._cls

    def __repr__(self):
        return (f"<{self.__class__.__name__} "
                f"{self.module}:{self.cls_name}>")
