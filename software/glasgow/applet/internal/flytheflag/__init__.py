import logging
import asyncio
from amaranth import *
from amaranth.build.res import ResourceError
from amaranth.lib import wiring
from amaranth.lib.wiring import In, Out

from ... import *

class Counter(wiring.Component):
    def __init__(self, bits=8):
        super().__init__({
            "value": Out(bits),
            "carry": Out(1)
        })

    def elaborate(self, platform):
        m = Module()
        vinc = self.value + 1
        m.d.sync += self.carry.eq(vinc >> len(self.value))
        m.d.sync += self.value.eq(vinc)
        return m

class BufferedPWM(wiring.Component):
    def __init__(self, counter, bits=None):
        if bits is None:
            bits = len(counter.value)

        super().__init__({
            "duty": In(bits),
            "out": Out(1)
        })

        self.counter = counter;
        self.bits = bits
        self.active_duty = Signal(bits)

    def elaborate(self, platform):
        m = Module()
        cnt = self.counter.value[:self.bits]

        with m.If(cnt == self.active_duty):
            m.d.sync += self.out.eq(0)

        with m.If(cnt == 0):
            adut = self.duty
            m.d.sync += self.active_duty.eq(adut)
            m.d.sync += self.out.eq(0)
            with m.If(adut):
                m.d.sync += self.out.eq(1)

        return m

class VisualLUT(wiring.Component):
    ind: In(8)
    outd: Out(16)

    def elaborate(self, platform):
        m = Module()
        # This is pwmtable_16 from
        # https://www.mikrocontroller.net/articles/LED-Fading
        # It is not a very good match for the glasgow LEDs :/
        # There's a longish "dead zone" in the low values now,
        # where atleast I can't see a dang thing.
        # Maybe 48Mhz is just so fast that the time it takes
        # to overcome the LED capacitance by the FPGA pin driver on turn-on
        # makes the effective times even shorter ? *shrug*.
        # (Also: Yep maybe implement this with a memory, lol.)
        lut = Array([
        0, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3,
        3, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 5, 5, 5, 5, 5, 6, 6, 6, 6, 7,
        7, 7, 8, 8, 8, 9, 9, 10, 10, 10, 11, 11, 12, 12, 13, 13, 14, 15,
        15, 16, 17, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29,
        31, 32, 33, 35, 36, 38, 40, 41, 43, 45, 47, 49, 52, 54, 56, 59,
        61, 64, 67, 70, 73, 76, 79, 83, 87, 91, 95, 99, 103, 108, 112,
        117, 123, 128, 134, 140, 146, 152, 159, 166, 173, 181, 189, 197,
        206, 215, 225, 235, 245, 256, 267, 279, 292, 304, 318, 332, 347,
        362, 378, 395, 412, 431, 450, 470, 490, 512, 535, 558, 583, 609,
        636, 664, 693, 724, 756, 790, 825, 861, 899, 939, 981, 1024, 1069,
        1117, 1166, 1218, 1272, 1328, 1387, 1448, 1512, 1579, 1649, 1722,
        1798, 1878, 1961, 2048, 2139, 2233, 2332, 2435, 2543, 2656, 2773,
        2896, 3025, 3158, 3298, 3444, 3597, 3756, 3922, 4096, 4277, 4467,
        4664, 4871, 5087, 5312, 5547, 5793, 6049, 6317, 6596, 6889, 7194,
        7512, 7845, 8192, 8555, 8933, 9329, 9742, 10173, 10624, 11094,
        11585, 12098, 12634, 13193, 13777, 14387, 15024, 15689, 16384,
        17109, 17867, 18658, 19484, 20346, 21247, 22188, 23170, 24196,
        25267, 26386, 27554, 28774, 30048, 31378, 32768, 34218, 35733,
        37315, 38967, 40693, 42494, 44376, 46340, 48392, 50534, 52772,
        55108, 57548, 60096, 62757, 65535
        ])
        m.d.sync += self.outd.eq(lut[self.ind[:8]])
        return m

class SineLUT(wiring.Component):
    def __init__(self, amplirange, inbits):
        super().__init__({
            "ind": In(inbits),
            "outd": Out(amplirange)
        })
        self.inbits = inbits
        self.amplirange = amplirange

    def elaborate(self, platform):
        m = Module()
        a = []
        minv = min(self.amplirange)
        lenv = len(self.amplirange)
        r = range(2**self.inbits)
        for n in r:
            from math import sin, pi
            # 0 to pi is positive
            # pi to 2*pi is negative
            angle = n/len(r) * (pi*2)
            v = (sin(angle) + 1.0) / 2 # -1 to 1 -> 0 to 1
            n = len(self.amplirange)
            xv = int(v * n) + minv
            a.append(xv)

        lut = Array(a)
        m.d.sync += self.outd.eq(lut[self.ind])
        return m


