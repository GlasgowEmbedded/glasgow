from typing import Optional, Callable
import functools
import threading
import inspect
import asyncio

import usb1

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


def _map_exceptions(f):
    def map_error(error):
        match error:
            case usb1.USBErrorInvalidParam() | usb1.USBErrorNotSupported():
                raise ErrorNotSupported() from None
            case usb1.USBErrorNotFound():
                raise ErrorNotFound() from None
            case usb1.USBErrorAccess():
                raise ErrorAccess() from None
            case usb1.USBErrorBusy():
                raise ErrorBusy() from None
            case usb1.USBErrorNoMem():
                raise ErrorOutOfMemory() from None
            case usb1.USBErrorNoDevice():
                raise ErrorDisconnected() from None
            case usb1.USBErrorPipe():
                raise ErrorStall() from None
            case usb1.USBErrorOverflow():
                raise ErrorBabble() from None
            case usb1.USBErrorInterrupted():
                raise ErrorAborted() from None
            case _:
                raise Error(str(error)) from error

    if inspect.iscoroutinefunction(f):
        @functools.wraps(f)
        async def wrapper(*args, **kwargs):
            try:
                return await f(*args, **kwargs)
            except usb1.USBError as err:
                map_error(err)
    else:
        @functools.wraps(f)
        def wrapper(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except usb1.USBError as err:
                map_error(err)
    return wrapper


def _map_request_type(request_type: RequestType) -> int:
    match request_type:
        case RequestType.Standard:
            return usb1.REQUEST_TYPE_STANDARD
        case RequestType.Class:
            return usb1.REQUEST_TYPE_CLASS
        case RequestType.Vendor:
            return usb1.REQUEST_TYPE_VENDOR


def _map_recipient(recipient: Recipient) -> int:
    match recipient:
        case Recipient.Device:
            return usb1.RECIPIENT_DEVICE
        case Recipient.Interface:
            return usb1.RECIPIENT_INTERFACE
        case Recipient.Endpoint:
            return usb1.RECIPIENT_ENDPOINT
        case Recipient.Other:
            return usb1.RECIPIENT_OTHER


class Context(AbstractContext):
    class _PollerThread(threading.Thread):
        def __init__(self, _impl: usb1.USBContext):
            super().__init__()

            self._impl = _impl
            self._done = False

        @property
        def done(self) -> bool:
            return self._done

        def run(self):
            # The poller thread spends most of its life in blocking `handleEvents()` calls and this
            # can cause issues during interpreter shutdown. If it were a daemon thread (it isn't)
            # then it would be instantly killed on interpreter shutdown and any locks it took could
            # block some libusb1 objects being destroyed as their Python counterparts are garbage
            # collected. Since it is not a daemon thread, `threading._shutdown()` (that is called
            # by e.g. `exit()`) will join it, and so it must terminate during threading shutdown.
            # Note that `atexit.register` is not enough as those callbacks are called after
            # threading shutdown, and past the point where a deadlock would happen.
            threading._register_atexit(self.stop)
            while not self._done:
                self._impl.handleEvents()

        def stop(self):
            self._done = True
            self._impl.interruptEventHandler()
            self.join()

    def __init__(self):
        self._impl = usb1.USBContext()
        self._poller = self._PollerThread(self._impl)
        self._on_connect = []
        self._on_disconnect = []

        if self.has_hotplug_support:
            self._impl.hotplugRegisterCallback(self._process_hotplug_event)
        self._poller.start()

    async def request_device(self, vendor_id: int, product_id: int):
        pass # not necessary on libusb1

    @_map_exceptions
    async def get_devices(self) -> list["Device"]:
        return [
            Device(self._poller, device)
            for device in self._impl.getDeviceIterator(skip_on_error=True)
        ]

    @property
    def has_hotplug_support(self) -> bool:
        return self._impl.hasCapability(usb1.CAP_HAS_HOTPLUG)

    def add_connect_callback(self, callback: Callable[["Device"], None]):
        self._on_connect.append(callback)

    def add_disconnect_callback(self, callback: Callable[["Device"], None]):
        self._on_disconnect.append(callback)

    def _process_hotplug_event(self, _impl, impl_device, event):
        match event:
            case usb1.HOTPLUG_EVENT_DEVICE_ARRIVED:
                for callback in self._on_connect:
                    callback(Device(self._poller, impl_device))

            case usb1.HOTPLUG_EVENT_DEVICE_LEFT:
                for callback in self._on_disconnect:
                    callback(Device(self._poller, impl_device))

    def __del__(self):
        self._poller.stop()


class Device(AbstractDevice):
    def __init__(self, _poller: Context._PollerThread, _impl_device: usb1.USBDevice):
        self._poller = _poller
        self._impl_device = _impl_device
        self._impl_handle: Optional[usb1.USBDeviceHandle] = None

        self._manufacturer_name: Optional[str] = None
        self._product_name: Optional[str] = None
        self._serial_number: Optional[str] = None

    @property
    def _ensure_open(self) -> usb1.USBDeviceHandle:
        if self._impl_handle is None:
            raise ErrorNotOpen()
        return self._impl_handle

    @property
    @_map_exceptions
    def vendor_id(self) -> int:
        return self._impl_device.getVendorID()

    @property
    @_map_exceptions
    def product_id(self) -> int:
        return self._impl_device.getProductID()

    @property
    @_map_exceptions
    def manufacturer_name(self) -> Optional[str]:
        if self._manufacturer_name is None:
            self._manufacturer_name = self._ensure_open.getASCIIStringDescriptor(
                self._impl_device.getManufacturerDescriptor())
        return self._manufacturer_name

    @property
    @_map_exceptions
    def product_name(self) -> Optional[str]:
        if self._product_name is None:
            self._product_name = self._ensure_open.getASCIIStringDescriptor(
                self._impl_device.getProductDescriptor())
        return self._product_name

    @property
    @_map_exceptions
    def serial_number(self) -> Optional[str]:
        if self._serial_number is None:
            self._serial_number = self._ensure_open.getASCIIStringDescriptor(
                self._impl_device.getSerialNumberDescriptor())
        return self._serial_number

    @property
    @_map_exceptions
    def version(self) -> int:
        return self._impl_device.getbcdDevice()

    @property
    @_map_exceptions
    def location(self) -> str:
        return f"{self._impl_device.getBusNumber():03d}/{self._impl_device.getDeviceAddress():03d}"

    @property
    @_map_exceptions
    def configuration(self) -> "Configuration":
        for configuration in self._impl_device.iterConfigurations():
            if configuration.getConfigurationValue() == self._ensure_open.getConfiguration():
                return Configuration(configuration)
        else:
            assert False

    @property
    @_map_exceptions
    def configurations(self) -> list["Configuration"]:
        return [
            Configuration(configuration)
            for configuration in self._impl_device.iterConfigurations()
        ]

    @_map_exceptions
    async def open(self):
        if self._impl_handle is None:
            self._impl_handle = self._impl_device.open()
            try:
                self._impl_handle.setAutoDetachKernelDriver(True)
            except usb1.USBErrorNotSupported:
                pass

    @_map_exceptions
    async def close(self):
        if self._impl_handle is not None:
            self._impl_handle.close()
            self._impl_handle = None

    @_map_exceptions
    async def select_configuration(self, configuration: int):
        self._ensure_open.setConfiguration(configuration)

    @_map_exceptions
    async def select_alternate_interface(self, interface: int, setting: int):
        self._ensure_open.setInterfaceAltSetting(interface, setting)

    @_map_exceptions
    async def claim_interface(self, interface: int):
        self._ensure_open.claimInterface(interface)

    @_map_exceptions
    async def release_interface(self, interface: int):
        self._ensure_open.releaseInterface(interface)

    @_map_exceptions
    async def _perform_transfer(self, direction: Direction, setup) -> bytearray | None:
        # libusb transfer cancellation is asynchronous, and moreover, it is necessary to wait for
        # all transfers to finish cancelling before closing the event loop. To do this, use
        # separate futures for result and cancel.
        cancel_future = asyncio.Future()
        result_future = asyncio.Future()

        transfer = self._ensure_open.getTransfer()
        setup(transfer)

        def callback(transfer: usb1.USBTransfer):
            if self._poller.done:
                return # shutting down
            if transfer.isSubmitted():
                return # transfer not completed

            match transfer.getStatus():
                case usb1.TRANSFER_CANCELLED:
                    cancel_future.set_result(None)
                case _ if result_future.cancelled():
                    pass
                case usb1.TRANSFER_COMPLETED if direction == Direction.In:
                    result_future.set_result(transfer.getBuffer()[:transfer.getActualLength()])
                case usb1.TRANSFER_COMPLETED if direction == Direction.Out:
                    result_future.set_result(None)
                case usb1.TRANSFER_STALL:
                    result_future.set_exception(ErrorStall())
                case usb1.TRANSFER_NO_DEVICE:
                    result_future.set_exception(ErrorDisconnected())
                case status:
                    result_future.set_exception(Error(
                        f"libusb1 status: {usb1.libusb1.libusb_transfer_status(status)}"))

        loop = asyncio.get_event_loop()
        transfer.setCallback(lambda transfer: loop.call_soon_threadsafe(callback, transfer))
        transfer.submit()
        try:
            return await result_future
        finally:
            if result_future.cancelled():
                try:
                    transfer.cancel()
                    await cancel_future
                except usb1.USBErrorNotFound:
                    pass # already finished, one way or another

    async def control_transfer_in(self, request_type: RequestType, recipient: Recipient,
                                  request: int, value: int, index: int, length: int) -> bytearray:
        def setup(transfer):
            transfer.setControl(
                _map_request_type(request_type) | _map_recipient(recipient) | usb1.ENDPOINT_IN,
                request, value, index, length)
        return memoryview(await self._perform_transfer(Direction.In, setup))

    async def control_transfer_out(self, request_type: RequestType, recipient: Recipient,
                                   request: int, value: int, index: int, data: bytearray):
        def setup(transfer):
            transfer.setControl(
                _map_request_type(request_type) | _map_recipient(recipient) | usb1.ENDPOINT_OUT,
                request, value, index, data)
        await self._perform_transfer(Direction.Out, setup)

    async def bulk_transfer_in(self, endpoint: int, length: int) -> bytearray:
        def setup(transfer):
            transfer.setBulk(endpoint, length)
        return memoryview(await self._perform_transfer(Direction.In, setup))

    async def bulk_transfer_out(self, endpoint: int, data: bytearray):
        def setup(transfer):
            transfer.setBulk(endpoint, data)
        await self._perform_transfer(Direction.Out, setup)


class Configuration(AbstractConfiguration):
    def __init__(self, _impl: usb1.USBConfiguration):
        self._impl = _impl

    @property
    def value(self) -> int:
        return self._impl.getConfigurationValue()

    @property
    def interfaces(self) -> list["Interface"]:
        return [
            Interface(number, interface)
            for number, interface in enumerate(self._impl.iterInterfaces())
        ]


class Interface(AbstractInterface):
    def __init__(self, _number: int, _impl: usb1.USBInterface):
        self._number = _number
        self._impl = _impl

    @property
    def number(self) -> int:
        return self._number

    @property
    def alternates(self) -> list["AlternateInterface"]:
        return [
            AlternateInterface(alternate)
            for alternate in self._impl.iterSettings()
        ]


class AlternateInterface(AbstractAlternateInterface):
    def __init__(self, _impl: usb1.USBInterfaceSetting):
        self._impl = _impl

    @property
    def setting(self) -> int:
        return self._impl.getAlternateSetting()

    @property
    def endpoints(self) -> list["Endpoint"]:
        return [
            Endpoint(endpoint)
            for endpoint in self._impl.iterEndpoints()
        ]


class Endpoint(AbstractEndpoint):
    def __init__(self, _impl: usb1.USBEndpoint):
        self._impl = _impl

    @property
    def number(self) -> int:
        return self._impl.getAddress()

    @property
    def direction(self) -> Direction:
        if self._impl.getAddress() & usb1.ENDPOINT_IN:
            return Direction.In
        else:
            return Direction.Out

    @property
    def type(self) -> EndpointType:
        match self._impl.getAttributes() & usb1.TRANSFER_TYPE_MASK:
            case usb1.TRANSFER_TYPE_BULK:
                return EndpointType.Bulk
            case usb1.TRANSFER_TYPE_INTERRUPT:
                return EndpointType.Interrupt
            case usb1.TRANSFER_TYPE_ISOCHRONOUS:
                return EndpointType.Isochronous
            case _:
                raise NotImplementedError(f"bmAttributes={self._impl.getAttributes():#04x}")

    @property
    def packet_size(self) -> int:
        return self._impl.getMaxPacketSize()
