import os
import sys
import logging
import asyncio
import argparse
from amaranth import *

from ...gateware.pads import *
from .. import *

__all__ = ["LEDApplet"]

class Bus(Elaboratable):
    def __init__(self, pads):
        self.pads = pads
        self.has_debug = hasattr(pads, "debug_t")
        if self.has_debug:
           self.debug_t = pads.debug_t
           self.debug_o = Signal()

    def elaborate(self, platform):
        m = Module()
        if self.has_debug:
            m.d.comb += self.debug_t.o.eq(self.debug_o)
        return m

class ClockModule(Elaboratable):
    def __init__(self):
        self.cycles = int(48e6)
        self.stb = Signal(1,reset=0)

    def elaborate(self, platform):
        m = Module()
        timer = Signal(range(self.cycles),reset=self.cycles-1)
        with m.If(timer == 0):
            m.d.sync += timer.eq(self.cycles)
        with m.Else():
            m.d.sync += timer.eq(timer - 1)
        m.d.comb += self.stb.eq(timer == 0)
        return m

class LEDSubtarget(Elaboratable):

    def __init__(self, pads, out_fifo, in_fifo):
        self.pads = pads
        self.out_fifo = out_fifo
        self.in_fifo = in_fifo
        self.clock = ClockModule()
        self.bus = Bus(pads=pads)

    def elaborate(self, platform):
        m = Module()
        m.submodules.clock = self.clock
        m.submodules.bus = self.bus
        led0 = platform.request('led', 0).o
        #m.d.sync += led0.eq(1)
        with m.If(self.clock.stb):
            m.d.sync += led0.eq(~led0)
            m.d.sync += self.bus.debug_o.eq(~self.bus.debug_o)
        return m

class LEDApplet(GlasgowApplet, name='led'):
    logger = logging.getLogger(__name__)
    help = "LED Example"
    description = """"""

    __pins = (["debug"])

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in cls.__pins:
            access.add_pin_argument(parser, pin, default=True)

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(LEDSubtarget(pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo()))

    async def run(self, device, args):
        return await device.demultiplexer.claim_interface(self, self.mux_interface, args)

