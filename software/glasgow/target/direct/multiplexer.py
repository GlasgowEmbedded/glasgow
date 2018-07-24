import logging
from migen import *

from ...gateware.pads import Pads
from ..access import AccessMultiplexer, AccessMultiplexerInterface


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
        self._applet      = applet
        self._logger      = applet.logger
        self._fx2_arbiter = fx2_arbiter
        self._fifo_num    = fifo_num
        self._pins        = pins
        self._pin_names   = pin_names

    def get_pins(self, indices):
        triple = TSTriple(len(indices))
        for triple_index, pin_index in enumerate(indices):
            self.specials += \
                Instance("SB_IO",
                    p_PIN_TYPE=0b101001, # PIN_OUTPUT_TRISTATE|PIN_INPUT
                    io_PACKAGE_PIN=self._pins[pin_index],
                    i_OUTPUT_ENABLE=triple.oe,
                    i_D_OUT_0=triple.o[triple_index],
                    o_D_IN_0=triple.i[triple_index],
                )
        return triple

    def get_pin(self, index):
        return self.get_pins([index])

    def get_pads(self, args, pins=[], pin_sets=[]):
        pad_args = {}

        for pin in pins:
            pin_num = getattr(args, "pin_{}".format(pin))
            if pin_num is None:
                self._logger.debug("not assigning pin %r to any device pin", pin)
            else:
                self._logger.debug("assigning pin %r to device pin %s",
                    pin, self._pin_names[pin_num])
                pad_args[pin] = self.get_pin(pin_num)

        for pin_set in pin_sets:
            pin_nums = getattr(args, "pin_set_{}".format(pin_set))
            if pin_nums is None:
                self._logger.debug("not assigning pin set %r to any device pins", pin_set)
            else:
                self._logger.debug("assigning pin set %r to device pins %s",
                    pin_set, ", ".join([self._pin_names[pin_num] for pin_num in pin_nums]))
                pad_args[pin_set] = self.get_pins(pin_nums)

        self.submodules.pads = Pads(**pad_args)
        return self.pads

    def get_out_fifo(self, **kwargs):
        return self._fx2_arbiter.get_out_fifo(self._fifo_num, **kwargs)

    def get_in_fifo(self, **kwargs):
        return self._fx2_arbiter.get_in_fifo(self._fifo_num, **kwargs)

    def get_inout_fifo(self, **kwargs):
        return (self._fx2_arbiter.get_in_fifo(self._fifo_num, **kwargs),
                self._fx2_arbiter.get_out_fifo(self._fifo_num, **kwargs))
