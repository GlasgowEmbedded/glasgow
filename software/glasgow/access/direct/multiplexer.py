import logging
from nmigen import *

from .. import AccessMultiplexer, AccessMultiplexerInterface


class _FIFOReadPort(Elaboratable):
    """
    FIFO read port wrapper with control enable and data enable signals.

    The enable signals are asserted at reset.

    Attributes
    ----------
    _ctrl_en : Signal
        Control enable. Deasserting control enable prevents any reads from the FIFO
        from happening, but does not change the readable flag.
    _data_en : Signal
        Data enable. Deasserting data enable prevents any reads and also deasserts
        the readable flag.
    """
    def __init__(self, fifo):
        self._fifo = fifo
        self.width = fifo.width
        self.depth = fifo.depth

        self._ctrl_en = Signal(reset=1)
        self._data_en = Signal(reset=1)

        self.r_en   = Signal()
        self.r_rdy  = Signal()
        self.r_data = fifo.r_data

        # TODO(nmigen): rename these
        self.re       = self.r_en
        self.readable = self.r_rdy
        self.dout     = self.r_data

    def elaborate(self, platform):
        fifo = self._fifo

        m = Module()
        m.d.comb += [
            fifo.r_en .eq(self._ctrl_en & self.r_rdy & self.r_en),
            self.r_rdy.eq(self._data_en & fifo.r_rdy)
        ]
        return m


class _FIFOWritePort(Elaboratable):
    """
    FIFO write port wrapper with control enable and data enable signals.

    The enable signals are asserted at reset.

    Attributes
    ----------
    _ctrl_en : Signal
        Control enable. Deasserting control enable prevents any writes to the FIFO
        from happening, but does not change the writable flag.
    _data_en : Signal
        Data enable. Deasserting data enable prevents any writes and also deasserts
        the writable flag.
    """
    def __init__(self, fifo):
        self._fifo = fifo
        self.width = fifo.width
        self.depth = fifo.depth

        self._ctrl_en = Signal(reset=1)
        self._data_en = Signal(reset=1)

        self.w_en   = Signal()
        self.w_rdy  = Signal()
        self.w_data = fifo.w_data
        self.flush  = fifo.flush

        # TODO(nmigen): rename these
        self.we       = self.w_en
        self.writable = self.w_rdy
        self.din      = self.w_data

    def elaborate(self, platform):
        fifo = self._fifo

        m = Module()
        m.d.comb += [
            fifo.w_en .eq(self._ctrl_en & self.w_rdy & self.w_en),
            self.w_rdy.eq(self._data_en & fifo.w_rdy)
        ]
        return m


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
        self.comb += [
            pin_parts.io.oe.eq(oe),
            pin_parts.io.o.eq(o),
            i.eq(pin_parts.io.i),
        ]
        if hasattr(pin_parts, "oe"):
            self.comb += pin_parts.oe.o.eq(oe)

    def _throttle_fifo(self, fifo):
        if self._throttle == "full":
            self.comb += fifo._ctrl_en.eq(~self.analyzer.throttle)
        elif self._throttle == "fifo":
            self.comb += fifo._data_en.eq(~self.analyzer.throttle)

        self.submodules += fifo
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
            # the applet asserts `r_en` or `w_en`, the applet will cause spurious reads or writes;
            # this happens because the FIFO is not in the control enable domain of the applet.
            #
            # (This is deliberate; throttling often happens because the analyzer CY7C FIFO is
            # full, but we might still be able to transfer data between the other FIFOs.)
            #
            # Thus, in `_throttle_fifo` above, we add the read (for OUT FIFOs) or write
            # (for IN FIFOs) ports into the applet control enable domain.
            subtarget = EnableInserter(~self.analyzer.throttle)(subtarget)

        # Reset the subtarget simultaneously with the USB-side and FPGA-side FIFOs. This ensures
        # that when the demultiplexer interface is reset, the gateware and the host software are
        # synchronized with each other.
        subtarget = ResetInserter(self.reset)(subtarget)

        self.submodules += subtarget
        return subtarget
