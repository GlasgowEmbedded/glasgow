from collections import defaultdict, namedtuple


__all__ = ["devices", "devices_by_idcode", "devices_by_name"]


XC9500Device = namedtuple("XC9500Device", (
    "name", "idcode", "fbs",
))


devices = [
    XC9500Device("XC9536", idcode=(0x049, 0x9502), fbs=2),
    XC9500Device("XC9572", idcode=(0x049, 0x9504), fbs=4),
    XC9500Device("XC95108", idcode=(0x049, 0x9506), fbs=6),
    XC9500Device("XC95144", idcode=(0x049, 0x9508), fbs=8),
    XC9500Device("XC95216", idcode=(0x049, 0x9512), fbs=12),
    XC9500Device("XC95288", idcode=(0x049, 0x9516), fbs=16),
]

devices_by_idcode = defaultdict(lambda: None,
    ((device.idcode, device) for device in devices))

devices_by_name = defaultdict(lambda: None,
    ((device.name, device) for device in devices))
