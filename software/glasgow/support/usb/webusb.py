from typing import Optional, Callable
import functools
import inspect
import js
import pyodide.ffi
import pyodide.ffi.wrappers

from . import *
from . import __all__ as _abstract_all


__all__ = _abstract_all + [
    "Context",
    "Device",
    "Configuration",
    "Interface",
    "AlternateInterface",
    "Endpoint",
]


def _map_result(result):
    match result.status:
        case "ok":
            return result
        case "stall":
            raise ErrorStall()
        case "babble":
            raise ErrorBabble()
        case _:
            assert False


def _map_exceptions(f):
    def map_error(error):
        match error.name:
            case "InvalidAccessError":
                raise ErrorNotSupported(error.message) from None
            case "NotFoundError":
                raise ErrorNotFound(error.message) from None
            case "SecurityError":
                raise ErrorAccess(error.message) from None
            case "DataError":
                raise ErrorOutOfMemory(error.message) from None
            case "InvalidStateError":
                raise ErrorNotOpen(error.message) from None
            case "NetworkError":
                raise ErrorDisconnected(error.message) from None
            case "AbortError":
                raise ErrorAborted(error.message) from None
            case _:
                raise Error(f"{error.name}: {error.message}") from error

    if inspect.iscoroutinefunction(f):
        @functools.wraps(f)
        async def wrapper(*args, **kwargs):
            try:
                return await f(*args, **kwargs)
            except pyodide.ffi.JsException as err:
                map_error(err)
    else:
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except pyodide.ffi.JsException as err:
                map_error(err)
    return wrapper


class Context(AbstractContext):
    def __init__(self):
        self._impl = js.navigator.usb
        self._on_connect = []
        self._on_disconnect = []

        pyodide.ffi.wrappers.add_event_listener(
            self._impl, "connect", self._process_connect_event)
        pyodide.ffi.wrappers.add_event_listener(
            self._impl, "disconnect", self._process_disconnect_event)

    @_map_exceptions
    async def request_device(self, vendor_id: int, product_id: int):
        await self._impl.requestDevice({"filters": [
            {"vendorId": vendor_id, "productId": product_id}
        ]})

    @_map_exceptions
    async def get_devices(self) -> list['Device']:
        return [Device(device) for device in await self._impl.getDevices()]

    @property
    def has_hotplug_support(self) -> bool:
        return True

    def add_connect_callback(self, callback: Callable[['Device'], None]):
        self._on_connect.append(callback)

    def _process_connect_event(self, event):
        for callback in self._on_connect:
            callback(Device(event.device))

    def add_disconnect_callback(self, callback: Callable[['Device'], None]):
        self._on_disconnect.append(callback)

    def _process_disconnect_event(self, event):
        for callback in self._on_disconnect:
            callback(Device(event.device))


class Device(AbstractDevice):
    def __init__(self, _impl):
        self._impl = _impl

    @property
    def vendor_id(self) -> int:
        return self._impl.vendorId

    @property
    def product_id(self) -> int:
        return self._impl.productId

    @property
    def manufacturer_name(self) -> Optional[str]:
        return self._impl.manufacturerName

    @property
    def product_name(self) -> Optional[str]:
        return self._impl.productName

    @property
    def serial_number(self) -> Optional[str]:
        return self._impl.serialNumber

    @property
    def version(self) -> int:
        return (
            self._impl.deviceVersionMajor << 8 |
            self._impl.deviceVersionMinor << 4 |
            self._impl.deviceVersionSubminor
        )

    @property
    def location(self) -> str:
        return "<webusb>"

    @property
    def configuration(self) -> 'Configuration':
        return Configuration(self._impl.configuration)

    @property
    def configurations(self) -> list['Configuration']:
        return [Configuration(configuration) for configuration in self._impl.configurations]

    @_map_exceptions
    async def open(self):
        await self._impl.open()

    @_map_exceptions
    async def close(self):
        await self._impl.close()

    @_map_exceptions
    async def select_configuration(self, configuration: int):
        await self._impl.selectConfiguration(configuration)

    @_map_exceptions
    async def select_alternate_interface(self, interface: int, setting: int):
        await self._impl.selectAlternateInterface(interface, setting)

    @_map_exceptions
    async def claim_interface(self, interface: int):
        await self._impl.claimInterface(interface)

    @_map_exceptions
    async def release_interface(self, interface: int):
        await self._impl.releaseInterface(interface)

    @_map_exceptions
    async def control_transfer_in(self, request_type: RequestType, recipient: Recipient,
                                  request: int, value: int, index: int, length: int) -> memoryview:
        return _map_result(await self._impl.controlTransferIn({
            "requestType": request_type.value,
            "recipient": recipient.value,
            "request": request,
            "value": value,
            "index": index,
        }, length)).data.to_py()

    @_map_exceptions
    async def control_transfer_out(self, request_type: RequestType, recipient: Recipient,
                                   request: int, value: int, index: int, data: bytes | bytearray):
        await self._impl.controlTransferOut({
            "requestType": request_type.value,
            "recipient": recipient.value,
            "request": request,
            "value": value,
            "index": index,
        }, pyodide.ffi.to_js(data).buffer)

    @_map_exceptions
    async def bulk_transfer_in(self, endpoint: int, length: int) -> memoryview:
        return _map_result(await self._impl.transferIn(endpoint, length)).data.to_py()

    @_map_exceptions
    async def bulk_transfer_out(self, endpoint: int, data: bytes | bytearray):
        await self._impl.transferOut(endpoint, pyodide.ffi.to_js(data).buffer)


class Configuration(AbstractConfiguration):
    def __init__(self, _impl):
        self._impl = _impl

    @property
    def value(self) -> int:
        return self._impl.configurationValue

    @property
    def interfaces(self) -> list['Interface']:
        return [Interface(interface) for interface in self._impl.interfaces]


class Interface(AbstractInterface):
    def __init__(self, _impl):
        self._impl = _impl

    @property
    def number(self) -> int:
        return self._impl.interfaceNumber

    # @property
    # def alternate(self) -> 'AlternateInterface':
    #     return AlternateInterface(self._impl.alternate)

    @property
    def alternates(self) -> list['AlternateInterface']:
        return [AlternateInterface(alternate) for alternate in self._impl.alternates]


class AlternateInterface(AbstractAlternateInterface):
    def __init__(self, _impl):
        self._impl = _impl

    @property
    def setting(self) -> int:
        return self._impl.alternateSetting

    @property
    def endpoints(self) -> list['Endpoint']:
        return [Endpoint(endpoint) for endpoint in self._impl.endpoints]


class Endpoint(AbstractEndpoint):
    def __init__(self, _impl):
        self._impl = _impl

    @property
    def number(self) -> int:
        return self._impl.endpointNumber

    @property
    def direction(self) -> Direction:
        return Direction(self._impl.direction)

    @property
    def type(self) -> EndpointType:
        return EndpointType(self._impl.type)

    @property
    def packet_size(self) -> int:
        return self._impl.packetSize
