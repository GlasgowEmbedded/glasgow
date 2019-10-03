import logging
from nmigen.compat import *
from nmigen.compat.genlib.cdc import MultiReg
from nmigen.compat.genlib.fifo import _FIFOInterface

from ..gateware.analyzer import *


__all__ = ["GlasgowAnalyzer"]


class GlasgowAnalyzer(Module):
    logger = logging.getLogger(__name__)

    def __init__(self, registers, multiplexer, event_depth=None):
        multiplexer.set_analyzer(self)
        self.mux_interface  = multiplexer.claim_interface(self, args=None, with_analyzer=False)
        self.event_analyzer = self.mux_interface.add_subtarget(
            EventAnalyzer(output_fifo=self.mux_interface.get_in_fifo(auto_flush=False),
                          event_depth=event_depth))
        self.event_sources = self.event_analyzer.event_sources
        self.throttle      = self.event_analyzer.throttle

        self.done, self.addr_done = registers.add_rw(1)
        self.logger.debug("adding done register at address %#04x", self.addr_done)
        self.comb += self.event_analyzer.done.eq(self.done)

        self._pins = []

    def _name(self, applet, event):
        # return "{}-{}".format(applet.name, event)
        return event

    def add_generic_event(self, applet, name, signal):
        event_source = self.event_analyzer.add_event_source(
            name=self._name(applet, name), kind="change", width=signal.nbits)
        signal_r = Signal.like(signal)
        event_source.sync += [
            signal_r.eq(signal),
        ]
        event_source.comb += [
            event_source.data.eq(signal),
            event_source.trigger.eq(signal != signal_r),
        ]

    def add_in_fifo_event(self, applet, fifo):
        event_source = self.event_analyzer.add_event_source(
            name=self._name(applet, "fifo-in"), kind="strobe", width=8)
        event_source.sync += [
            event_source.trigger.eq(fifo.writable & fifo.we),
            event_source.data.eq(fifo.din)
        ]

    def add_out_fifo_event(self, applet, fifo):
        event_source = self.event_analyzer.add_event_source(
            name=self._name(applet, "fifo-out"), kind="strobe", width=8)
        event_source.comb += [
            event_source.trigger.eq(fifo.readable & fifo.re),
            event_source.data.eq(fifo.dout)
        ]

    def add_pin_event(self, applet, name, triple):
        self._pins.append((self._name(applet, name), triple))

    def _finalize_pin_events(self):
        if not self._pins:
            return

        reg_reset = Signal()
        self.sync += reg_reset.eq(self.mux_interface.reset)

        pin_oes = []
        pin_ios = []
        for (name, triple) in self._pins:
            sync_i = Signal.like(triple.i)
            self.specials += MultiReg(triple.i, sync_i)
            pin_oes.append((name, triple.oe))
            pin_ios.append((name, Mux(triple.oe, triple.o, sync_i)))

        sig_oes = Cat(oe for n, oe in pin_oes)
        reg_oes = Signal.like(sig_oes)
        sig_ios = Cat(io for n, io in pin_ios)
        reg_ios = Signal.like(sig_ios)
        self.sync += [
            reg_oes.eq(sig_oes),
            reg_ios.eq(sig_ios),
        ]

        oe_event_source = self.event_analyzer.add_event_source(
            name="oe", kind="change", width=value_bits_sign(sig_oes)[0],
            fields=[(name, value_bits_sign(oe)[0]) for name, oe in pin_oes])
        io_event_source = self.event_analyzer.add_event_source(
            name="io", kind="change", width=value_bits_sign(sig_ios)[0],
            fields=[(name, value_bits_sign(io)[0]) for name, io in pin_ios])
        self.comb += [
            oe_event_source.trigger.eq(reg_reset | (sig_oes != reg_oes)),
            oe_event_source.data.eq(sig_oes),
            io_event_source.trigger.eq(reg_reset | (sig_ios != reg_ios)),
            io_event_source.data.eq(sig_ios),
        ]