class FlagSequencer(Elaboratable):
    def __init__(self, counter, pwmlist):
        self.lightpos = Signal(signed(8))
        self.counter = counter
        self.pwmlist = pwmlist
        self.sequence = Signal(4) # 5*2 + 2, = 12 states
        # smaller is faster
        self.speed = 12
        self.animcnt = Signal(range(self.speed+1))

        self.sinbits = 8
        self.sinpos = Signal(self.sinbits)
        # true max spacing*2, but we just get close to the edge
        self.posmax = 76
        self.posmin = -self.posmax;


    def elaborate(self, platform):
        m = Module()
        m.submodules.visual = visual = VisualLUT()
        m.submodules.sinelut = sinelut = SineLUT(range(self.posmin,self.posmax+1),self.sinbits)
        with m.If(self.counter.carry):
            m.d.sync += self.animcnt.eq(self.animcnt - 1)
            with m.If(self.animcnt == 0):
                m.d.sync += self.animcnt.eq(self.speed)
                m.d.sync += self.sequence.eq(0)
                m.d.sync += self.sinpos.eq(self.sinpos + 1)
                m.d.sync += sinelut.ind.eq(self.sinpos)

        v = 0
        with m.Switch(self.sequence):
            with m.Case(0):
                m.d.sync += self.lightpos.eq(sinelut.outd)
                m.d.sync += self.sequence.eq(1)

            for pwm in self.pwmlist:
                with m.Case(v*2+1):
                    # Spacing has an effect on the max "distance",
                    # thus how dim the dim parts get.
                    # (and also needs to match up with posmax above)
                    spacing = 40
                    pos = Const(v*spacing - (2*spacing))
                    dist = Mux((self.lightpos - pos) >= 0, self.lightpos - pos, pos - self.lightpos)
                    bright = 255 - dist
                    m.d.sync += visual.ind.eq(bright)
                    m.d.sync += self.sequence.eq((v*2)+2)
                with m.Case(v*2+2):
                    m.d.sync += pwm.duty.eq(visual.outd)
                    m.d.sync += self.sequence.eq((v*2)+3)
                v += 1

            with m.Default():
                pass

        return m


class FlyTheFlagSubtarget(Elaboratable):
    def __init__(self, applet, target):
        try:
            # I do not know if my code has an off-by-one, or if there's something funny about the definitions...
            xleds = [target.platform.request("led", n) for n in range(5)]
            self.leds = [xleds[-1]] + xleds[:4]
        except ResourceError:
            self.leds = []


    def elaborate(self, platform):
        m = Module()
        m.submodules.counter = counter = Counter(16)
        pwmlist = []
        for n in range(5):
            m.submodules[f"pwm{n}"] = pwm = BufferedPWM(counter,16)
            pwmlist.append(pwm)
            m.d.comb += self.leds[n].o.eq(pwm.out)
        m.submodules.sequencer = FlagSequencer(counter, pwmlist)
        return m


class FlyTheFlagApplet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "A PWM demo on the user LEDs"
    preview = True
    description = """
    An FPGA PWM demonstration
    """

    __pins = ()

    def build(self, target, args):
        target.add_submodule(FlyTheFlagSubtarget(applet=self, target=target))

        self.mux_interface_1 = iface_1 = target.multiplexer.claim_interface(self, None)
        self.mux_interface_2 = iface_2 = target.multiplexer.claim_interface(self, None)

        in_fifo_1, out_fifo_1 = iface_1.get_inout_fifo()
        in_fifo_2, out_fifo_2 = iface_2.get_inout_fifo()
        m = Module()
        m.d.comb += [
            in_fifo_1.w_data.eq(out_fifo_1.r_data),
            in_fifo_1.w_en.eq(out_fifo_1.r_rdy),
            out_fifo_1.r_en.eq(in_fifo_1.w_rdy),
            in_fifo_2.w_data.eq(out_fifo_2.r_data),
            in_fifo_2.w_en.eq(out_fifo_2.r_rdy),
            out_fifo_2.r_en.eq(in_fifo_2.w_rdy),
        ]
        target.add_submodule(m)

    async def run(self, device, args):
        return None

    @classmethod
    def add_interact_arguments(cls, parser):
        pass

    async def interact(self, device, args, iface):
        pass

# -------------------------------------------------------------------------------------------------

class FlyTheFlagAppletTestCase(GlasgowAppletTestCase, applet=FlyTheFlagApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
