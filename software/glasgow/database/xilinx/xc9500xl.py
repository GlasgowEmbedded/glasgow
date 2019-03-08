from collections import defaultdict, namedtuple


__all__ = ["devices", "devices_by_idcode", "devices_by_name"]


XC9500XLDevice = namedtuple("XC9500XLDevice", (
    "name", "idcode", "bitstream_words", "word_width", "usercode_low", "usercode_high"
))


devices = [
    XC9500XLDevice("XC9536XL",
        idcode=(0x049, 0x9602),
        bitstream_words=1620,
        word_width=16,
        usercode_low=90, usercode_high=105),
    XC9500XLDevice("XC9572XL",
        idcode=(0x049, 0x9604),
        bitstream_words=1620,
        word_width=32,
        usercode_low=90, usercode_high=105),
]

devices_by_idcode = defaultdict(lambda: None,
    ((device.idcode, device) for device in devices))

devices_by_name = defaultdict(lambda: None,
    ((device.name, device) for device in devices))
