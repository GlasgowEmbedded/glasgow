import logging

from amaranth import *
from amaranth.lib import wiring, stream

from .platform import GlasgowPlatformPort
from ..gateware.stream import StreamFIFO
from ..access import AccessMultiplexer, AccessMultiplexerInterface


class _FIFOReadPort:
    """
    FIFO read port wrapper that exists for historical reasons.
    """
    def __init__(self, depth):
        self.depth  = depth

        self.stream = stream.Signature(8).create()

        self.r_data = self.stream.payload
        self.r_rdy  = self.stream.valid
        self.r_en   = self.stream.ready


class _FIFOWritePort:
    """
    FIFO write port wrapper that exists for historical reasons.
    """
    def __init__(self, depth, auto_flush):
        self.depth  = depth

        self.stream = stream.Signature(8).flip().create()

        self.w_data = self.stream.payload
        self.w_en   = self.stream.valid
        self.w_rdy  = self.stream.ready
        self.flush  = Signal(init=auto_flush)


class DirectMultiplexer(AccessMultiplexer):
    def __init__(self, ports, pipes, registers, fx2_crossbar):
        self._ports         = ports
        self._claimed_ports = set()
        self._pipes         = pipes
        self._claimed_pipes = 0
        self._registers     = registers
        self._fx2_crossbar  = fx2_crossbar
        self._ifaces        = []

    def elaborate(self, platform):
        m = Module()
        m.submodules += self._ifaces
        return m

    @property
    def pipe_count(self):
        return self._claimed_pipes

    def claim_interface(self, applet, args):
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

        if iface_spec:
            applet.logger.debug("claimed pipe %s and port(s) %s",
                                self._pipes[pipe_num], ", ".join(sorted(iface_spec)))
        else:
            applet.logger.debug("claimed pipe %s",
                                self._pipes[pipe_num])

        self._ifaces.append(iface := DirectMultiplexerInterface(
            applet, self._registers, self._fx2_crossbar, pipe_num, pins))
        return iface


class DirectMultiplexerInterface(AccessMultiplexerInterface):
    def __init__(self, applet, registers, fx2_crossbar, pipe_num, pins):
        super().__init__(applet)
        self._registers     = registers
        self._fx2_crossbar  = fx2_crossbar
        self._pipe_num      = pipe_num
        self._pins          = pins
        self._subtarget     = None
        self._in_port       = None
        self._out_port      = None

        self.reset, self._addr_reset = self._registers.add_rw(1, init=1)
        self.logger.debug("adding reset register at address %#04x", self._addr_reset)

    def elaborate(self, platform):
        m = Module()

        # Reset the subtarget simultaneously with the USB-side and FPGA-side FIFOs. This ensures
        # that when the demultiplexer interface is reset, the gateware and the host software are
        # synchronized with each other.

        if self._subtarget:
            m.submodules.subtarget = ResetInserter(self.reset)(self._subtarget)

        if self._in_port:
            m.submodules.in_fifo = in_fifo = ResetInserter(self.reset)(
                StreamFIFO(shape=8, depth=self._in_port.depth))
            in_ep = self._fx2_crossbar.in_eps[self._pipe_num]
            m.d.comb += in_ep.reset.eq(self.reset)
            wiring.connect(m, in_fifo.w, wiring.flipped(self._in_port.stream))
            wiring.connect(m, in_ep.data, in_fifo.r)
            m.d.comb += in_ep.flush.eq(self._in_port.flush)

        if self._out_port:
            m.submodules.out_fifo = out_fifo = ResetInserter(self.reset)(
                StreamFIFO(shape=8, depth=self._out_port.depth))
            out_ep = self._fx2_crossbar.out_eps[self._pipe_num]
            m.d.comb += out_ep.reset.eq(self.reset)
            wiring.connect(m, out_fifo.w, out_ep.data)
            wiring.connect(m, wiring.flipped(self._out_port.stream), out_fifo.r)

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

    def get_in_fifo(self, depth=512, auto_flush=True):
        assert self._in_port is None, "only one IN FIFO can be requested"

        self._in_port = _FIFOWritePort(depth, auto_flush)
        return self._in_port

    def get_out_fifo(self, depth=512):
        assert self._out_port is None, "only one OUT FIFO can be requested"

        self._out_port = _FIFOReadPort(depth)
        return self._out_port

    def add_subtarget(self, subtarget):
        assert self._subtarget is None, "only one subtarget can be added"

        self._subtarget = subtarget
        return subtarget
