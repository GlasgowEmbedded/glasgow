import logging
from migen import *

from .. import AccessMultiplexer, AccessMultiplexerInterface


class DirectMultiplexer(AccessMultiplexer):
    def __init__(self, ports, fifo_count, fx2_arbiter):
        self._ports         = ports
        self._claimed_ports = set()
        self._fifo_count    = fifo_count
        self._claimed_fifos = 0
        self._fx2_arbiter   = fx2_arbiter

    def claim_interface(self, applet, args):
        iface_spec = list(args.port_spec)

        claimed_spec = self._claimed_ports.intersection(iface_spec)
        if claimed_spec:
            applet.logger.error("cannot claim port(s) %s: port(s) %s already claimed",
                                ", ".join(sorted(iface_spec)),
                                ", ".join(sorted(claimed_spec)))
            return None

        pins = []
        pin_names = []
        for port in iface_spec:
            if port not in self._ports:
                applet.logger.error("port %s does not exist", port)
                return None
            else:
                port_signal = self._ports[port]()
                pins += [port_signal[bit] for bit in range(port_signal.nbits)]
                pin_names += ["{}{}".format(port, bit) for bit in range(port_signal.nbits)]

        if self._claimed_fifos == self._fifo_count:
            applet.logger.error("cannot claim USB FIFO: out of FIFOs")
            return None
        fifo_num = self._claimed_fifos
        self._claimed_fifos += 1

        iface = DirectMultiplexerInterface(applet, self._fx2_arbiter, fifo_num, pins, pin_names)
        self.submodules += iface
        return iface


class DirectMultiplexerInterface(AccessMultiplexerInterface):
    def __init__(self, applet, fx2_arbiter, fifo_num, pins, pin_names):
        super().__init__(applet)
        self._fx2_arbiter = fx2_arbiter
        self._fifo_num    = fifo_num
        self._pins        = pins
        self._pin_names   = pin_names

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

    def get_out_fifo(self, **kwargs):
        return self._fx2_arbiter.get_out_fifo(self._fifo_num, **kwargs)

    def get_in_fifo(self, **kwargs):
        return self._fx2_arbiter.get_in_fifo(self._fifo_num, **kwargs)

    def get_inout_fifo(self, **kwargs):
        return (self._fx2_arbiter.get_in_fifo(self._fifo_num, **kwargs),
                self._fx2_arbiter.get_out_fifo(self._fifo_num, **kwargs))
