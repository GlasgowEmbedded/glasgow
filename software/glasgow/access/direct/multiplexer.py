import logging
from migen import *

from .. import AccessMultiplexer, AccessMultiplexerInterface


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

    def claim_interface(self, applet, args, with_analyzer=True):
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

        if with_analyzer:
            analyzer = self._analyzer
        else:
            analyzer = None

        iface = DirectMultiplexerInterface(applet, analyzer, self._registers,
            self._fx2_arbiter, fifo_num, pins, pin_names)
        self.submodules += iface
        return iface


class DirectMultiplexerInterface(AccessMultiplexerInterface):
    def __init__(self, applet, analyzer, registers, fx2_arbiter, fifo_num, pins, pin_names,
                 with_reset=True):
        super().__init__(applet, analyzer)
        self._registers   = registers
        self._fx2_arbiter = fx2_arbiter
        self._fifo_num    = fifo_num
        self._pins        = pins
        self._pin_names   = pin_names

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

    def get_in_fifo(self, **kwargs):
        fifo = self._fx2_arbiter.get_in_fifo(self._fifo_num, **kwargs, reset=self.reset)
        if self.analyzer:
            self.analyzer.add_in_fifo_event(self.applet, fifo)
        return fifo

    def get_out_fifo(self, **kwargs):
        fifo = self._fx2_arbiter.get_out_fifo(self._fifo_num, **kwargs, reset=self.reset)
        if self.analyzer:
            self.analyzer.add_out_fifo_event(self.applet, fifo)
        return fifo

    def add_subtarget(self, subtarget):
        subtarget = ResetInserter()(subtarget)
        self.submodules += subtarget
        self.comb += subtarget.reset.eq(self.reset)
        return subtarget
