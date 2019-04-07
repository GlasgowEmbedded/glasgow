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
        self.dout     = fifo.dout
        self.comb += [
            fifo.re.eq(self._ce & self.readable & self.re),
            self.readable.eq(self._de & fifo.readable)
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
        self.din      = fifo.din
        self.flush    = fifo.flush
        self.comb += [
            fifo.we.eq(self._ce & self.writable & self.we),
            self.writable.eq(self._de & fifo.writable)
        ]


class DirectMultiplexer(AccessMultiplexer):
    def __init__(self, ports, pipes, registers, fx2_crossbar):
        self._ports         = ports
        self._claimed_ports = set()
        self._pipes         = pipes
        self._claimed_pipes = 0
        self._analyzer      = None
        self._registers     = registers
        self._fx2_crossbar  = fx2_crossbar

    def set_analyzer(self, analyzer):
        assert self._analyzer is None
        self._analyzer = analyzer

    @property
    def pipe_count(self):
        return self._claimed_pipes

    def claim_interface(self, applet, args, with_analyzer=True, throttle="fifo"):
        if self._claimed_pipes == len(self._pipes):
            applet.logger.error("cannot claim pipe: out of pipes")
            return None
        pipe_num = self._claimed_pipes
        self._claimed_pipes += 1

        pins = []
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
                    port_width, port_req = self._ports[port]
                    pins += [(port, bit, port_req) for bit in range(port_width)]
        else:
            iface_spec = []

        if with_analyzer and self._analyzer:
            analyzer = self._analyzer
        else:
            analyzer = None
            throttle = "none"

        if iface_spec:
            applet.logger.debug("claimed pipe %s and port(s) %s",
                                self._pipes[pipe_num], ", ".join(sorted(iface_spec)))
        else:
            applet.logger.debug("claimed pipe %s",
                                self._pipes[pipe_num])

        iface = DirectMultiplexerInterface(applet, analyzer, self._registers,
            self._fx2_crossbar, pipe_num, pins, throttle)
        self.submodules += iface
        return iface


class DirectMultiplexerInterface(AccessMultiplexerInterface):
    def __init__(self, applet, analyzer, registers, fx2_crossbar, pipe_num, pins,
                 throttle):
        assert throttle in ("full", "fifo", "none")

        super().__init__(applet, analyzer)
        self._registers    = registers
        self._fx2_crossbar = fx2_crossbar
        self._pipe_num     = pipe_num
        self._pins         = pins
        self._throttle     = throttle

        self.reset, self._addr_reset = self._registers.add_rw(1, reset=1)
        self.logger.debug("adding reset register at address %#04x", self._addr_reset)

    def get_pin_name(self, pin_num):
        port, bit, req = self._pins[pin_num]
        return "{}{}".format(port, bit)

    def build_pin_tristate(self, pin_num, oe, o, i):
        port, bit, req = self._pins[pin_num]
        pin_parts = req(bit)

        self.specials += \
            Instance("SB_IO",
                p_PIN_TYPE=C(0b101001, 6), # PIN_OUTPUT_TRISTATE|PIN_INPUT
                io_PACKAGE_PIN=pin_parts.io,
                i_OUTPUT_ENABLE=oe,
                i_D_OUT_0=o,
                o_D_IN_0=i,
            )
        if hasattr(pin_parts, "oe"):
            self.comb += pin_parts.oe.eq(oe)

        # This makes the bitstream ID depend on physical pin location, as .pcf is currently
        # not taken into account when generating bitstream ID.
        pin_parts.io.attr.add(("glasgow.pin", "{}{}".format(port, bit)))

    def _throttle_fifo(self, fifo):
        self.submodules += fifo
        if self._throttle == "full":
            fifo.comb += fifo._ce.eq(~self.analyzer.throttle)
        elif self._throttle == "fifo":
            fifo.comb += fifo._de.eq(~self.analyzer.throttle)
        return fifo

    def get_in_fifo(self, **kwargs):
        fifo = self._fx2_crossbar.get_in_fifo(self._pipe_num, **kwargs, reset=self.reset)
        if self.analyzer:
            self.analyzer.add_in_fifo_event(self.applet, fifo)
        return self._throttle_fifo(_FIFOWritePort(fifo))

    def get_out_fifo(self, **kwargs):
        fifo = self._fx2_crossbar.get_out_fifo(self._pipe_num, **kwargs, reset=self.reset)
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
