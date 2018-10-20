import logging
from migen import *

from .. import AccessMultiplexer, AccessMultiplexerInterface


class _FIFOReadPort(Module):
    """
    FIFO read port wrapper with control enable and data enable signals.

    The enable signals are asserted at reset.

    Attributes
    ----------
    _ce : Signal
        Control enable. Deasserting control enable prevents any reads from the FIFO
        from happening, but does not change the readable flag.
    _de : Signal
        Data enable. Deasserting data enable prevents any reads and also deasserts
        the readable flag.
    """
    def __init__(self, fifo):
        self.width = fifo.width
        self.depth = fifo.depth

        self._ce = Signal(reset=1)
        self._de = Signal(reset=1)

        self.re       = Signal()
        self.readable = Signal()
        self.dout     = Signal.like(fifo.dout)
        self.comb += [
            fifo.re.eq(self._ce & self.readable & self.re),
            self.readable.eq(self._de & fifo.readable),
            self.dout.eq(fifo.dout)
        ]


class _FIFOWritePort(Module):
    """
    FIFO write port wrapper with control enable and data enable signals.

    The enable signals are asserted at reset.

    Attributes
    ----------
    _ce : Signal
        Control enable. Deasserting control enable prevents any writes to the FIFO
        from happening, but does not change the writable flag.
    _de : Signal
        Data enable. Deasserting data enable prevents any writes and also deasserts
        the writable flag.
    """
    def __init__(self, fifo):
        self.width = fifo.width
        self.depth = fifo.depth

        self._ce = Signal(reset=1)
        self._de = Signal(reset=1)

        self.we       = Signal()
        self.writable = Signal()
        self.din      = Signal.like(fifo.din)
        self.flush    = Signal()
        self.comb += [
            fifo.we.eq(self._ce & self.writable & self.we),
            self.writable.eq(self._de & fifo.writable),
            fifo.din.eq(self.din),
            fifo.flush.eq(self.flush),
        ]


class DirectMultiplexer(AccessMultiplexer):
    def __init__(self, ports, fifo_count, registers, fx2_arbiter):
        self._ports         = ports
        self._claimed_ports = set()
        self._fifo_count    = fifo_count
        self._claimed_fifos = 0
        self._analyzer      = None
        self._registers     = registers
        self._fx2_arbiter   = fx2_arbiter

    def set_analyzer(self, analyzer):
        assert self._analyzer is None
        self._analyzer = analyzer

    def claim_interface(self, applet, args, with_analyzer=True, throttle="fifo"):
        if self._claimed_fifos == self._fifo_count:
            applet.logger.error("cannot claim USB FIFO: out of FIFOs")
            return None
        fifo_num = self._claimed_fifos
        self._claimed_fifos += 1

        pins = []
        pin_names = []
        if hasattr(args, "port_spec"):
            iface_spec = list(args.port_spec)

            claimed_spec = self._claimed_ports.intersection(iface_spec)
            if claimed_spec:
                applet.logger.error("cannot claim port(s) %s: port(s) %s already claimed",
                                    ", ".join(sorted(iface_spec)),
                                    ", ".join(sorted(claimed_spec)))
                return None

            for port in iface_spec:
                if port not in self._ports:
                    applet.logger.error("port %s does not exist", port)
                    return None
                else:
                    port_signal = self._ports[port]()
                    pins += [port_signal[bit] for bit in range(port_signal.nbits)]
                    pin_names += ["{}{}".format(port, bit) for bit in range(port_signal.nbits)]

        if with_analyzer and self._analyzer:
            analyzer = self._analyzer
        else:
            analyzer = None
            throttle = "none"

        iface = DirectMultiplexerInterface(applet, analyzer, self._registers,
            self._fx2_arbiter, fifo_num, pins, pin_names, throttle)
        self.submodules += iface
        return iface


class DirectMultiplexerInterface(AccessMultiplexerInterface):
    def __init__(self, applet, analyzer, registers, fx2_arbiter, fifo_num, pins, pin_names,
                 throttle):
        assert throttle in ("full", "fifo", "none")

        super().__init__(applet, analyzer)
        self._registers   = registers
        self._fx2_arbiter = fx2_arbiter
        self._fifo_num    = fifo_num
        self._pins        = pins
        self._pin_names   = pin_names
        self._throttle    = throttle

        self.reset, self._addr_reset = self._registers.add_rw(1, reset=1)
        self.logger.debug("adding reset register at address %#04x", self._addr_reset)

    def get_pin_name(self, pin):
        return self._pin_names[pin]

    def build_pin_tristate(self, pin, oe, o, i):
        self.specials += \
            Instance("SB_IO",
                p_PIN_TYPE=C(0b101001, 6), # PIN_OUTPUT_TRISTATE|PIN_INPUT
                io_PACKAGE_PIN=self._pins[pin],
                i_OUTPUT_ENABLE=oe,
                i_D_OUT_0=o,
                o_D_IN_0=i,
            )

    def _throttle_fifo(self, fifo):
        self.submodules += fifo
        if self._throttle == "full":
            fifo.comb += fifo._ce.eq(~self.analyzer.throttle)
        elif self._throttle == "fifo":
            fifo.comb += fifo._de.eq(~self.analyzer.throttle)
        return fifo

    def get_in_fifo(self, **kwargs):
        fifo = self._fx2_arbiter.get_in_fifo(self._fifo_num, **kwargs, reset=self.reset)
        if self.analyzer:
            self.analyzer.add_in_fifo_event(self.applet, fifo)
        return self._throttle_fifo(_FIFOWritePort(fifo))

    def get_out_fifo(self, **kwargs):
        fifo = self._fx2_arbiter.get_out_fifo(self._fifo_num, **kwargs, reset=self.reset)
        if self.analyzer:
            self.analyzer.add_out_fifo_event(self.applet, fifo)
        return self._throttle_fifo(_FIFOReadPort(fifo))

    def add_subtarget(self, subtarget):
        if self._throttle == "full":
            # When in the "full" throttling mode, once the throttle signal is asserted while
            # the applet asserts `re` or `we`, the applet will cause spurious reads or writes;
            # this happens because the FIFO is not in the control enable domain of the applet.
            #
            # (This is deliberate; throttling often happens because the analyzer CY7C FIFO is
            # full, but we might still be able to transfer data between the other FIFOs.)
            #
            # Thus, in `_throttle_fifo` above, we add the read (for OUT FIFOs) or write
            # (for IN FIFOs) ports into the applet control enable domain.
            subtarget = CEInserter()(subtarget)
            subtarget.comb += subtarget.ce.eq(~self.analyzer.throttle)

        subtarget = ResetInserter()(subtarget)
        subtarget.comb += subtarget.reset.eq(self.reset)

        self.submodules += subtarget
        return subtarget
