from amaranth.build import *

from .ecp5 import *


__all__ = ["GlasgowRevD0Platform"]


class _GlasgowRevDPlatform(GlasgowECP5Platform):
    device      = "LFE5U-25F"
    package     = "BG256"
    speed       = 8
    default_clk = "clk_if"
    resources   = [
        Resource("clk_fx", 0, Pins("C8", dir="i"),
                 Clock(48e6), Attrs(IO_TYPE="LVCMOS33")),
        Resource("clk_if", 0, Pins("E8", dir="i"),
                 Clock(48e6), Attrs(IO_TYPE="LVCMOS33")),

        Resource("fx2", 0,
            Subsignal("sloe",    Pins("B5", dir="o")),
            Subsignal("slrd",    Pins("E9", dir="o")),
            Subsignal("slwr",    Pins("D10", dir="o")),
            Subsignal("pktend",  Pins("E11", dir="o")),
            Subsignal("fifoadr", Pins("D9 D8", dir="o")),
            Subsignal("flag",    Pins("B10 E10 A9 E4", dir="i")),
            Subsignal("fd",      Pins("T8 T7 M7 N7 P7 R7 R6 T6", dir="io")),
            Attrs(IO_TYPE="LVCMOS33")
        ),

        Resource("i2c", 0,
            Subsignal("scl", Pins("A12", dir="io")),
            Subsignal("sda", Pins("D11", dir="io")),
            Attrs(IO_TYPE="LVCMOS33")
        ),
        Resource("alert", 0, PinsN("B4", dir="oe"), Attrs(IO_TYPE="LVCMOS33")),

        Resource("led", 0, Pins("D13", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led", 1, Pins("E13", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led", 2, Pins("A13", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led", 3, Pins("A14", dir="o"), Attrs(IO_TYPE="LVCMOS33")),
        Resource("led", 4, Pins("B14", dir="o"), Attrs(IO_TYPE="LVCMOS33")),

        Resource("octospi", 0,
            Subsignal("cs",  PinsN("R16", dir="o"), Attrs(PULLUP=1)),
            Subsignal("clk", Pins( "P16", dir="o")),
            Subsignal("dqs", Pins( "N16", dir="io")),
            Subsignal("dq",  Pins( "L15 K13 M15 L16 M16 L13 L12 K12", dir="io")),
            Attrs(IO_TYPE="LVCMOS33")
        ),
        Resource("octospi", 1,
            Subsignal("cs",  PinsN("P11", dir="o"), Attrs(PULLUP=1)),
            Subsignal("clk", Pins( "M11", dir="o")),
            Subsignal("dqs", Pins( "R12", dir="io")),
            Subsignal("dq",  Pins( "R14 P14 T15 R15 T14 T13 P13 N13", dir="io")),
            Attrs(IO_TYPE="LVCMOS33")
        ),

        Resource("afe_mcu", 0,
            # When using the AFE from the FPGA, the MCU must be held in reset to avoid contention.
            Subsignal("reset", PinsN("D5",  dir="o"), Attrs(PULLUP=1)),
            Attrs(IO_TYPE="LVCMOS33")
        ),
        Resource("afe_adc", 0,
            Subsignal("reset", PinsN("A15", dir="o"), Attrs(PULLUP=1)),
            Subsignal("cs",    PinsN("C9",  dir="o"), Attrs(PULLUP=1)),
            Subsignal("clk",   Pins( "A8",  dir="o")),
            Subsignal("copi",  Pins( "A3",  dir="o")),
            Subsignal("cipo",  Pins( "B3",  dir="i")),
            Subsignal("int",   PinsN("C4",  dir="i")),
            Subsignal("sync",  Pins( "D4",  dir="o")),
            Subsignal("drdy",  Pins( "A2",  dir="i")),
            Attrs(IO_TYPE="LVCMOS33")
        ),

        Resource("port_a", 0,
                 Subsignal("io", Pins("B2"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("B1", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_a", 1,
                 Subsignal("io", Pins("D3"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("C3", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_a", 2,
                 Subsignal("io", Pins("C2"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("C1", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_a", 3,
                 Subsignal("io", Pins("F3"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("E3", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_a", 4,
                 Subsignal("io", Pins("E2"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("D1", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_a", 5,
                 Subsignal("io", Pins("F5"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("F4", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_a", 6,
                 Subsignal("io", Pins("G5"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("G4", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_a", 7,
                 Subsignal("io", Pins("E1"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("F2", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),

        Resource("port_b", 0,
                 Subsignal("io", Pins("G2"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("F1",  dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_b", 1,
                 Subsignal("io", Pins("H3"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("G3", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_b", 2,
                 Subsignal("io", Pins("H4"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("H5", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_b", 3,
                 Subsignal("io", Pins("J5"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("J4", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_b", 4,
                 Subsignal("io", Pins("H2"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("G1", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_b", 5,
                 Subsignal("io", Pins("K3"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("J3", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_b", 6,
                 Subsignal("io", Pins("J2"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("J1", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_b", 7,
                 Subsignal("io", Pins("K2"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("K1", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),

        Resource("port_c", 0,
                 Subsignal("io", Pins("B16"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("B15",  dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_c", 1,
                 Subsignal("io", Pins("C14"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("D14", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_c", 2,
                 Subsignal("io", Pins("C16"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("C15", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_c", 3,
                 Subsignal("io", Pins("E14"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("F14", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_c", 4,
                 Subsignal("io", Pins("D16"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("E15", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_c", 5,
                 Subsignal("io", Pins("F13"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("F12", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_c", 6,
                 Subsignal("io", Pins("G12"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("G13", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_c", 7,
                 Subsignal("io", Pins("F15"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("E16", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),

        Resource("port_d", 0,
                 Subsignal("io", Pins("F16"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("G15",  dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_d", 1,
                 Subsignal("io", Pins("G14"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("H14", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_d", 2,
                 Subsignal("io", Pins("H12"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("H13", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_d", 3,
                 Subsignal("io", Pins("J13"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("J12", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_d", 4,
                 Subsignal("io", Pins("G16"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("H15", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_d", 5,
                 Subsignal("io", Pins("J14"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("K14", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_d", 6,
                 Subsignal("io", Pins("J16"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("J15", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
        Resource("port_d", 7,
                 Subsignal("io", Pins("K16"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("K15", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),

        Resource("port_s", 0,
                 Subsignal("io", Pins("B13"), Attrs(PULLUP=1)),
                 Subsignal("oe", Pins("C13", dir="o")),
                 Attrs(IO_TYPE="LVCMOS33")),
    ]
    connectors  = [
        Connector("lvds", 0,
        # 1  2  3  4  5  6  7  8  9  10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30
        " -  -  -  -  A5 -  L2 L1 -  K5 K4 -  P2 N1 -  P3 N4 -  R1 P1 -  R3 P4 -  T4 R5 -  N6 M6 - "
        # 31 32 33 34 35 36 37 38 39 40 41 42 43 44 45 46 47 48 49 50 51 52 53 54 55 56 57 58 59 60
        " -  -  -  -  -  L5 L4 -  M3 L3 -  M2 M1 -  N3 M4 -  N5 M5 -  P5 P6 -  T2 R2 -  T3 R4 -  - "
        ),
    ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._init_glasgow_pins(
            ("A", "port_a", range(8)),
            ("B", "port_b", range(8)),
            ("C", "port_c", range(8)),
            ("D", "port_d", range(8)),
            ("S", "port_s", range(1)),
        )


class GlasgowRevD0Platform(_GlasgowRevDPlatform):
    pass
