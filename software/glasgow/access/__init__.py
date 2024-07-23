from abc import ABCMeta, abstractmethod
from amaranth import *
from amaranth.lib import io
import argparse

from ..gateware.ports import PortGroup


__all__  = ["AccessArguments"]
__all__ += ["AccessMultiplexer", "AccessMultiplexerInterface"]
__all__ += ["AccessDemultiplexer", "AccessDemultiplexerInterface"]


class _DeprecatedPads:
    """Deprecated in favor of :class:`glasgow.gateware.ports.PortGroup`."""


class AccessArguments(metaclass=ABCMeta):
    def _arg_error(self, message):
        raise argparse.ArgumentTypeError(f"applet {self._applet_name!r}: " + message)

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


class AccessMultiplexer(Elaboratable, metaclass=ABCMeta):
    @abstractmethod
    def set_analyzer(self, analyzer):
        pass

    @abstractmethod
    def claim_interface(self, applet, args, with_analyzer=True):
        pass


class AccessMultiplexerInterface(Elaboratable, metaclass=ABCMeta):
    def __init__(self, applet, analyzer):
        self.applet   = applet
        self.logger   = applet.logger
        self.analyzer = analyzer

        self._deprecated_buffers = []

    @abstractmethod
    def get_out_fifo(self, **kwargs):
        pass

    @abstractmethod
    def get_in_fifo(self, **kwargs):
        pass

    @abstractmethod
    def get_pin_name(self, pin):
        pass

    @abstractmethod
    def get_port_impl(self, pin, *, name):
        pass

    def get_port(self, pin_or_pins, *, name):
        if isinstance(pin_or_pins, list):
            if pin_or_pins == []:
                self.logger.debug("not assigning applet ports '%s[]' to any device pins", name)
                return None
            port = None
            for index, subpin in enumerate(pin_or_pins):
                subport = self.get_port(subpin, name=f"{name}[{index}]")
                if port is None:
                    port  = subport
                else:
                    port += subport
            assert port is not None
            return port
        else:
            if pin_or_pins is None:
                self.logger.debug("not assigning applet port '%s' to any device pin", name)
                return None
            return self.get_port_impl(pin_or_pins, name=name)

    def get_port_group(self, **kwargs):
        return PortGroup(**{
            name: self.get_port(pin_or_pins, name=name) for name, pin_or_pins in kwargs.items()
        })

    def get_deprecated_pad(self, pins, name=None):
        port = self.get_port(pins, name=name)
        self._deprecated_buffers.append(buffer := io.Buffer("io", port))
        if self.analyzer:
            if name is None:
                name = ",".join(self.get_pin_name(pins) for pins in pins)
            self.analyzer.add_pin_event(self.applet, name, buffer)
        return buffer

    def get_deprecated_pads(self, args, pins=[], pin_sets=[]):
        pads = _DeprecatedPads()
        for pin in pins:
            pin_num = getattr(args, f"pin_{pin}")
            if pin_num is not None:
                setattr(pads, f"{pin}_t", self.get_deprecated_pad(pin_num, name=pin))
        for pin_set in pin_sets:
            pin_nums = getattr(args, f"pin_set_{pin_set}")
            if pin_nums is not None:
                setattr(pads, f"{pin_set}_t", self.get_deprecated_pad(pin_nums, name=pin_set))
        # Horrifically dirty, but the `uart` applet currently depends on this :(
        self.pads = pads
        return pads


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

    async def cancel(self):
        for iface in self._interfaces:
            await iface.cancel()

    def statistics(self):
        for iface in self._interfaces:
            iface.statistics()


class AccessDemultiplexerInterface(metaclass=ABCMeta):
    def __init__(self, device, applet):
        self.device = device
        self.applet = applet
        self.logger = applet.logger

    @abstractmethod
    async def cancel(self):
        pass

    @abstractmethod
    async def reset(self):
        pass

    @abstractmethod
    async def read(self, length=None, *, flush=True):
        pass

    @abstractmethod
    async def write(self, data):
        pass

    @abstractmethod
    async def flush(self, wait=True):
        pass

    def statistics(self):
        pass
