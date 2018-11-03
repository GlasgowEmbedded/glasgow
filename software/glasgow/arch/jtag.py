# Ref: IEEE 1149.1

from bitarray import bitarray

from ..support.bits import *


__all__ = [
    # DR
    "DR_IDCODE",
]


DR_IDCODE = Bitfield("DR_IDCODE", 4, [
    ("present",  1),
    ("mfg_id",  11),
    ("part_id", 16),
    ("version",  8),
])
