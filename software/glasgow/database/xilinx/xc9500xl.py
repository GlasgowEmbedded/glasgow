from collections import defaultdict, namedtuple


__all__ = ["devices", "devices_by_idcode", "devices_by_name"]


XC9500XLDevice = namedtuple("XC9500XLDevice", (
    "name", "idcode", "fbs", "kind",
))


devices = [
    XC9500XLDevice("XC9536XL", idcode=(0x049, 0x9602), fbs=2, kind="xl"),
    XC9500XLDevice("XC9572XL", idcode=(0x049, 0x9604), fbs=4, kind="xl"),
    XC9500XLDevice("XC95144XL", idcode=(0x049, 0x9608), fbs=8, kind="xl"),
    XC9500XLDevice("XC95288XL", idcode=(0x049, 0x9616), fbs=16, kind="xl"),
    XC9500XLDevice("XC9536XV", idcode=(0x049, 0x9702), fbs=2, kind="xv"),
    XC9500XLDevice("XC9572XV", idcode=(0x049, 0x9704), fbs=4, kind="xv"),
    XC9500XLDevice("XC95144XV", idcode=(0x049, 0x9708), fbs=8, kind="xv"),
    XC9500XLDevice("XC95288XV", idcode=(0x049, 0x9716), fbs=16, kind="xv"),
]

devices_by_idcode = defaultdict(lambda: None,
    ((device.idcode, device) for device in devices))

devices_by_name = defaultdict(lambda: None,
    ((device.name, device) for device in devices))
