from itertools import chain
from typing import List, Tuple
from amaranth import *

class SignalCompressor(Elaboratable):
    """The SignalCompressor converts information about value changes into an efficient compressed 
    format. It outputs a 16bit stream that is encoded in one of three ways:

    0b0: plain, no compression [15 bit value dump]
    0b10: constant 0 for the following n [14 bit] cycles
    0b11: constant 1 for the following n [14 bit] cycles
    """
    def __init__(self, signal):
        self.signal = signal

        self.valid = Signal()
        self.value = Signal(16)

    def elaborate(self, platform):
        m = Module()
        
        last = Signal()
        m.d.sync += last.eq(self.signal)
        change = Signal()
        m.d.comb += change.eq(self.signal ^ last)


        counter = Signal(14)
        m.d.sync += counter.eq(counter + 1)

        buffer = Signal(15)
        m.d.sync += buffer.eq((buffer << 1) | self.signal)

        plain_mode = Signal()

        with m.If(change):
            with m.If(counter < 15):
                m.d.sync += plain_mode.eq(1)
            with m.Elif(~plain_mode):
                m.d.comb += self.valid.eq(1)
                m.d.comb += self.value.eq(Cat(1, last, counter))
                m.d.sync += counter.eq(0)
                m.d.sync += plain_mode.eq(0)

        with m.If(counter == 2**len(counter) - 1):
            m.d.comb += self.valid.eq(1)
            m.d.comb += self.value.eq(Cat(1, last, counter))
            m.d.sync += counter.eq(0)
            m.d.sync += plain_mode.eq(0)
        
        with m.If(plain_mode & (counter == 14)):
            m.d.comb += self.valid.eq(1)
            m.d.comb += self.value.eq(Cat(0, buffer))
            m.d.sync += counter.eq(0)
            m.d.sync += plain_mode.eq(0)

        return m

    @staticmethod
    def decode_pkg(pkg) -> List[Tuple[int, int]]:
        if pkg & 0b1:
            value = pkg >> 1 & 0b01
            duration = pkg >> 2
            return [(value, duration + 1)]
        else:
            return [(int(x), 1) for x in list('{0:015b}'.format(pkg >> 1))]

    @staticmethod
    def expand_duration_list(duration_list: List[Tuple[int, int]]) -> List[int]:
        return list(chain(*[[value] * duration for value, duration in duration_list]))
