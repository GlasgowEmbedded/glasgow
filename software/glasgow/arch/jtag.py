# Ref: IEEE Std 1149.1-2001
# Accession: G00018

from glasgow.support.bitstruct import bitstruct


__all__ = [
    # DR
    "DR_IDCODE",
]


DR_IDCODE = bitstruct("DR_IDCODE", 32, [
    ("present",  1),
    ("mfg_id",  11),
    ("part_id", 16),
    ("version",  4),
])
