from nmigen.build import *

from .ice40 import *


__all__ = ["GlasgowPlatformRevAB"]


class GlasgowPlatformRevAB(GlasgowPlatformICE40):
    device      = "iCE40UP5K"
    package     = "SG48"
    default_clk = "clk_if"
    resources   = [
        Resource("clk_fx", 0, Pins("44", dir="i"),
                 Clock(48e6), Attrs(GLOBAL="1", IO_STANDARD="SB_LVCMOS33")),
        Resource("clk_if", 0, Pins("20", dir="i"),
                 Clock(30e6), Attrs(GLOBAL="1", IO_STANDARD="SB_LVCMOS33")),

        Resource("fx2", 0,
            Subsignal("sloe",    Pins("6", dir="o")),
            Subsignal("slrd",    Pins("47", dir="o")),
            Subsignal("slwr",    Pins("46", dir="o")),
            Subsignal("pktend",  Pins("2", dir="o")),
            Subsignal("fifoadr", Pins("4 3", dir="o")),
            Subsignal("flag",    Pins("11 10 9 48", dir="i")),
            Subsignal("fd",      Pins("19 18 17 16 15 14 13 12", dir="io")),
            Attrs(IO_STANDARD="SB_LVCMOS33")
        ),

        Resource("i2c", 0,
            Subsignal("scl", Pins("39", dir="io")),
            Subsignal("sda", Pins("40", dir="io")),
            Attrs(IO_STANDARD="SB_LVCMOS33")
        ),

        Resource("port_a", 0, Subsignal("io", Pins("45"))),
        Resource("port_a", 1, Subsignal("io", Pins("43"))),
        Resource("port_a", 2, Subsignal("io", Pins("42"))),
        Resource("port_a", 3, Subsignal("io", Pins("38"))),
        Resource("port_a", 4, Subsignal("io", Pins("37"))),
        Resource("port_a", 5, Subsignal("io", Pins("36"))),
        Resource("port_a", 6, Subsignal("io", Pins("35"))),
        Resource("port_a", 7, Subsignal("io", Pins("34"))),

        Resource("port_b", 0, Subsignal("io", Pins("32"))),
        Resource("port_b", 1, Subsignal("io", Pins("31"))),
        Resource("port_b", 2, Subsignal("io", Pins("28"))),
        Resource("port_b", 3, Subsignal("io", Pins("27"))),
        Resource("port_b", 4, Subsignal("io", Pins("26"))),
        Resource("port_b", 5, Subsignal("io", Pins("25"))),
        Resource("port_b", 6, Subsignal("io", Pins("23"))),
        Resource("port_b", 7, Subsignal("io", Pins("21"))),

        # On revA/B, this pin is open-drain only.
        Resource("port_s", 0, Pins("41")),
    ]
    connectors  = [
    ]
