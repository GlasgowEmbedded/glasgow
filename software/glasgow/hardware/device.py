import re
import sys
import enum
import time
import struct
import logging
import asyncio
import importlib.resources
from typing import Self, BinaryIO

import fx2
import fx2.format

from glasgow.support.logging import dump_hex
from glasgow.support.progress import Progress
if sys.platform == "emscripten":
    from glasgow.support.usb import webusb as usb
else:
    from glasgow.support.usb import libusb1 as usb
from .build_plan import GlasgowBuildPlan
from . import quirks


__all__ = ["GlasgowDevice", "FX2BootloaderDevice"]


logger = logging.getLogger(__name__)


VID_QIHW         = 0x20b7
PID_GLASGOW      = 0x9db1

CUR_API_LEVEL    = 0x07


class _Request(enum.IntEnum):
    # Board management
    WRITE_EEPROM    = 0x10
    READ_EEPROM     = 0x11
    # FPGA programming
    FPGA_LOAD_CFG   = 0x20
    FPGA_LOAD_NVM   = 0x21
    FPGA_STATUS     = 0x22
    FPGA_SET_REG    = 0x28
    FPGA_GET_REG    = 0x29
    # Port management
    SET_VSUPPLY     = 0x30
    GET_VSUPPLY     = 0x31
    SET_VLIMIT      = 0x32
    GET_VLIMIT      = 0x33
    SET_VALERT      = 0x34
    GET_VALERT      = 0x35
    SET_IALERT      = 0x36
    GET_IALERT      = 0x37
    GET_VSENSE      = 0x38
    GET_ISUPPLY     = 0x39
    SET_PULLS       = 0x3A
    GET_PULLS       = 0x3B
    GET_STATE       = 0x3C
    # Alert handling
    GET_ALERTS      = 0xA0
    CLR_ALERTS      = 0xA1
    # Internal use only
    TEST_LEDS       = 0xF0
    WRITE_SMBUS     = 0xF1
    READ_SMBUS      = 0xF2


class _Result(enum.IntEnum):
    ACK             = 0x00
    WAIT            = 0x01
    ERROR           = 0xff


class GlasgowPortAlerts(enum.Flag):
    UNDERVOLTAGE    = 1<<0
    OVERVOLTAGE     = 1<<1
    OVERCURRENT     = 1<<2

    ALL_POSSIBLE    = 0xff


class GlasgowDeviceError(Exception):
    """An exception raised on a communication or usage error."""


