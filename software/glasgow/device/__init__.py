from abc import ABCMeta, abstractmethod


__all__ = ["GlasgowDeviceError", "GlasgowDevice"]


class GlasgowDeviceError:
    """An exception raised on a communication error."""


class GlasgowDevice(metaclass=ABCMeta):
    pass
