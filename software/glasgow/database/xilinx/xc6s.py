from collections import defaultdict, namedtuple


__all__ = ["devices", "devices_by_idcode", "devices_by_name"]


XC6SDevice = namedtuple("XC6SDevice", ("name", "idcode"))


devices = [
    XC6SDevice("XC6SLX4",    idcode=(0x049, 0x4000)),
    XC6SDevice("XC6SLX9",    idcode=(0x049, 0x4001)),
    XC6SDevice("XC6SLX16",   idcode=(0x049, 0x4002)),
    XC6SDevice("XC6SLX25",   idcode=(0x049, 0x4004)),
    XC6SDevice("XC6SLX25T",  idcode=(0x049, 0x4024)),
    XC6SDevice("XC6SLX45",   idcode=(0x049, 0x4008)),
    XC6SDevice("XC6SLX45T",  idcode=(0x049, 0x4028)),
    XC6SDevice("XC6SLX75",   idcode=(0x049, 0x400E)),
    XC6SDevice("XC6SLX75T",  idcode=(0x049, 0x402E)),
    XC6SDevice("XC6SLX100",  idcode=(0x049, 0x4011)),
    XC6SDevice("XC6SLX100T", idcode=(0x049, 0x4031)),
    XC6SDevice("XC6SLX150",  idcode=(0x049, 0x401D)),
    XC6SDevice("XC6SLX150T", idcode=(0x049, 0x403D)),
]

devices_by_idcode = defaultdict(lambda: None,
    ((device.idcode, device) for device in devices))

devices_by_name = defaultdict(lambda: None,
    ((device.name, device) for device in devices))
