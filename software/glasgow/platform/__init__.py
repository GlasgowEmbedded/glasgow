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

    ("port_a", 0, Subsignal("io", Pins("45")), IOStandard("LVCMOS33")),
    ("port_a", 1, Subsignal("io", Pins("43")), IOStandard("LVCMOS33")),
    ("port_a", 2, Subsignal("io", Pins("42")), IOStandard("LVCMOS33")),
    ("port_a", 3, Subsignal("io", Pins("38")), IOStandard("LVCMOS33")),
    ("port_a", 4, Subsignal("io", Pins("37")), IOStandard("LVCMOS33")),
    ("port_a", 5, Subsignal("io", Pins("36")), IOStandard("LVCMOS33")),
    ("port_a", 6, Subsignal("io", Pins("35")), IOStandard("LVCMOS33")),
    ("port_a", 7, Subsignal("io", Pins("34")), IOStandard("LVCMOS33")),

    ("port_b", 0, Subsignal("io", Pins("32")), IOStandard("LVCMOS33")),
    ("port_b", 1, Subsignal("io", Pins("31")), IOStandard("LVCMOS33")),
    ("port_b", 2, Subsignal("io", Pins("28")), IOStandard("LVCMOS33")),
    ("port_b", 3, Subsignal("io", Pins("27")), IOStandard("LVCMOS33")),
    ("port_b", 4, Subsignal("io", Pins("26")), IOStandard("LVCMOS33")),
    ("port_b", 5, Subsignal("io", Pins("25")), IOStandard("LVCMOS33")),
    ("port_b", 6, Subsignal("io", Pins("23")), IOStandard("LVCMOS33")),
    ("port_b", 7, Subsignal("io", Pins("21")), IOStandard("LVCMOS33")),

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


class GlasgowPlatform(LatticePlatform):
    default_clk_name = "clk_if"
    default_clk_period = 1e9 / 30e6

    def __init__(self):
        LatticePlatform.__init__(self, "ice40-up5k-sg48", _io, _connectors,
                                 toolchain="icestorm")

    def create_programmer(self):
        return GlasgowProgrammer()
