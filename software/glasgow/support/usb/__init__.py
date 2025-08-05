"""Abstract USB backend interface."""

from typing import Optional, Callable
from abc import ABCMeta, abstractmethod
import enum


__all__ = [
    "RequestType",
    "Recipient",
    "Direction",
    "EndpointType",
    "Error",
    "ErrorNotSupported",
    "ErrorNotFound",
    "ErrorNotOpen",
    "ErrorAccess",
    "ErrorBusy",
    "ErrorOutOfMemory",
    "ErrorDisconnected",
    "ErrorStall",
    "ErrorBabble",
    "ErrorAborted",
    "AbstractContext",
    "AbstractDevice",
    "AbstractConfiguration",
    "AbstractInterface",
    "AbstractAlternateInterface",
    "AbstractEndpoint",
]


class RequestType(enum.Enum):
    Standard = "standard"
    Class = "class"
    Vendor = "vendor"


class Recipient(enum.Enum):
    Device = "device"
    Interface = "interface"
    Endpoint = "endpoint"
    Other = "other"


class Direction(enum.Enum):
    In = "in"
    Out = "out"


class EndpointType(enum.Enum):
    Bulk = "bulk"
    Interrupt = "interrupt"
    Isochronous = "isochronous"


class Error(Exception):
    pass


class ErrorNotSupported(Error):
    pass


class ErrorNotFound(Error):
    pass


class ErrorNotOpen(Error):
    pass


class ErrorAccess(Error):
    pass


class ErrorBusy(Error):
    pass


class ErrorOutOfMemory(Error):
    pass


class ErrorDisconnected(Error):
    pass


class ErrorStall(Error):
    pass


class ErrorBabble(Error):
    pass


class ErrorAborted(Error):
    pass


class AbstractContext(metaclass=ABCMeta):
    @abstractmethod
    async def request_device(self, vendor_id: int, product_id: int):
        pass

    @abstractmethod
    async def get_devices(self) -> list["AbstractDevice"]:
        pass

    @property
    @abstractmethod
    def has_hotplug_support(self) -> bool:
        pass

    @abstractmethod
    def add_connect_callback(self, callback: Callable[["AbstractDevice"], None]):
        pass

    @abstractmethod
    def add_disconnect_callback(self, callback: Callable[["AbstractDevice"], None]):
        pass


class AbstractDevice(metaclass=ABCMeta):
    @property
    @abstractmethod
    def vendor_id(self) -> int:
        pass

    @property
    @abstractmethod
    def product_id(self) -> int:
        pass

    @property
    @abstractmethod
    def manufacturer_name(self) -> Optional[str]:
        pass

    @property
    @abstractmethod
    def product_name(self) -> Optional[str]:
        pass

    @property
    @abstractmethod
    def serial_number(self) -> Optional[str]:
        pass

    @property
    @abstractmethod
    def version(self) -> int:
        pass

    @property
    @abstractmethod
    def location(self) -> str:
        pass

    @property
    @abstractmethod
    def configuration(self) -> "AbstractConfiguration":
        pass

    @property
    @abstractmethod
    def configurations(self) -> list["AbstractConfiguration"]:
        pass

    @abstractmethod
    async def open(self):
        pass

    @abstractmethod
    async def close(self):
        pass

    @abstractmethod
    async def select_configuration(self, configuration: int):
        pass

    @abstractmethod
    async def select_alternate_interface(self, interface: int, setting: int):
        pass

    @abstractmethod
    async def claim_interface(self, interface: int):
        pass

    @abstractmethod
    async def release_interface(self, interface: int):
        pass

    @abstractmethod
    async def control_transfer_in(self, request_type: RequestType, recipient: Recipient,
                                  request: int, value: int, index: int, length: int) -> memoryview:
        pass

    @abstractmethod
    async def control_transfer_out(self, request_type: RequestType, recipient: Recipient,
                                   request: int, value: int, index: int, data: bytes | bytearray):
        pass

    @abstractmethod
    async def bulk_transfer_in(self, endpoint: int, length: int) -> memoryview:
        pass

    @abstractmethod
    async def bulk_transfer_out(self, endpoint: int, data: bytes | bytearray):
        pass


class AbstractConfiguration(metaclass=ABCMeta):
    @property
    @abstractmethod
    def value(self) -> int:
        pass

    @property
    @abstractmethod
    def interfaces(self) -> list["AbstractInterface"]:
        pass


class AbstractInterface(metaclass=ABCMeta):
    @property
    @abstractmethod
    def number(self) -> int:
        pass

    # @property
    # @abstractmethod
    # def alternate(self) -> 'AbstractAlternateInterface':
    #     pass

    @property
    @abstractmethod
    def alternates(self) -> list["AbstractAlternateInterface"]:
        pass


class AbstractAlternateInterface(metaclass=ABCMeta):
    @property
    @abstractmethod
    def setting(self) -> int:
        pass

    @property
    @abstractmethod
    def endpoints(self) -> list["AbstractEndpoint"]:
        pass


class AbstractEndpoint(metaclass=ABCMeta):
    @property
    @abstractmethod
    def number(self) -> int:
        pass

    @property
    @abstractmethod
    def direction(self) -> Direction:
        pass

    @property
    @abstractmethod
    def type(self) -> EndpointType:
        pass

    @property
    @abstractmethod
    def packet_size(self) -> int:
        pass
