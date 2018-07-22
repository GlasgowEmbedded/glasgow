from migen.build.generic_platform import *
from migen.build.lattice import LatticePlatform

from .programmer import GlasgowProgrammer


__all__ = ['Platform']


_io = [
    ("clk_fx", 0, Pins("44"), IOStandard("LVCMOS33")),
    ("clk_if", 0, Pins("20"), IOStandard("LVCMOS33")),

    ("fx2", 0,
        Subsignal("sloe", Pins("6")),
        Subsignal("slrd", Pins("47")),
        Subsignal("slwr", Pins("46")),
        Subsignal("pktend", Pins("2")),
        Subsignal("fifoadr", Pins("4 3")),
        Subsignal("flag", Pins("11 10 9 48")),
        Subsignal("fd", Pins("19 18 17 16 15 14 13 12")),
        IOStandard("LVCMOS33")
    ),

    ("io", 0, Pins("45 43 42 38 37 36 35 34"), IOStandard("LVCMOS33")),
    ("io", 1, Pins("32 31 28 27 26 25 23 21"), IOStandard("LVCMOS33")),

    ("i2c", 0,
        Subsignal("scl", Pins("39")),
        Subsignal("sda", Pins("40")),
        IOStandard("LVCMOS33")
    ),

    # open-drain
    ("sync", 0, Pins("41"), IOStandard("LVCMOS33")),
]

_connectors = [
]


class Platform(LatticePlatform):
    default_clk_name = "clk_if"
    default_clk_period = 1e9 / 30e6

    def __init__(self):
        LatticePlatform.__init__(self, "ice40-up5k-sg48", _io, _connectors,
                                 toolchain="icestorm")

    def create_programmer(self):
        return GlasgowProgrammer()
