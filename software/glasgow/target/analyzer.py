import logging
from amaranth import *
from amaranth.lib.cdc import FFSynchronizer

from ..gateware.analyzer import *


__all__ = ["GlasgowAnalyzer"]


class GlasgowAnalyzer(Elaboratable):
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

        self._generics = []
        self._in_fifos = []
        self._out_fifos = []
        self._pins = []

    def _name(self, applet, event):
        # return "{}-{}".format(applet.name, event)
        return event

    def add_generic_event(self, applet, name, signal):
        event_source = self.event_analyzer.add_event_source(
            name=self._name(applet, name), kind="change", width=len(signal))
        self._generics.append((signal, event_source))

    def add_in_fifo_event(self, applet, fifo):
        event_source = self.event_analyzer.add_event_source(
            name=self._name(applet, "fifo-in"), kind="strobe", width=8)
        self._in_fifos.append((fifo, event_source))

    def add_out_fifo_event(self, applet, fifo):
        event_source = self.event_analyzer.add_event_source(
            name=self._name(applet, "fifo-out"), kind="strobe", width=8)
        self._out_fifos.append((fifo, event_source))

    def add_pin_event(self, applet, name, triple):
        self._pins.append((self._name(applet, name), triple))

    def _finalize_pin_events(self):
        if not self._pins:
            return

        pin_oes = []
        pin_ios = []
        self._ffsyncs = []
        for (name, triple) in self._pins:
            sync_i = Signal.like(triple.i)
            self._ffsyncs.append(FFSynchronizer(triple.i, sync_i))
            pin_oes.append((name, triple.oe))
            pin_ios.append((name, Mux(triple.oe, triple.o, sync_i)))

        self.sig_oes = Cat(oe for n, oe in pin_oes)
        self.sig_ios = Cat(io for n, io in pin_ios)

        self.oe_event_source = self.event_analyzer.add_event_source(
            name="oe", kind="change", width=len(self.sig_oes),
            fields=[(name, len(oe)) for name, oe in pin_oes])
        self.io_event_source = self.event_analyzer.add_event_source(
            name="io", kind="change", width=len(self.sig_ios),
            fields=[(name, len(io)) for name, io in pin_ios])

    def elaborate(self, platform):
        m = Module()

        m.d.comb += self.event_analyzer.done.eq(self.done)

        for signal, event_source in self._generics:
            signal_r = Signal.like(signal)
            m.d.sync += [
                signal_r.eq(signal),
            ]
            m.d.comb += [
                event_source.data.eq(signal),
                event_source.trigger.eq(signal != signal_r),
            ]

        for fifo, event_source in self._in_fifos:
            m.d.sync += [
                event_source.trigger.eq(fifo.w_rdy & fifo.w_en),
                event_source.data.eq(fifo.w_data)
            ]

        for fifo, event_source in self._out_fifos:
            m.d.comb += [
                event_source.trigger.eq(fifo.r_rdy & fifo.r_en),
                event_source.data.eq(fifo.r_data)
            ]

        if self._pins:
            m.submodules += self._ffsyncs

            reg_reset = Signal()
            m.d.sync += reg_reset.eq(self.mux_interface.reset)

            reg_oes = Signal.like(self.sig_oes)
            reg_ios = Signal.like(self.sig_ios)
            m.d.sync += [
                reg_oes.eq(self.sig_oes),
                reg_ios.eq(self.sig_ios),
            ]

            m.d.comb += [
                self.oe_event_source.trigger.eq(reg_reset | (self.sig_oes != reg_oes)),
                self.oe_event_source.data.eq(self.sig_oes),
                self.io_event_source.trigger.eq(reg_reset | (self.sig_ios != reg_ios)),
                self.io_event_source.data.eq(self.sig_ios),
            ]

        return m
