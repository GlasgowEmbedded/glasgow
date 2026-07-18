from amaranth import *


__all__ = ["IODelay"]


class IODelay(Elaboratable):
    """Very hacky replacement for proper I/O delay blocks for iCE40. Works surprisingly well."""

    def __init__(self, i, o, *, length=8): # approx. 5 ns by default
        self._i = i
        self._o = o
        self._length = length

    def elaborate(self, platform):
        m = Module()

        i = o = self._i
        for n in range(self._length):
            o = Signal()
            m.submodules[f"stage_{n}"] = Instance("SB_LUT4",
                a_keep=1,
                p_LUT_INIT=C(0b01, 16),
                i_I0=i,
                i_I1=C(0),
                i_I2=C(0),
                i_I3=C(0),
                o_O=o)
            i = o
        m.d.comb += self._o.eq(o)

        return m
