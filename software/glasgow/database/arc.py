from collections import defaultdict, namedtuple


__all__ = ["devices"]


ARCDevice = namedtuple("ARCDevice", ("name",))


devices = defaultdict(lambda: None, {
    (0x258, 0x0002): ARCDevice(name="ARC6xx"),
})
