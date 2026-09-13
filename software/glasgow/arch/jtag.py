# Ref: IEEE Std 1149.1-2001
# Accession: G00018

from glasgow.support.bitstruct import bitstruct


__all__ = [
    # DR
    "DR_IDCODE",
]


class DR_IDCODE(bitstruct, width=32):
    present: int = 1
    mfg_id: int  = 11
    part_id: int = 16
    version: int = 4
