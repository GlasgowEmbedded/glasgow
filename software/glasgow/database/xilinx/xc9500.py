from collections import defaultdict, namedtuple


__all__ = ["devices", "devices_by_idcode"]


XC9500Device = namedtuple("XC9500Device", (
    "name", "idcode", "bitstream_words", "usercode_low", "usercode_high"
))


devices = [
    XC9500Device("XC9572XL",
        idcode=(0x049, 0x9604),
        bitstream_words=1620,
        usercode_low=90, usercode_high=105),
]

devices_by_idcode = defaultdict(lambda: None,
    ((device.idcode, device) for device in devices))
