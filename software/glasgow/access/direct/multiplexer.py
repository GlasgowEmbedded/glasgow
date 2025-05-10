import logging
from amaranth import *
from amaranth.lib import stream, io

from ...platform.generic import GlasgowPlatformPort
from .. import AccessMultiplexer, AccessMultiplexerInterface


class _FIFOReadPort:
    """
    FIFO read port wrapper that exists for historical reasons.
    """
    def __init__(self, fifo):
        self.stream = fifo.r

        self.r_data = fifo.r.payload
        self.r_rdy  = fifo.r.valid
        self.r_en   = fifo.r.ready


class _FIFOWritePort:
    """
    FIFO write port wrapper that exists for historical reasons.
    """
    def __init__(self, fifo):
        self.stream = fifo.w

        self.w_data = fifo.w.payload
        self.w_en   = fifo.w.valid
        self.w_rdy  = fifo.w.ready
        self.flush  = fifo.flush


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

    def claim_interface(self, applet, args, with_analyzer=True):
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

        if iface_spec:
            applet.logger.debug("claimed pipe %s and port(s) %s",
                                self._pipes[pipe_num], ", ".join(sorted(iface_spec)))
        else:
            applet.logger.debug("claimed pipe %s",
                                self._pipes[pipe_num])

        iface = DirectMultiplexerInterface(applet, analyzer, self._registers,
            self._fx2_crossbar, pipe_num, pins)
        self._ifaces.append(iface)
        return iface


class DirectMultiplexerInterface(AccessMultiplexerInterface):
    def __init__(self, applet, analyzer, registers, fx2_crossbar, pipe_num, pins):
        super().__init__(applet, analyzer)
        self._registers     = registers
        self._fx2_crossbar  = fx2_crossbar
        self._pipe_num      = pipe_num
        self._pins          = pins
        self._subtargets    = []
        self._fifos         = []

        self.reset, self._addr_reset = self._registers.add_rw(1, init=1)
        self.logger.debug("adding reset register at address %#04x", self._addr_reset)

    def elaborate(self, platform):
        m = Module()

        for subtarget in self._subtargets:
            # Reset the subtarget simultaneously with the USB-side and FPGA-side FIFOs. This ensures
            # that when the demultiplexer interface is reset, the gateware and the host software are
            # synchronized with each other.
            m.submodules += ResetInserter(self.reset)(subtarget)

        return m

    def get_pin_name(self, pin):
        port, bit, request = self._pins[pin.number]
        return f"{port}{bit}"

    def get_port_impl(self, pin, *, name):
        port, bit, request = self._pins[pin.number]
        self.logger.debug("assigning applet port '%s' to device pin %s%s",
            name, self.get_pin_name(pin), " (inverted)" if pin.invert else "")
        pin_components = request(bit)
        return GlasgowPlatformPort(
            io=~pin_components.io if pin.invert else pin_components.io,
            oe=getattr(pin_components, "oe", None)
        )

    def get_in_fifo(self, **kwargs):
        fifo = self._fx2_crossbar.get_in_fifo(self._pipe_num, **kwargs, reset=self.reset)
        if self.analyzer:
            self.analyzer.add_in_fifo_event(self.applet, fifo)
        return _FIFOWritePort(fifo)

    def get_out_fifo(self, **kwargs):
        fifo = self._fx2_crossbar.get_out_fifo(self._pipe_num, **kwargs, reset=self.reset)
        if self.analyzer:
            self.analyzer.add_out_fifo_event(self.applet, fifo)
        return _FIFOReadPort(fifo)

    def add_subtarget(self, subtarget):
        self._subtargets.append(subtarget)
        return subtarget