class GlasgowDevice:
    @classmethod
    def firmware_file(cls):
        return importlib.resources.files(__package__).joinpath("firmware-fx2.ihex")

    @classmethod
    def firmware_data(cls) -> list[tuple[int, bytes]]:
        with cls.firmware_file().open() as file:
            return fx2.format.input_data(file, fmt="ihex")

    @classmethod
    async def _enumerate_devices(cls, context: usb.Context) -> dict[str, usb.Device]:
        devices: list[usb.Device] = []
        devices_by_serial: dict[str, usb.Device] = {}

        def on_connected(device):
            if device.vendor_id == VID_QIHW and device.product_id == PID_GLASGOW:
                devices.append(device)
        context.add_connect_callback(on_connected)

        # No especially good way to handle the case where multiple devices are connected without
        # also making it very annoying to use a single device only.
        if len(await context.get_devices()) == 0:
            await context.request_device(VID_QIHW, PID_GLASGOW)
        devices.extend(await context.get_devices())

        while any(devices):
            device = devices.pop()

            if device.vendor_id == VID_QIHW and device.product_id == PID_GLASGOW:
                revision  = GlasgowDeviceConfig.decode_revision(device.version & 0xFF)
                api_level = device.version >> 8
            else:
                continue

            try:
                await device.open()
            except usb.ErrorAccess:
                logger.error("missing permissions to open device %s", device.location)
                continue
            if api_level == 0:
                logger.debug("found rev%s device without firmware", revision)
            elif api_level != CUR_API_LEVEL:
                try:
                    # Make sure nobody else is using the device, otherwise reloading the firmware
                    # will crash an existing session.
                    for interface in device.configuration.interfaces:
                        await device.claim_interface(interface.number)
                    logger.info("found rev%s device with API level %d (supported API level is %d)",
                        revision, api_level, CUR_API_LEVEL)
                    # Updating the firmware is not strictly required. However, re-enumeration tends
                    # to expose all kinds of issues related to hotplug (especially on Windows,
                    # where libusb does not listen to hotplug events) and the more you do it,
                    # the more likely it is to eventually cause misery.
                    logger.warning("please run `glasgow flash` to update firmware of device %s",
                        device.serial_number)
                except usb.ErrorBusy:
                    logger.debug("found busy rev%s device with unsupported API level %d",
                        revision, api_level)
                    await device.close()
                    continue
            else: # api_level == CUR_API_LEVEL
                if device.serial_number and device.serial_number not in devices_by_serial:
                    logger.debug("found rev%s device with serial %s",
                        revision, device.serial_number)
                    devices_by_serial[device.serial_number] = device
                await device.close()
                continue

            # If the device has no firmware or the firmware is too old (or, potentially, too new),
            # load the firmware that we know will work.
            logger.debug("loading firmware from %r to rev%s device",
                str(cls.firmware_file()), revision)
            await device.control_transfer_out(usb.RequestType.Vendor, usb.Recipient.Device,
                fx2.REQ_RAM, fx2.REG_CPUCS, 0, bytes([1]))
            for address, data in cls.firmware_data():
                for offset in range(0, len(data), 4096):
                    await device.control_transfer_out(
                        usb.RequestType.Vendor, usb.Recipient.Device,
                        fx2.REQ_RAM, address + offset, 0, bytes(data[offset:offset + 4096]))
            await device.control_transfer_out(usb.RequestType.Vendor, usb.Recipient.Device,
                fx2.REQ_RAM, fx2.REG_CPUCS, 0, bytes([0]))
            await device.close()

            RE_ENUMERATION_TIMEOUT = 10.0

            if context.has_hotplug_support:
                # Hotplug is available; process hotplug events for a while looking for the device
                # that re-enumerates after firmware upload. We expect two events (one detach and
                # one attach event), but allow for a bit more than that. (It is not possible to
                # wait for re-enumeration without some guesswork because USB lacks geographical
                # addressing.)
                logger.debug(f"waiting for re-enumeration (hotplug event)")
                devices_len = len(devices)
                deadline = time.time() + RE_ENUMERATION_TIMEOUT
                while deadline > time.time():
                    await asyncio.sleep(0.5)
                    if len(await context.get_devices()) == 0:
                        await context.request_device(VID_QIHW, PID_GLASGOW)
                    if devices_len < len(devices):
                        break # Found it!
                else:
                    logger.warning("device %s did not re-enumerate after firmware upload",
                        device.location)

            else:
                # No hotplug capability (most likely because we're running on Windows with an older
                # version of libusb); give the device a bit of time to re-enumerate. The device
                # disconnects from the bus for ~1 second, so we should wait a few times that
                # to allow for the variable OS and platform delays. Windows seems particularly slow
                # with a 5-second timeout being insufficient.
                logger.debug(f"waiting for re-enumeration (fixed delay)")
                await asyncio.sleep(RE_ENUMERATION_TIMEOUT)

                if len(await context.get_devices()) == 0:
                    await context.request_device(VID_QIHW, PID_GLASGOW)
                devices.extend(await context.get_devices())

        return devices_by_serial

    @classmethod
    async def enumerate(cls) -> list[str]:
        devices = await cls._enumerate_devices(usb.Context())
        return list(devices.keys())

    @classmethod
    async def find(cls, serial: str | None = None) -> "GlasgowDevice":
        usb_context = usb.Context()
        usb_devices = await cls._enumerate_devices(usb_context)
        if len(usb_devices) == 0:
            raise GlasgowDeviceError("device not found")
        elif serial is None:
            if len(usb_devices) > 1:
                raise GlasgowDeviceError(
                    f"found {len(usb_devices)} devices (with serial numbers "
                    f"{', '.join(usb_devices.keys())}), but a serial number is not specified")
            usb_device = next(iter(usb_devices.values()))
        else:
            if serial not in usb_devices:
                raise GlasgowDeviceError(f"device with serial number {serial} not found")
            usb_device = usb_devices[serial]

        device = GlasgowDevice(usb_context, usb_device)
        await device.open()
        return device

    def __init__(self, usb_context: usb.Context, usb_device: usb.Device):
        self.usb_context = usb_context
        self.usb_device = usb_device
        self.revision = GlasgowDeviceConfig.decode_revision(usb_device.version & 0xFF)
        self._mgmt_task: asyncio.Task | None = None
        self._mgmt_queue: dict[int, asyncio.Future[bytes]] = {}
        self._next_serial: int = 1

    async def open(self):
        await self.usb_device.open()
        if self.modified_design:
            logger.info("device with serial number %s was manufactured from modified design files",
                        self.serial)
            logger.info("the Glasgow Interface Explorer project is not responsible for "
                        "operation of this device")
        if self._mgmt_task is None:
            await self.usb_device.claim_interface(0)
            await self.usb_device.select_alternate_interface(0, 1)
            async def ep1_in_poller():
                while True:
                    packet = await self.usb_device.bulk_transfer_in(0x81, 64)
                    if len(packet) == 0:
                        logger.warning("USB: BULK EP1 IN ZLP (unexpected)")
                        continue
                    serial, payload = packet[0], packet[1:]
                    if handler := self._mgmt_queue.pop(serial, None):
                        logger.trace("USB: BULK EP1 IN data=<%s>", dump_hex(packet))
                        handler.set_result(payload)
                    else:
                        logger.warning("USB: BULK EP1 IN data=<%s> (unhandled)", dump_hex(packet))
            self._mgmt_task = asyncio.create_task(ep1_in_poller())

    async def close(self):
        if self._mgmt_task is not None:
            self._mgmt_task.cancel()
            await asyncio.wait([self._mgmt_task])
            self._mgmt_task = None
            await self.usb_device.release_interface(0)
        await self.usb_device.close()

    @property
    def serial(self):
        return self.usb_device.serial_number

    @property
    def modified_design(self):
        assert self.usb_device.product_name is not None
        is_modified = not self.usb_device.product_name.startswith("Glasgow Interface Explorer")
        if (self.usb_device.manufacturer_name == "1BitSquared" and
                self.usb_device.serial_number in quirks.modified_design_1b2_mar2024):
            is_modified = False # see quirks.py
        return is_modified

    @property
    def has_pulls(self):
        # C0 has fairly broken pulls, but we still try to support them.
        return self.revision >= "C0"

    @property
    def measures_current(self):
        return self.revision >= "C2"

    @property
    def all_ports(self) -> str:
        if self.revision >= "D0":
            return "ABCD"
        else:
            return "AB"

    async def _command_raw(self, payload: bytes | bytearray | memoryview) -> bytes:
        serial, self._next_serial = self._next_serial, (self._next_serial % 0xff) + 1
        packet = bytes([serial]) + payload
        future = self._mgmt_queue[serial] = asyncio.Future()
        logger.trace("USB: BULK EP1 OUT data=<%s>", dump_hex(packet))
        assert len(packet) <= 64
        await self.usb_device.bulk_transfer_out(0x01, packet)
        return await future

    async def _command_fmt(self, req_format: str, res_format: str, *req_params):
        req_packet = struct.pack(req_format, *req_params)
        res_packet = await self._command_raw(req_packet)
        res_params = struct.unpack(res_format, res_packet)
        return res_params

    async def bulk_read(self, endpoint: int, length: int) -> bytearray:
        logger.trace("USB: BULK EP%d IN length=%d (submit)", endpoint & 0x7f, length)
        try:
            data = await self.usb_device.bulk_transfer_in(endpoint, length)
            logger.trace("USB: BULK EP%d IN data=<%s> (completed)", endpoint & 0x7f, dump_hex(data))
        except asyncio.CancelledError:
            logger.trace("USB: BULK EP%d IN (cancelled)", endpoint & 0x7f)
            raise
        else:
            return data

    async def bulk_write(self, endpoint: int, data: bytes | bytearray | memoryview):
        if not isinstance(data, (bytes, bytearray)):
            data = bytearray(data)
        logger.trace("USB: BULK EP%d OUT data=<%s> (submit)", endpoint & 0x7f, dump_hex(data))
        try:
            await self.usb_device.bulk_transfer_out(endpoint, data)
            logger.trace("USB: BULK EP%d OUT (completed)", endpoint & 0x7f)
        except asyncio.CancelledError:
            logger.trace("USB: BULK EP%d OUT (cancelled)", endpoint & 0x7f)
            raise

    # Board management

    _EEPROM_CHUNK = 0x20

    async def read_eeprom(self, addr: int, length: int) -> bytearray:
        """Read ``length`` bytes at ``addr`` from FX2 EEPROM in ``chunk_size`` byte chunks."""
        logger.debug("reading FX2 EEPROM range %04x-%04x", addr, addr + length - 1)
        data = bytearray()
        while length > 0:
            chunk_size = min(length, self._EEPROM_CHUNK)
            result = await self._command_raw(struct.pack("<BHB",
                _Request.READ_EEPROM, addr, chunk_size))
            assert result[0] == _Result.ACK, f"unexpected result {result[0]:02x}"
            data   += result[1:]
            addr   += chunk_size
            length -= chunk_size
        return data

    async def write_eeprom(self, addr: int, data: bytes | bytearray):
        """Write ``data`` bytes at ``addr`` in FX2 EEPROM."""
        logger.debug("writing FX2 EEPROM range %04x-%04x", addr, addr + len(data) - 1)
        while len(data) > 0:
            # Make sure chunks never cross a 32-byte boundary.
            chunk_size = min(((addr | (self._EEPROM_CHUNK - 1)) + 1) - addr, self._EEPROM_CHUNK)
            result, = await self._command_raw(struct.pack("<BH",
                _Request.WRITE_EEPROM, addr) + data[:chunk_size])
            assert result == _Result.ACK, f"unexpected result {result:02x}"
            addr += chunk_size
            data  = data[chunk_size:]

    # FPGA programming

    async def bitstream_id(self) -> None | bytes:
        """Get bitstream ID for the bitstream currently running on the FPGA,
        or ``None`` if the FPGA does not have a bitstream.
        """
        result, _bitstream_size, bitstream_id = \
            await self._command_fmt("<B", "<BL8s", _Request.FPGA_STATUS)
        assert result == _Result.ACK, f"unexpected result {result:02x}"
        if re.match(rb"^\x00+$", bitstream_id):
            return None
        return bytes(bitstream_id)

    async def download_bitstream(self, bitstream: bytes, bitstream_id: bytes = b"\xff" * 8):
        """Download ``bitstream`` with ID ``bitstream_id`` to FPGA."""
        async def fpga_load():
            while True:
                # The FPGA_LAUNCH command serves as a synchronization point for EP2 writes.
                result, = await self._command_fmt("<BL8s", "<B",
                    _Request.FPGA_LOAD_CFG, len(bitstream), bitstream_id)
                if result == _Result.ACK:
                    break
                elif result == _Result.WAIT:
                    await asyncio.sleep(0.1)
                    continue
                else:
                    raise GlasgowDeviceError("FPGA configuration failed")
        async with (self.usb_device.with_interface(1, 3), # IFACE_EP2OUT, EP_MODE_CFG
                    asyncio.TaskGroup() as tg):
            tg.create_task(self.bulk_write(0x02, bitstream))
            tg.create_task(fpga_load())
        # Each bitstream has an I2C register at address 0, which is used to check that the FPGA
        # has configured properly and that the I2C bus function is intact. A small subset of
        # production devices manufactured by 1bitSquared fails this check.
        result, magic = await self._command_fmt("<BBB", "<B1s", _Request.FPGA_GET_REG, 0x00, 1)
        if result != _Result.ACK or magic != b"\xa5":
            raise GlasgowDeviceError(
                "FPGA health check failed; if you are using a newly manufactured device, "
                "ask the vendor of the device for return and replacement, else ask for support "
                "on community channels")

    async def download_plan(self, plan: GlasgowBuildPlan, *, reload: bool = False):
        if await self.bitstream_id() == plan.bitstream_id and not reload:
            logger.info("device already has bitstream ID %s", plan.bitstream_id.hex())
            return
        logger.info("generating bitstream ID %s", plan.bitstream_id.hex())
        await self.download_bitstream(await plan.get_bitstream(), plan.bitstream_id)

    async def download_prebuilt(self, plan: GlasgowBuildPlan, bitstream_file: BinaryIO):
        bitstream_file_id = bitstream_file.read(8)
        force_download = (bitstream_file_id == b"\xff" * 8)
        if force_download:
            logger.warning("prebuilt bitstream ID is all ones, forcing download")
        elif await self.bitstream_id() == plan.bitstream_id:
            logger.info("device already has bitstream ID %s", plan.bitstream_id.hex())
            return
        elif bitstream_file_id != plan.bitstream_id:
            logger.warning("prebuilt bitstream ID %s does not match design bitstream ID %s",
                           bitstream_file_id.hex(), plan.bitstream_id.hex())
        logger.info("downloading prebuilt bitstream ID %s from file %r",
                    plan.bitstream_id.hex(), bitstream_file.name)
        await self.download_bitstream(bitstream_file.read(), plan.bitstream_id)

    async def flash_bitstream(self, bitstream: bytes, bitstream_id: bytes = b"\xff" * 8):
        """Flash ``bitstream`` with ID ``bitstream_id`` to FPGA."""
        async def fpga_load():
            with Progress(total=len(bitstream), action="flashing", item="B") as progress:
                while True:
                    # The FPGA_LOAD_NVM command serves as a synchronization point for EP2 writes.
                    result, done_bytes = await self._command_fmt("<BL8s", "<BL",
                        _Request.FPGA_LOAD_NVM, len(bitstream), bitstream_id)
                    if result == _Result.ACK:
                        break
                    elif result == _Result.WAIT:
                        progress.advance(done_bytes - progress.done)
                        continue
                    else:
                        raise GlasgowDeviceError("FPGA bitstream flashing failed")
        async with (self.usb_device.with_interface(1, 4), # IFACE_EP2OUT, EP_MODE_NVM
                    asyncio.TaskGroup() as tg):
            tg.create_task(self.bulk_write(0x02, bitstream))
            tg.create_task(fpga_load())

    async def flash_plan(self, plan: GlasgowBuildPlan):
        logger.info("generating bitstream ID %s", plan.bitstream_id.hex())
        await self.flash_bitstream(await plan.get_bitstream(), plan.bitstream_id)

    async def write_register(self, addr: int, value: int, width: int = 1):
        """Write ``value`` to ``width``-byte FPGA register at ``addr``."""
        logger.trace("register %d write: %#04x", addr, value)
        result, = await self._command_fmt(f"<BB{width}s", "<B",
            _Request.FPGA_SET_REG, addr, value.to_bytes(width, byteorder="big"))
        if result != _Result.ACK:
            raise GlasgowDeviceError(f"failed to write register {addr:#04x}")

    async def read_register(self, addr: int, width: int = 1):
        """Read ``width``-byte FPGA register at ``addr``."""
        result, data = await self._command_fmt("<BBB", f"<B{width}s",
            _Request.FPGA_GET_REG, addr, width)
        if result != _Result.ACK:
            raise GlasgowDeviceError(f"failed to read register {addr:#04x}")
        value = int.from_bytes(data, byteorder="little")
        logger.trace("register %d read: %#04x", addr, value)
        return value

    # Port management

    def _iospec_to_mask(self, spec: str) -> int:
        mask = 0
        for port in spec:
            match port:
                case "A": mask |= 0x1
                case "B": mask |= 0x2
                case "C" if self.revision >= "D0": mask |= 0x4
                case "D" if self.revision >= "D0": mask |= 0x8
                case _:
                    raise GlasgowDeviceError(f"revision {self.revision} has no I/O port {port}")
        return mask

    def _iospec_to_index(self, port: str) -> int:
        if len(port) != 1:
            raise GlasgowDeviceError("exactly one I/O port may be specified for this operation")
        match port:
            case "A": return 0
            case "B": return 1
            case "C" if self.revision >= "D0": return 2
            case "D" if self.revision >= "D0": return 3
            case _:
                raise GlasgowDeviceError(f"revision {self.revision} has no I/O port {port}")

    async def set_voltage(self, spec: str, volts: float):
        """Set voltage on port(s) ``spec`` to ``volts``."""
        value = round(volts * 1000) # to mV
        result, = await self._command_fmt("<BB4H", "<B",
            _Request.SET_VSUPPLY, self._iospec_to_mask(spec),
            value, value, value, value)
        if result == _Result.ERROR:
            cause_list = []
            for port in spec:
                if (limit := await self.get_voltage_limit(port)) < volts:
                    cause_list.append(f"port {port} voltage limit is set to {limit:.4} V")
            causes = ""
            if cause_list:
                causes = f" ({', '.join(cause_list)})"
            raise GlasgowDeviceError(
                f"cannot set I/O port(s) {spec or '(none)'} supply voltage "
                f"to {float(volts):.4} V{causes}")
        assert result == _Result.ACK, f"unexpected result {result:02x}"

    async def get_voltage(self, spec: str) -> float:
        """Get supply supply voltage on port ``spec``, in volts."""
        result, _mask, va, vb, vc, vd = await self._command_fmt("<B", "<BB4H", _Request.GET_VSUPPLY)
        if result == _Result.ERROR:
            raise GlasgowDeviceError(f"cannot get I/O port {spec} supply voltage")
        assert result == _Result.ACK, f"unexpected result {result:02x}"
        return [va, vb, vc, vd][self._iospec_to_index(spec)] / 1000 # from mV

    async def set_voltage_limit(self, spec: str, volts: float):
        """Set supply voltage limit on port(s) ``spec`` to ``volts``.

        If ``volts`` is zero, limiting is removed. If voltage on this port is currently
        higher than the limit, it is clamped to the limit value.

        Supply voltage limit remains in place until it is removed, including across power cycles.
        """
        value = round(volts * 1000) # to mV
        result, = await self._command_fmt("<BB4H", "<B",
            _Request.SET_VLIMIT, self._iospec_to_mask(spec),
            value, value, value, value)
        if result == _Result.ERROR:
            raise GlasgowDeviceError(
                f"cannot set I/O port(s) {spec or '(none)'} supply voltage limit "
                f"to {float(volts):.4} V")
        assert result == _Result.ACK, f"unexpected result {result:02x}"

    async def get_voltage_limit(self, spec: str) -> float:
        """Get supply voltage limit on port ``spec``, in volts."""
        result, _mask, va, vb, vc, vd = await self._command_fmt("<B", "<BB4H", _Request.GET_VLIMIT)
        if result == _Result.ERROR:
            raise GlasgowDeviceError(f"cannot get I/O port {spec} supply voltage limit")
        assert result == _Result.ACK, f"unexpected result {result:02x}"
        return [va, vb, vc, vd][self._iospec_to_index(spec)] / 1000 # from mV

    async def measure_voltage(self, spec: str) -> float:
        """Measure voltage on port ``spec`` sense input, in volts.

        On revision C2 and newer (INA233 ADC) the code step size is 1.25 mV/LSB, on previous
        revisions the step size is 25.9 mV/LSB. Value is rounded to 1 mV.
        """
        result, _mask, va, vb, vc, vd = await self._command_fmt("<B", "<BB4H", _Request.GET_VSENSE)
        if result == _Result.ERROR:
            raise GlasgowDeviceError(f"cannot measure I/O port {spec} sense voltage")
        assert result == _Result.ACK, f"unexpected result {result:02x}"
        return [va, vb, vc, vd][self._iospec_to_index(spec)] / 1000 # from mV

    async def measure_current(self, spec: str) -> float:
        """Measure supply current on port ``spec``, in amperes.

        Only available on revision C2 and newer (INA233 ADC). The code step size is 10 uA/LSB, and
        the maximum representable value is 327.67 mA. Value is rounded to 10 uA.
        """
        result, _mask, va, vb, vc, vd = await self._command_fmt("<B", "<BB4h", _Request.GET_ISUPPLY)
        if result == _Result.ERROR:
            raise GlasgowDeviceError(f"cannot measure I/O port {spec} supply current")
        assert result == _Result.ACK, f"unexpected result {result:02x}"
        return abs([va, vb, vc, vd][self._iospec_to_index(spec)]) / 100000 # from 10 uA

    async def set_alert(self, spec: str, low_volts: float, high_volts: float):
        """Configure window (over/under) voltage alert on port ``spec`` sense input.

        Only available on revision C2 and newer (INA233 ADC). If either ``low_volts`` or
        ``high_volts`` is zero, that limit is not active.

        If voltage on the sense input is measured outside of the configured window, the voltage
        supply for the same port is turned off (immediately and without firmware action)
        The alert is disabled afterwards.
        """
        low_value  = round(low_volts  * 1000) # to mV
        high_value = round(high_volts * 1000) # to mV
        result, = await self._command_fmt("<BB8H", "<B",
            _Request.SET_VALERT, self._iospec_to_mask(spec),
            *(low_value, high_value) * 4)
        if result == _Result.ERROR:
            raise GlasgowDeviceError(
                f"cannot set I/O port(s) {spec or '(none)'} sense voltage alert "
                f"to {float(low_volts):.4}-{float(high_volts):.4} V")
        assert result == _Result.ACK, f"unexpected result {result:02x}"

    async def set_alert_tolerance(self, spec: str, volts: float, tolerance: float):
        """Configure window voltage alert on port ``spec`` sense input by center voltage and
        relative tolerance.

        For example, use :py:`device.set_alert_tolerance("A", 3.3, 0.05)` to disable supply on
        port A if voltage on its sense pin goes out of range of 3.3 V ±5%.
        """
        low_volts  = volts * (1 - tolerance)
        high_volts = volts * (1 + tolerance)
        await self.set_alert(spec, low_volts, high_volts)

    async def reset_alert(self, spec: str):
        """Disable window voltage alert on port ``spec`` sense input."""
        await self.set_alert(spec, 0.0, 0.0)

    async def get_alert(self, spec: str) -> tuple[float, float]:
        """Get references of window voltage alert on port ``spec`` sense input."""
        result, _mask, val, vah, vbl, vbh, vcl, vch, vdl, vdh = \
            await self._command_fmt("<B", "<BB8H", _Request.GET_VALERT)
        if result == _Result.ERROR:
            raise GlasgowDeviceError(f"cannot get I/O port {spec} sense voltage alert")
        assert result == _Result.ACK, f"unexpected result {result:02x}"
        vl, vh = [(val, vah), (vbl, vbh), (vcl, vch), (vdl, vdh)][self._iospec_to_index(spec)]
        return vl / 1000, vh / 1000 # from mV

    async def mirror_voltage(self, spec: str, sense: str | None = None, *,
                             tolerance: float = 0.05) -> float:
        if sense is None:
            sense = spec
        voltage = await self.measure_voltage(sense)
        if voltage < 1.8 * (1 - tolerance):
            raise GlasgowDeviceError(f"I/O port {spec} sense voltage ({voltage} V) too low")
        if voltage > 5.0 * (1 + tolerance):
            raise GlasgowDeviceError(f"I/O port {spec} sense voltage ({voltage} V) too high")
        await self.set_voltage(spec, voltage)
        await self.set_alert_tolerance(spec, voltage, tolerance=0.05)
        return voltage

    async def poll_alert(self):
        raise NotImplementedError("this function has been removed")

    async def set_trip_current(self, spec: str, amps: float):
        """Set supply trip current on port(s) ``spec`` to ``amps``.

        Only available on revision C2 and newer (INA233 ADC). If ``amps`` is zero, overcurrent
        tripping is disabled.

        If current on the LDO output is measured above the configured trip point, the voltage
        supply for the same port is turned off (immediately and without firmware action).
        The alert remains enabled afterwards.
        """
        value = round(amps * 100000) # to 10 uA
        result, = await self._command_fmt("<BB4H", "<B",
            _Request.SET_IALERT, self._iospec_to_mask(spec),
            value, value, value, value)
        if result == _Result.ERROR:
            raise GlasgowDeviceError(
                f"cannot set I/O port(s) {spec or '(none)'} supply trip current "
                f"to {float(amps):.6} A")
        assert result == _Result.ACK, f"unexpected result {result:02x}"

    async def get_trip_current(self, spec: str) -> float:
        """Get supply trip current on port ``spec``, in amperes."""
        result, _mask, ia, ib, ic, id = await self._command_fmt("<B", "<BB4H", _Request.GET_IALERT)
        if result == _Result.ERROR:
            raise GlasgowDeviceError(f"cannot get I/O port {spec} supply trip current")
        assert result == _Result.ACK, f"unexpected result {result:02x}"
        return [ia, ib, ic, id][self._iospec_to_index(spec)] / 100000 # from 10 uA

    async def get_faults(self, spec: str) -> GlasgowPortAlerts:
        """Get fault alerts on port ``spec``."""
        result, pa, pb, pc, pd, _fpga = await self._command_fmt("<B", "<B4BB", _Request.GET_ALERTS)
        if result == _Result.ERROR:
            raise GlasgowDeviceError(f"cannot get I/O port {spec} fault alerts")
        assert result == _Result.ACK, f"unexpected result {result:02x}"
        return GlasgowPortAlerts([pa, pb, pc, pd][self._iospec_to_index(spec)])

    async def clear_faults(self, spec: str, alerts = GlasgowPortAlerts.ALL_POSSIBLE):
        """Clear fault alerts on port(s) ``spec``."""
        mask = self._iospec_to_mask(spec)
        result, = await self._command_fmt("<B4BB", "<B",
            _Request.CLR_ALERTS, *(alerts.value if mask & (1<<i) else 0 for i in range(4)), 0)
        if result == _Result.ERROR:
            raise GlasgowDeviceError(f"cannot clear I/O port {spec} fault alerts")
        assert result == _Result.ACK, f"unexpected result {result:02x}"

    async def set_pulls(self, spec: str, low: set[int] = set(), high: set[int] = set(),
                        keep: set[int] = set()):
        """Configure pull resistors on port(s) ``spec``.

        Only available on revision C0 and newer.
        """
        assert self.has_pulls
        assert not {bit for bit in low | high if bit >= len(spec) * 8}

        mask = self._iospec_to_mask(spec)
        values = bytearray(b"\x00"*8)
        for index, port in enumerate(spec):
            port_index = self._iospec_to_index(port)
            for port_bit in range(0, 8):
                abs_index = index * 8 + port_bit
                if (abs_index in low) + (abs_index in high) + (abs_index in keep) > 1:
                    raise GlasgowDeviceError(f"pin {port}{port_bit} is configured ambiguously")
                if abs_index in low  or abs_index in keep:
                    values[(port_index<<1)|0] |= 1 << port_bit
                if abs_index in high or abs_index in keep:
                    values[(port_index<<1)|1] |= 1 << port_bit

        result, = await self._command_fmt("<BB8s", "<B",
            _Request.SET_PULLS, mask, values)
        if result == _Result.ERROR:
            raise GlasgowDeviceError(
                f"cannot set I/O port(s) {spec or '(none)'} pull resistors to "
                f"low={low or '{}'} high={high or '{}'}")
        assert result == _Result.ACK, f"unexpected result {result:02x}"

    async def get_state(self, spec: str) -> int:
        """Get pin states on port ``spec``.

        Only available on revision C2 and newer. Uses pull resistor GPIO expanders to observe pins.
        """
        assert self.has_pulls

        result, _mask, sa, sb, sc, sd = await self._command_fmt("<B", "<BB4B", _Request.GET_STATE)
        if result == _Result.ERROR:
            raise GlasgowDeviceError(f"cannot get I/O port {spec} pin state")
        assert result == _Result.ACK, f"unexpected result {result:02x}"
        return [sa, sb, sc, sd][self._iospec_to_index(spec)]

    # Internal use only

    async def _test_leds(self, enable: bool, state: int):
        result, = await self._command_fmt("<BBB", "<B", _Request.TEST_LEDS, enable, state)
        assert result == _Result.ACK, f"unexpected result {result:02x}"

    async def _write_smbus(self, addr: int, cmd: int, value: int):
        result, = await self._command_fmt("<BBBH", "<B",
            _Request.WRITE_SMBUS, addr, cmd, value)
        if result != _Result.ACK:
            raise GlasgowDeviceError(f"failed to write SMBus word {cmd:#04x} @ {addr:#09b}")
        assert result == _Result.ACK, f"unexpected result {result:02x}"

    async def _read_smbus(self, addr: int, cmd: int) -> int:
        result, value = await self._command_fmt("<BBB", "<BH",
            _Request.READ_SMBUS, addr, cmd)
        if result != _Result.ACK:
            raise GlasgowDeviceError(f"failed to read SMBus word {cmd:#04x} @ {addr:#09b}")
        assert result == _Result.ACK, f"unexpected result {result:02x}"
        return value


