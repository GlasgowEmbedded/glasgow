import logging
import asyncio
from amaranth import *
from amaranth.build.res import ResourceError

from ... import *

class Counter(Elaboratable):
    def __init__(self, bits=8):
        self.bits = bits
        self.value = Signal(bits, reset=0)

        self.ports = (
            self.value
        )

    def elaborate(self, platform):
        m = Module()
        m.d.sync += self.value.eq(self.value + 1)
        return m


class PWM(Elaboratable):
    def __init__(self, counter, bits=8, duty=1):
        self.bits = bits
        self.counter = counter;
        self.idut = Signal(bits, reset=duty)
        self.duty = Signal(bits, reset=duty)
        self.out = Signal()

        self.ports = (
            self.duty,
            self.out
        )

    def elaborate(self, platform):
        m = Module()
        counter = self.counter.value[:self.bits]

        with m.If(counter == 0):
            m.d.sync += self.idut.eq(self.duty)
            with m.If(self.idut):
                m.d.sync += self.out.eq(1)
        with m.If(counter == self.idut):
            m.d.sync += self.out.eq(0)

        return m

class VisualPWM(Elaboratable):
    def __init__(self):
        self.ind = Signal(8)
        self.outd = Signal(16)
        self.ports = (
            self.ind,
            self.outd
        )

    def elaborate(self, platform):
        m = Module()
        lut = Array([
        1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 2, 3,
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


class FlyTheFlagSubtarget(Elaboratable):
    def __init__(self, applet, target):
        try:
            self.leds = [target.platform.request("led", n) for n in range(5)]
        except ResourceError:
            self.leds = []


    def elaborate(self, platform):
        m = Module()
        m.submodules.counter = counter = Counter(27)
        for n in range(5):
            m.submodules[f"pwm{n}"] = pwm = PWM(counter,16)
            m.submodules[f"vpwm{n}"] = vpwm = VisualPWM()
            daa = Signal(8)
            m.d.sync += daa.eq((counter.value >> 19) + (51 * n))
            with m.If(daa > 127):
                m.d.sync += vpwm.ind.eq((128 | Const(127,8) - daa[:7]))
            with m.Else():
                m.d.sync += vpwm.ind.eq(128 | daa)
            m.d.sync += pwm.duty.eq(vpwm.outd)
            m.d.comb += self.leds[n].o.eq(pwm.out)

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
