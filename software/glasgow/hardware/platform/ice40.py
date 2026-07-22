from amaranth import *
from amaranth.vendor import LatticeICE40Platform

from . import GlasgowPlatform


__all__ = ["GlasgowICE40Platform"]


class GlasgowICE40Platform(GlasgowPlatform, LatticeICE40Platform):
    def bitstream_filename(self, design_name):
        return f"{design_name}.bin"