class GlasgowDeviceConfig:
    """Glasgow EEPROM configuration data.

    :ivar int size:
        Total size of configuration block (currently 64).

    :ivar str[1] revision:
        Revision letter, ``A``-``Z``.

    :ivar str[16] serial:
        Serial number, in ISO 8601 format.

    :ivar int bitstream_size:
        Size of bitstream flashed to ICE_MEM, or 0 if there isn't one.

    :ivar bytes[8] bitstream_id:
        Opaque string that uniquely identifies bitstream functionality,
        but not necessarily any particular routing and placement.
        Only meaningful if ``bitstream_size`` is set.

    :ivar int[2] voltage_limit:
        Maximum allowed I/O port voltage, in millivolts.

    :ivar str[22] manufacturer:
        Manufacturer string.

    :ivar bool modified_design:
        Modified from the original design files. This flag must be set if the PCBA has been modified
        from the design files published in https://github.com/GlasgowEmbedded/glasgow/ in any way
        except those exempted in https://glasgow-embedded.org/latest/build.html. It will be set when
        running `glasgow factory --using-modified-design-files=yes`.

    :ivar bool advertise_webusb:
        Whether to advertise WebUSB support. This will cause Chrome (including embedded Chromium)
        to display a notification linking to https://webusb.glasgow-embedded.org/.
    """

    _encoding = "<B16sI8sL4H22sb"
    assert struct.calcsize(_encoding) == 64

    _FLAG_MODIFIED_DESIGN  = 0b00000001
    _FLAG_API_LEVEL_GE_7   = 0b00000010
    _FLAG_ADVERTISE_WEBUSB = 0b00000100

    def __init__(self, revision: str, serial: str, bitstream_size: int = 0,
                 bitstream_id: bytes = b"\x00"*8, voltage_limit: list[int] | None = None,
                 manufacturer: str = "", modified_design: bool = False,
                 advertise_webusb: bool = False):
        self.revision         = revision
        self.serial           = serial
        self.bitstream_size   = bitstream_size
        self.bitstream_id     = bitstream_id
        self.voltage_limit    = [0, 0, 0, 0] if voltage_limit is None else voltage_limit
        self.manufacturer     = manufacturer
        self.modified_design  = bool(modified_design)
        self.advertise_webusb = bool(advertise_webusb)

    @staticmethod
    def encode_revision(string: str) -> int:
        """Encode the human readable revision to the revision byte as used in the firmware.

        The revision byte encodes the letter ``X`` and digit ``N`` in ``revXN`` in the high and
        low nibble respectively. The high nibble is the letter (1 means ``A``) and the low nibble
        is the digit.
        """
        if re.match(r"^[A-Z][0-9]$", string):
            major, minor = string
            return ((ord(major) - ord("A") + 1) << 4) | (ord(minor) - ord("0"))
        else:
            raise ValueError(f"invalid revision string {string!r}")

    @staticmethod
    def decode_revision(value: int) -> str:
        """Decode the revision byte as used in the firmware to the human readable revision.

        This inverts the transformation done by :meth:`encode_revision`.
        """
        major, minor = (value & 0xF0) >> 4, value & 0x0F
        if major == 0:
            return chr(ord("A") + minor - 1) + "0"
        elif minor in range(10):
            return chr(ord("A") + major - 1) + chr(ord("0") + minor)
        else:
            raise ValueError(f"invalid revision value {value:#04x}")

    @classmethod
    def size(cls):
        return struct.calcsize(cls._encoding)

    def encode(self) -> bytes:
        """Convert configuration to a byte array that can be loaded into memory or EEPROM."""
        return struct.pack(self._encoding,
                           self.encode_revision(self.revision),
                           self.serial.encode("ascii"),
                           self.bitstream_size,
                           self.bitstream_id,
                           0,
                           self.voltage_limit[0],
                           self.voltage_limit[1],
                           self.voltage_limit[2],
                           self.voltage_limit[3],
                           self.manufacturer.encode("ascii"),
                           self._FLAG_API_LEVEL_GE_7 |
                           (self._FLAG_MODIFIED_DESIGN if self.modified_design else 0) |
                           (self._FLAG_ADVERTISE_WEBUSB if self.advertise_webusb else 0))

    @classmethod
    def decode(cls, data: bytes) -> Self:
        """Parse configuration from a byte array loaded from memory or EEPROM.

        Returns :class:`GlasgowConfiguration` or raises :class:`ValueError` if
        the byte array does not contain a valid configuration.
        """
        if len(data) != cls.size():
            raise ValueError("Incorrect configuration length")

        voltage_limit = [0, 0, 0, 0]
        revision, serial, bitstream_size, bitstream_id, _unused, \
        voltage_limit[0], voltage_limit[1], voltage_limit[2], voltage_limit[3], \
        manufacturer, flags = \
            struct.unpack_from(cls._encoding, data, 0)
        if not flags & cls._FLAG_API_LEVEL_GE_7:
            bitstream_size = 0
            bitstream_id = b"\x00"*8
            voltage_limit[0] = voltage_limit[2]
            voltage_limit[1] = voltage_limit[3]
        return cls(cls.decode_revision(revision),
                   serial.decode("ascii"),
                   bitstream_size,
                   bitstream_id,
                   voltage_limit,
                   manufacturer.decode("ascii"),
                   flags & cls._FLAG_MODIFIED_DESIGN,
                   flags & cls._FLAG_ADVERTISE_WEBUSB)


