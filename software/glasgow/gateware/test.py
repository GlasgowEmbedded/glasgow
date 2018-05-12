from migen import *

from .target import GlasgowBase


__all__ = ["TestToggleIO", "TestMirrorI2C", "TestGenSeq"]


class TestToggleIO(GlasgowBase):
    def __init__(self):
        super().__init__()

        cnt = Signal(15)
        out = Signal()
        self.sync += [
            cnt.eq(cnt + 1),
            If(cnt == 0,
                out.eq(~out))
        ]

        sync = self.platform.request("sync")
        ioa = self.platform.request("io")
        iob = self.platform.request("io")
        self.comb += [
            sync.eq(out),
            ioa.eq(Replicate(out, 8)),
            iob.eq(Replicate(out, 8)),
        ]


class TestMirrorI2C(GlasgowBase):
    def __init__(self):
        super().__init__()

        i2c = self.platform.request("i2c")
        ioa = self.platform.request("io")
        self.comb += ioa[0:2].eq(Cat(i2c.scl, i2c.sda))


class TestGenSeq(GlasgowBase):
    def __init__(self):
        super().__init__(out_count=1, in_count=2)

        out0 = self.arbiter.get_out(0)
        in0 = self.arbiter.get_in(0)
        in1 = self.arbiter.get_in(1)

        stb = Signal()
        re  = Signal()
        self.sync += [
            out0.re.eq(out0.readable),
            re.eq(out0.re),
            stb.eq(out0.re & ~re)
        ]

        act = Signal()
        nam = Signal()
        cnt = Signal(8)
        lim = Signal(8)
        self.sync += [
            If(stb,
                act.eq(1),
                nam.eq(1),
                lim.eq(out0.dout),
                cnt.eq(0),
            ),
            If(act,
                nam.eq(~nam),
                in0.we.eq(1),
                in1.we.eq(1),
                If(nam,
                    in0.din.eq(b'A'[0]),
                    in1.din.eq(b'B'[0]),
                ).Else(
                    in0.din.eq(cnt),
                    in1.din.eq(cnt),
                    cnt.eq(cnt + 1),
                    If(cnt + 1 == lim,
                        act.eq(0)
                    )
                ),
            ).Else(
                in0.we.eq(0),
                in1.we.eq(0),
            ),
        ]
