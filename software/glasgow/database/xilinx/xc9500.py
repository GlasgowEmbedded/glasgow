from collections import defaultdict, namedtuple


__all__ = ["devices"]


XC9500Device = namedtuple("XC9500Device", (
    "name", "bitstream_words", "usercode_low", "usercode_high"
))


devices = defaultdict(lambda: None, {
    (0x049, 0x9604): XC9500Device(name="XC9572XL", bitstream_words=1620,
                                  usercode_low=90, usercode_high=105),
})