class FX2BootloaderDevice:
    @classmethod
    def firmware_file(cls):
        return importlib.resources.files("fx2").joinpath("boot-cypress.ihex")

    @classmethod
    def firmware_data(cls) -> list[tuple[int, bytes]]:
        with cls.firmware_file().open() as file:
            return fx2.format.input_data(file, fmt="ihex")

    @classmethod
    async def find(cls, vid: int, pid: int) -> "FX2BootloaderDevice":
        usb_context = usb.Context()
        device_filter = lambda device: (device.vendor_id, device.product_id) == (vid, pid)
        usb_devices: list[usb.Device] = []
        usb_devices.extend(filter(device_filter, await usb_context.get_devices()))
        if len(usb_devices) == 0:
            await usb_context.request_device(vid, pid)
            usb_devices.extend(filter(device_filter, await usb_context.get_devices()))

        if len(usb_devices) == 0:
            raise GlasgowDeviceError(f"device {vid:#06x}:{pid:#06x} not found")
        elif len(usb_devices) > 1:
            raise GlasgowDeviceError(
                f"found {len(usb_devices)} devices (with {vid:#06x}:{pid:#06x})")

        device = FX2BootloaderDevice(usb_context, usb_devices[0])
        await device.open()
        return device

    def __init__(self, usb_context: usb.Context, usb_device: usb.Device):
        self.usb_context = usb_context
        self.usb_device = usb_device

    async def open(self):
        # usb.Device.open() is safe to call multiple times
        await self.usb_device.open()

    async def close(self):
        await self.usb_device.close()

    async def load_ram(self, chunks: list[tuple[int, bytes]]):
        """Write ``chunks``, a list of ``(address, data)`` pairs, to internal RAM,
        and start the CPU core.
        """
        # Put the FX2 into reset
        await self.usb_device.control_transfer_out(
            usb.RequestType.Vendor, usb.Recipient.Device, fx2.REQ_RAM, fx2.REG_CPUCS, 0, b"\x01")

        chunk_size = 0x1000
        for addr, data in chunks:
            for offset in range(0, len(data), chunk_size):
                await self.usb_device.control_transfer_out(
                    usb.RequestType.Vendor, usb.Recipient.Device,
                    fx2.REQ_RAM, addr + offset, 0, bytes(data[offset:offset + chunk_size]))

        # Take the FX2 out of reset
        await self.usb_device.control_transfer_out(
            usb.RequestType.Vendor, usb.Recipient.Device, fx2.REQ_RAM, fx2.REG_CPUCS, 0, b"\x00")

    async def read_boot_eeprom(self, addr: int, length: int, chunk_size: int = 0x1000) -> bytes:
        """Read ``length`` bytes at ``addr`` from boot EEPROM in ``chunk_size`` chunks.

        Requires the second stage bootloader or a compatible firmware.
        """
        data = bytearray()
        for offset in range(0, length, chunk_size):
            chunk_length = min(length - offset, chunk_size)
            data += await self.usb_device.control_transfer_in(
                usb.RequestType.Vendor, usb.Recipient.Device,
                fx2.REQ_EEPROM_DB, addr + offset, 0, chunk_length)
        return data

    async def write_boot_eeprom(self, addr: int, data: bytes, chunk_size: int = 0x1000):
        """Write ``data`` to ``addr`` in boot EEPROM in ``chunk_size`` chunks.

        Requires the second stage bootloader or a compatible firmware.
        """
        # 64 bytes
        page_size = 6
        await self.usb_device.control_transfer_out(
            usb.RequestType.Vendor, usb.Recipient.Device, fx2.REQ_PAGE_SIZE, page_size, 0, b"")

        for offset in range(0, len(data), chunk_size):
            await self.usb_device.control_transfer_out(
                usb.RequestType.Vendor, usb.Recipient.Device,
                fx2.REQ_EEPROM_DB, addr + offset, 0, bytes(data[offset:offset + chunk_size]))
