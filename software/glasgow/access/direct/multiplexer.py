import logging
from amaranth import *
from amaranth.lib import io

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

        self._ctrl_en = Signal(init=1)
        self._data_en = Signal(init=1)

        self.r_en   = Signal()
        self.r_rdy  = Signal()
        self.r_data = fifo.r_data

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

        self._ctrl_en = Signal(init=1)
        self._data_en = Signal(init=1)

        self.w_en   = Signal()
        self.w_rdy  = Signal()
        self.w_data = fifo.w_data
        self.flush  = fifo.flush

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
        self._ifaces        = []

    def elaborate(self, platform):
        m = Module()
        m.submodules += self._ifaces
        return m

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
        self._ifaces.append(iface)
        return iface


class DirectMultiplexerInterface(AccessMultiplexerInterface):
    def __init__(self, applet, analyzer, registers, fx2_crossbar, pipe_num, pins, throttle):
        assert throttle in ("full", "fifo", "none")

        super().__init__(applet, analyzer)
        self._registers     = registers
        self._fx2_crossbar  = fx2_crossbar
        self._pipe_num      = pipe_num
        self._pins          = pins
        self._throttle      = throttle
        self._subtargets    = []
        self._fifos         = []
        self._pin_tristates = []

        self.reset, self._addr_reset = self._registers.add_rw(1, init=1)
        self.logger.debug("adding reset register at address %#04x", self._addr_reset)

    def elaborate(self, platform):
        m = Module()

        m.submodules += self._subtargets
        if self.pads is not None:
            m.submodules.pads = self.pads

        for fifo in self._fifos:
            if self._throttle == "full":
                m.d.comb += fifo._ctrl_en.eq(~self.analyzer.throttle)
            elif self._throttle == "fifo":
                m.d.comb += fifo._data_en.eq(~self.analyzer.throttle)

            m.submodules += fifo

        for pin_parts, oe, o, i in self._pin_tristates:
            m.submodules += (io_buffer := io.Buffer("io", pin_parts.io))
            m.d.comb += [
                io_buffer.oe.eq(oe),
                io_buffer.o.eq(o),
                i.eq(io_buffer.i),
            ]
            if hasattr(pin_parts, "oe"):
                m.submodules += (oe_buffer := io.Buffer("o", pin_parts.oe))
                m.d.comb += oe_buffer.o.eq(oe)

        return m

    def get_pin_name(self, pin_num):
        port, bit, req = self._pins[pin_num]
        return f"{port}{bit}"

    def build_pin_tristate(self, pin_num, oe, o, i):
        port, bit, req = self._pins[pin_num]
        pin_parts = req(bit)
        self._pin_tristates.append((pin_parts, oe, o, i))

    def get_in_fifo(self, **kwargs):
        fifo = self._fx2_crossbar.get_in_fifo(self._pipe_num, **kwargs, reset=self.reset)
        if self.analyzer:
            self.analyzer.add_in_fifo_event(self.applet, fifo)
        fifo = _FIFOWritePort(fifo)
        self._fifos.append(fifo)
        return fifo

    def get_out_fifo(self, **kwargs):
        fifo = self._fx2_crossbar.get_out_fifo(self._pipe_num, **kwargs, reset=self.reset)
        if self.analyzer:
            self.analyzer.add_out_fifo_event(self.applet, fifo)
        fifo = _FIFOReadPort(fifo)
        self._fifos.append(fifo)
        return fifo

    def add_subtarget(self, subtarget):
        if self._throttle == "full":
            # When in the "full" throttling mode, once the throttle signal is asserted while
            # the applet asserts `r_en` or `w_en`, the applet will cause spurious reads or writes;
            # this happens because the FIFO is not in the control enable domain of the applet.
            #
            # (This is deliberate; throttling often happens because the analyzer CY7C FIFO is
            # full, but we might still be able to transfer data between the other FIFOs.)
            #
            # Thus, in `elaborate` above, we add the read (for OUT FIFOs) or write
            # (for IN FIFOs) ports into the applet control enable domain.
            subtarget = EnableInserter(~self.analyzer.throttle)(subtarget)

        # Reset the subtarget simultaneously with the USB-side and FPGA-side FIFOs. This ensures
        # that when the demultiplexer interface is reset, the gateware and the host software are
        # synchronized with each other.
        subtarget = ResetInserter(self.reset)(subtarget)

        self._subtargets.append(subtarget)
        return subtarget
