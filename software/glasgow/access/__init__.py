from abc import ABCMeta, abstractmethod
from migen import *

from ..gateware.pads import Pads


__all__  = ["AccessArguments"]
__all__ += ["AccessMultiplexer", "AccessMultiplexerInterface"]
__all__ += ["AccessDemultiplexer", "AccessDemultiplexerInterface"]


class AccessArguments(metaclass=ABCMeta):
    def _arg_error(self, message, *args, **kwargs):
        raise argparse.ArgumentTypeError(("applet {!r}: " + message)
                                         .format(self._applet_name, *args, **kwargs))

    @abstractmethod
    def add_build_arguments(self, parser):
        pass

    @abstractmethod
    def add_run_arguments(self, parser):
        pass

    @abstractmethod
    def add_pin_argument(self, parser, name, default=None, required=False):
        pass

    @abstractmethod
    def add_pin_set_argument(self, parser, name, width, default=None, required=False):
        pass


class AccessMultiplexer(Module, metaclass=ABCMeta):
    @abstractmethod
    def claim_interface(self, applet, args):
        pass


class AccessMultiplexerInterface(Module, metaclass=ABCMeta):
    def __init__(self, applet):
        self.applet = applet
        self.logger = applet.logger

    @abstractmethod
    def get_out_fifo(self, **kwargs):
        pass

    @abstractmethod
    def get_in_fifo(self, **kwargs):
        pass

    @abstractmethod
    def get_inout_fifo(self, **kwargs):
        pass

    @abstractmethod
    def build_pin_tristate(self, pin, oe, o, i):
        pass

    @abstractmethod
    def get_pin_name(self, pin):
        pass

    def get_pins(self, pins):
        triple = TSTriple(len(pins))
        for n, pin in enumerate(pins):
            self.build_pin_tristate(pin, triple.oe, triple.o[n], triple.i[n])
        return triple

    def get_pin(self, pin):
        return self.get_pins([pin])

    def get_pads(self, args, pins=[], pin_sets=[]):
        pad_args = {}

        for pin in pins:
            pin_num = getattr(args, "pin_{}".format(pin))
            if pin_num is None:
                self.logger.debug("not assigning pin %r to any device pin", pin)
            else:
                self.logger.debug("assigning pin %r to device pin %s",
                    pin, self.get_pin_name(pin_num))
                pad_args[pin] = self.get_pin(pin_num)

        for pin_set in pin_sets:
            pin_nums = getattr(args, "pin_set_{}".format(pin_set))
            if pin_nums is None:
                self.logger.debug("not assigning pin set %r to any device pins", pin_set)
            else:
                self.logger.debug("assigning pin set %r to device pins %s",
                    pin_set, ", ".join([self.get_pin_name(pin_num) for pin_num in pin_nums]))
                pad_args[pin_set] = self.get_pins(pin_nums)

        self.submodules.pads = Pads(**pad_args)
        return self.pads


class AccessDemultiplexer(metaclass=ABCMeta):
    def __init__(self, device):
        self.device = device
        self._interfaces = []

    @abstractmethod
    async def claim_interface(self, applet, mux_interface, args, timeout=None):
        pass

    async def flush(self):
        for iface in self._interfaces:
            await iface.flush()


class AccessDemultiplexerInterface(metaclass=ABCMeta):
    def __init__(self, device, applet):
        self.device = device
        self.applet = applet
        self.logger = applet.logger

    @abstractmethod
    async def reset(self):
        pass

    @abstractmethod
    async def read(self, length=None):
        pass

    async def read_str(self, *args, encoding="utf-8", **kwargs):
        result = await self.read(*args, **kwargs)
        if result is None:
            return None
        else:
            return result.decode(encoding)

    @abstractmethod
    async def write(self, data):
        pass

    async def write_str(self, data, *args, encoding="utf-8", **kwargs):
        await self.write(data.encode(encoding), *args, **kwargs)

    @abstractmethod
    async def flush(self):
        pass
