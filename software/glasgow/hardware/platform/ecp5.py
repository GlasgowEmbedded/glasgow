from amaranth import *
from amaranth.vendor import LatticeECP5Platform

from . import GlasgowPlatform


__all__ = ["GlasgowECP5Platform"]


class GlasgowECP5Platform(GlasgowPlatform, LatticeECP5Platform):
    def bitstream_filename(self, design_name):
        return f"{design_name}.bit"

    def get_pll(self, pll):
        raise NotImplementedError("get_pll() not implemented for ECP5")
