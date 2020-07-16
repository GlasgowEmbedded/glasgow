from nmigen.build import *

from .ice40 import *


__all__ = ["GlasgowPlatformRevC0"]


class GlasgowPlatformRevC0(GlasgowPlatformICE40):
    device      = "iCE40HX8K"
    package     = "BG121"
    default_clk = "clk_if"
    resources   = [
        Resource("clk_fx", 0, Pins("L5", dir="i"),
                 Clock(48e6), Attrs(GLOBAL="1", IO_STANDARD="SB_LVCMOS33")),
        Resource("clk_if", 0, Pins("K6", dir="i"),
                 Clock(48e6), Attrs(GLOBAL="1", IO_STANDARD="SB_LVCMOS33")),

        Resource("fx2", 0,
            Subsignal("sloe",    Pins("L3", dir="o")),
            Subsignal("slrd",    Pins("J5", dir="o")),
            Subsignal("slwr",    Pins("J4", dir="o")),
            Subsignal("pktend",  Pins("L1", dir="o")),
            Subsignal("fifoadr", Pins("K3 L2", dir="o")),
            Subsignal("flag",    Pins("L7 K5 L4 J3", dir="i")),
            Subsignal("fd",      Pins("H7 J7 J9 K10 L10 K9 L8 K7", dir="io")),
            Attrs(IO_STANDARD="SB_LVCMOS33")
        ),

        Resource("i2c", 0,
            Subsignal("scl", Pins("H9", dir="io")),
            Subsignal("sda", Pins("J8", dir="io")),
            Attrs(IO_STANDARD="SB_LVCMOS33")
        ),

        Resource("alert", 0, PinsN("K4", dir="oe"), Attrs(IO_STANDARD="SB_LVCMOS33")),

        Resource("led", 0, Pins("G9", dir="o"), Attrs(IO_STANDARD="SB_LVCMOS33")),
        Resource("led", 1, Pins("G8", dir="o"), Attrs(IO_STANDARD="SB_LVCMOS33")),
        Resource("led", 2, Pins("E9", dir="o"), Attrs(IO_STANDARD="SB_LVCMOS33")),
        Resource("led", 3, Pins("D9", dir="o"), Attrs(IO_STANDARD="SB_LVCMOS33")),
        Resource("led", 4, Pins("E8", dir="o"), Attrs(IO_STANDARD="SB_LVCMOS33")),

        Resource("port_a", 0,
                 Subsignal("io", Pins("A1"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("C7", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS33")),
        Resource("port_a", 1,
                 Subsignal("io", Pins("A2"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("C8", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS33")),
        Resource("port_a", 2,
                 Subsignal("io", Pins("B3"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("D7", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS33")),
        Resource("port_a", 3,
                 Subsignal("io", Pins("A3"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("A7", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS33")),
        Resource("port_a", 4,
                 Subsignal("io", Pins("B6"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("B8", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS33")),
        Resource("port_a", 5,
                 Subsignal("io", Pins("A4"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("A8", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS33")),
        Resource("port_a", 6,
                 Subsignal("io", Pins("B7"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("B9", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS33")),
        Resource("port_a", 7,
                 Subsignal("io", Pins("A5"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("A9", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS33")),

        Resource("port_b", 0,
                 Subsignal("io", Pins("B11"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("F9",  dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS33")),
        Resource("port_b", 1,
                 Subsignal("io", Pins("C11"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("G11", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS33")),
        Resource("port_b", 2,
                 Subsignal("io", Pins("D10"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("G10", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS33")),
        Resource("port_b", 3,
                 Subsignal("io", Pins("D11"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("H11", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS33")),
        Resource("port_b", 4,
                 Subsignal("io", Pins("E10"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("H10", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS33")),
        Resource("port_b", 5,
                 Subsignal("io", Pins("E11"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("J11", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS33")),
        Resource("port_b", 6,
                 Subsignal("io", Pins("F11"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("J10", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS33")),
        Resource("port_b", 7,
                 Subsignal("io", Pins("F10"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("K11", dir="o")),
                 Attrs(IO_STANDARD="SB_LVCMOS33")),

        Resource("port_s", 0,
                 Subsignal("io", Pins("A11")),
                 Attrs(IO_STANDARD="SB_LVCMOS33")),

        Resource("aux", 0, Pins("A10"), Attrs(IO_STANDARD="SB_LVCMOS33")),
        Resource("aux", 1, Pins("C9"),  Attrs(IO_STANDARD="SB_LVCMOS33")),

        # On revC, these balls are shared with B6 and B7, respectively.
        # Since the default pin state is a weak pullup, we need to tristate them explicitly.
        Resource("unused", 0, Pins("A6 B5", dir="oe"), Attrs(IO_STANDARD="SB_LVCMOS33")),
    ]
    connectors  = [
    ]


if __name__ == "__main__":
    from nmigen_boards.test.blinky import *
    GlasgowPlatformRevC0().build(Blinky(), do_program=True)
