from abc import ABCMeta, abstractmethod
from migen import *


__all__  = ["AccessArguments"]
__all__ += ["AccessMultiplexer", "AccessMultiplexerInterface"]
__all__ += ["AccessDemultiplexer", "AccessDemultiplexerInterface"]


class AccessArguments(metaclass=ABCMeta):
    @abstractmethod
    def add_build_arguments(self, parser):
        pass

    @abstractmethod
    def add_run_arguments(self, parser):
        pass

    @abstractmethod
    def add_pin_argument(self, parser, name, default=None):
        pass

    @abstractmethod
    def add_pin_set_argument(self, parser, name, width, default=None):
        pass


class AccessMultiplexer(Module, metaclass=ABCMeta):
    @abstractmethod
    def claim_interface(self, applet, args):
        pass


class AccessMultiplexerInterface(Module, metaclass=ABCMeta):
    @abstractmethod
    def get_out_fifo(self, **kwargs):
        pass

    @abstractmethod
    def get_in_fifo(self, **kwargs):
        pass

    @abstractmethod
    def get_inout_fifo(self, **kwargs):
        pass


class AccessDemultiplexer(metaclass=ABCMeta):
    @abstractmethod
    def claim_raw_interface(self, applet, timeout=None, async=False):
        pass

    @abstractmethod
    def claim_interface(self, applet, args, timeout=None, async=False):
        pass


class AccessDemultiplexerInterface(metaclass=ABCMeta):
    @abstractmethod
    def has_buffered_data(self):
        pass

    @abstractmethod
    def read(self, length=None):
        pass

    def read_str(self, *args, encoding="utf-8", **kwargs):
        result = self.read(*args, **kwargs)
        if result is None:
            return None
        else:
            return result.decode(encoding)

    @abstractmethod
    def write(self, data):
        pass

    def write_str(self, data, *args, encoding="utf-8", **kwargs):
        return self.write(data.encode(encoding), *args, **kwargs)

    @abstractmethod
    def flush(self):
        pass

    def __del__(self):
        self.flush()
