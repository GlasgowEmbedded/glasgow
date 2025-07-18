from typing import Optional
import re
import sys
import time
import struct
import logging
import asyncio
import importlib.resources

import usb1
from fx2 import REQ_RAM, REG_CPUCS
from fx2.format import input_data

from ..support.logging import dump_hex
if sys.platform == "emscripten":
    from ..support.usb import webusb as usb
else:
    from ..support.usb import libusb1 as usb
from . import quirks


__all__ = ["GlasgowDevice"]


logger = logging.getLogger(__name__)


VID_QIHW         = 0x20b7
PID_GLASGOW      = 0x9db1

CUR_API_LEVEL    = 0x04

REQ_EEPROM       = 0x10
REQ_FPGA_CFG     = 0x11
REQ_STATUS       = 0x12
REQ_REGISTER     = 0x13
REQ_IO_VOLT      = 0x14
REQ_SENSE_VOLT   = 0x15
REQ_ALERT_VOLT   = 0x16
REQ_POLL_ALERT   = 0x17
REQ_BITSTREAM_ID = 0x18
REQ_IOBUF_ENABLE = 0x19
REQ_LIMIT_VOLT   = 0x1A
REQ_PULL         = 0x1B
REQ_TEST_LEDS    = 0x1C

ST_ERROR         = 1<<0
ST_FPGA_RDY      = 1<<1
ST_ALERT         = 1<<2

IO_BUF_A         = 1<<0
IO_BUF_B         = 1<<1


class GlasgowDeviceError(Exception):
    """An exception raised on a communication error."""


class GlasgowDevice:
    @classmethod
    def firmware_file(cls):
        return importlib.resources.files(__package__).joinpath("firmware.ihex")

    @classmethod
    def firmware_data(cls):
        with cls.firmware_file().open() as file:
            return input_data(file, fmt="ihex")

    @classmethod
    async def _enumerate_devices(cls, context: usb.Context):
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
                if device.serial_number not in devices_by_serial:
                    logger.debug("found rev%s device with serial %s",
                        revision, device.serial_number)
                    devices_by_serial[device.serial_number] = device
                await device.close()
                continue

            # If the device has no firmware or the firmware is too old (or, potentially, too new),
            # load the firmware that we know will work.
            logger.debug("loading firmware from %r to rev%s device",
                str(cls.firmware_file()), revision)
            await device.control_transfer_out(
                usb.RequestType.Vendor, usb.Recipient.Device, REQ_RAM, REG_CPUCS, 0, bytes([1]))
            for address, data in cls.firmware_data():
                for offset in range(0, len(data), 4096):
                    await device.control_transfer_out(
                        usb.RequestType.Vendor, usb.Recipient.Device,
                        REQ_RAM, address, 0, bytes(data[offset:offset + 4096]))
            await device.control_transfer_out(
                usb.RequestType.Vendor, usb.Recipient.Device, REQ_RAM, REG_CPUCS, 0, bytes([0]))
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
    async def find(cls, serial: Optional[str] = None) -> 'GlasgowDevice':
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

    async def open(self):
        await self.usb_device.open()
        if self.modified_design:
            logger.info("device with serial number %s was manufactured from modified design files",
                        self.serial)
            logger.info("the Glasgow Interface Explorer project is not responsible for "
                        "operation of this device")

    async def close(self):
        await self.usb_device.close()

    @property
    def serial(self):
        return self.usb_device.serial_number

    @property
    def modified_design(self):
        is_modified = not self.usb_device.product_name.startswith("Glasgow Interface Explorer")
        if (self.usb_device.manufacturer_name == "1BitSquared" and
                self.usb_device.serial_number in quirks.modified_design_1b2_mar2024):
            is_modified = False # see quirks.py
        return is_modified

    async def control_read(self, request, value, index, length):
        logger.trace("USB: CONTROL IN request=%#04x value=%#06x index=%#06x length=%d (submit)",
                     request, value, index, length)
        try:
            data = await self.usb_device.control_transfer_in(
                usb.RequestType.Vendor, usb.Recipient.Device, request, value, index, length)
            logger.trace("USB: CONTROL IN request=%#04x data=<%s> (completed)",
                request, dump_hex(data))
            return data
        except asyncio.CancelledError:
            logger.trace("USB: CONTROL IN request=%#04x (cancelled)", request)
            raise

    async def control_write(self, request, value, index, data):
        if not isinstance(data, (bytes, bytearray)):
            data = bytearray(data)
        logger.trace("USB: CONTROL OUT request=%#04x value=%#06x index=%#06x data=<%s> (submit)",
                     request, value, index, dump_hex(data))
        try:
            await self.usb_device.control_transfer_out(
                usb.RequestType.Vendor, usb.Recipient.Device, request, value, index, data)
            logger.trace("USB: CONTROL OUT request=%#04x (completed)", request)
        except asyncio.CancelledError:
            logger.trace("USB: CONTROL OUT request=%#04x (cancelled)", request)
            raise

    async def bulk_read(self, endpoint, length):
        logger.trace("USB: BULK EP%d IN length=%d (submit)", endpoint & 0x7f, length)
        try:
            data = await self.usb_device.bulk_transfer_in(endpoint, length)
            logger.trace("USB: BULK EP%d IN data=<%s> (completed)", endpoint & 0x7f, dump_hex(data))
            return data
        except asyncio.CancelledError:
            logger.trace("USB: BULK EP%d IN (cancelled)", endpoint & 0x7f)
            raise

    async def bulk_write(self, endpoint, data):
        if not isinstance(data, (bytes, bytearray)):
            data = bytearray(data)
        logger.trace("USB: BULK EP%d OUT data=<%s> (submit)", endpoint & 0x7f, dump_hex(data))
        try:
            await self.usb_device.bulk_transfer_out(endpoint, data)
            logger.trace("USB: BULK EP%d OUT (completed)", endpoint & 0x7f)
        except asyncio.CancelledError:
            logger.trace("USB: BULK EP%d OUT (cancelled)", endpoint & 0x7f)
            raise

    async def _read_eeprom_raw(self, idx, addr, length, chunk_size=0x1000):
        """
        Read ``length`` bytes at ``addr`` from EEPROM at index ``idx``
        in ``chunk_size`` byte chunks.
        """
        data = bytearray()
        while length > 0:
            chunk_length = min(length, chunk_size)
            logger.debug("reading EEPROM chip %d range %04x-%04x",
                         idx, addr, addr + chunk_length - 1)
            data += await self.control_read(REQ_EEPROM, addr, idx, chunk_length)
            addr += chunk_length
            length -= chunk_length
        return data

    async def _write_eeprom_raw(self, idx, addr, data, chunk_size=0x1000):
        """
        Write ``data`` to ``addr`` in EEPROM at index ``idx``
        in ``chunk_size`` byte chunks.
        """
        while len(data) > 0:
            chunk_length = min(len(data), chunk_size)
            logger.debug("writing EEPROM chip %d range %04x-%04x",
                         idx, addr, addr + chunk_length - 1)
            await self.control_write(REQ_EEPROM, addr, idx, data[:chunk_length])
            addr += chunk_length
            data  = data[chunk_length:]

    @staticmethod
    def _adjust_eeprom_addr_for_kind(kind, addr):
        if kind == "fx2":
            base_offset = 0
        elif kind == "ice":
            base_offset = 1
        else:
            raise ValueError(f"Unknown EEPROM kind {kind}")
        return 0x10000 * base_offset + addr

    async def read_eeprom(self, kind, addr, length):
        """
        Read ``length`` bytes at ``addr`` from EEPROM of kind ``kind``
        in ``chunk_size`` byte chunks. Valid ``kind`` is ``"fx2"`` or ``"ice"``.
        """
        logger.debug("reading %s EEPROM range %04x-%04x",
                     kind, addr, addr + length - 1)
        addr = self._adjust_eeprom_addr_for_kind(kind, addr)
        result = bytearray()
        while length > 0:
            chunk_addr   = addr & ((1 << 16) - 1)
            chunk_length = min(chunk_addr + length, 1 << 16) - chunk_addr
            result += await self._read_eeprom_raw(addr >> 16, chunk_addr, chunk_length)
            addr   += chunk_length
            length -= chunk_length
        return result

    async def write_eeprom(self, kind, addr, data):
        """
        Write ``data`` to ``addr`` in EEPROM of kind ``kind``
        in ``chunk_size`` byte chunks. Valid ``kind`` is ``"fx2"`` or ``"ice"``.
        """
        logger.debug("writing %s EEPROM range %04x-%04x",
                     kind, addr, addr + len(data) - 1)
        addr = self._adjust_eeprom_addr_for_kind(kind, addr)
        while len(data) > 0:
            chunk_addr   = addr & ((1 << 16) - 1)
            chunk_length = min(chunk_addr + len(data), 1 << 16) - chunk_addr
            await self._write_eeprom_raw(addr >> 16, chunk_addr, data[:chunk_length])
            addr += chunk_length
            data  = data[chunk_length:]

    async def _status(self):
        result = await self.control_read(REQ_STATUS, 0, 0, 1)
        return result[0]

    async def status(self):
        """
        Query device status.

        Returns a set of flags out of ``{"fpga-ready", "alert"}``.
        """
        status_word = await self._status()
        status_set  = set()
        # Status should be queried and ST_ERROR cleared after every operation that may set it,
        # so we ignore it here.
        if status_word & ST_FPGA_RDY:
            status_set.add("fpga-ready")
        if status_word & ST_ALERT:
            status_set.add("alert")
        return status_set

    async def bitstream_id(self):
        """
        Get bitstream ID for the bitstream currently running on the FPGA,
        or ``None`` if the FPGA does not have a bitstream.
        """
        bitstream_id = await self.control_read(REQ_BITSTREAM_ID, 0, 0, 16)
        if re.match(rb"^\x00+$", bitstream_id):
            return None
        return bytes(bitstream_id)

    async def download_bitstream(self, bitstream, bitstream_id=b"\xff" * 16):
        """Download ``bitstream`` with ID ``bitstream_id`` to FPGA."""
        # Send consecutive chunks of bitstream. Sending 0th chunk also clears the FPGA bitstream.
        index = 0
        while index * 4096 < len(bitstream):
            await self.control_write(REQ_FPGA_CFG, 0, index,
                bitstream[index * 4096:(index + 1) * 4096])
            index += 1
        # Complete configuration by setting bitstream ID. This starts the FPGA.
        try:
            await self.control_write(REQ_BITSTREAM_ID, 0, 0, bitstream_id)
        except usb.ErrorStall:
            raise GlasgowDeviceError("FPGA configuration failed") from None
        try:
            # Each bitstream has an I2C register at address 0, which is used to check that the FPGA
            # has configured properly and that the I2C bus function is intact. A small subset of
            # production devices manufactured by 1bitSquared fails this check.
            magic, = await self.control_read(REQ_REGISTER, 0x00, 0, 1)
        except usb.ErrorStall:
            magic = 0
        if magic != 0xa5:
            raise GlasgowDeviceError(
                "FPGA health check failed; if you are using a newly manufactured device, "
                "ask the vendor of the device for return and replacement, else ask for support "
                "on community channels")

    async def download_target(self, plan, *, reload=False):
        if await self.bitstream_id() == plan.bitstream_id and not reload:
            logger.info("device already has bitstream ID %s", plan.bitstream_id.hex())
            return
        logger.info("generating bitstream ID %s", plan.bitstream_id.hex())
        await self.download_bitstream(await plan.get_bitstream(), plan.bitstream_id)

    async def download_prebuilt(self, plan, bitstream_file):
        bitstream_file_id = bitstream_file.read(16)
        force_download = (bitstream_file_id == b'\xff' * 16)
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

    async def _iobuf_enable(self, on):
        # control the IO-buffers (FXMA108) on revAB, they are on by default
        # no effect on other revisions
        await self.control_write(REQ_IOBUF_ENABLE, on, 0, [])

    @staticmethod
    def _iobuf_spec_to_mask(spec, one):
        if one and len(spec) != 1:
            raise GlasgowDeviceError("exactly one I/O port may be specified for this operation")

        mask = 0
        for port in str(spec):
            if   port == "A":
                mask |= IO_BUF_A
            elif port == "B":
                mask |= IO_BUF_B
            else:
                raise GlasgowDeviceError(f"unknown I/O port {port}")
        return mask

    @staticmethod
    def _mask_to_iobuf_spec(mask):
        spec = ""
        if mask & IO_BUF_A:
            spec += "A"
        if mask & IO_BUF_B:
            spec += "B"
        return spec

    async def _write_voltage(self, req, spec, volts):
        millivolts = round(volts * 1000)
        await self.control_write(req, 0, self._iobuf_spec_to_mask(spec, one=False),
            struct.pack("<H", millivolts))

    async def set_voltage(self, spec, volts):
        await self._write_voltage(REQ_IO_VOLT, spec, volts)
        # Check if we've succeeded
        if await self._status() & ST_ERROR:
            causes = []
            for port in spec:
                if (limit := await self._read_voltage(REQ_LIMIT_VOLT, port)) < volts:
                    causes.append("port {} voltage limit is set to {:.2} V"
                                  .format(port, limit))
            causes_string = ""
            if causes:
                causes_string = f" ({', '.join(causes)})"
            raise GlasgowDeviceError("cannot set I/O port(s) {} voltage to {:.2} V{}"
                                     .format(spec or "(none)", float(volts), causes_string))

    async def set_voltage_limit(self, spec, volts):
        await self._write_voltage(REQ_LIMIT_VOLT, spec, volts)
        # Check if we've succeeded
        if await self._status() & ST_ERROR:
            raise GlasgowDeviceError("cannot set I/O port(s) {} voltage limit to {:.2} V"
                                     .format(spec or "(none)", float(volts)))

    async def _read_voltage(self, req, spec):
        millivolts, = struct.unpack("<H",
            await self.control_read(req, 0, self._iobuf_spec_to_mask(spec, one=True), 2))
        volts = round(millivolts / 1000, 2) # we only have 8 bits of precision
        return volts

    async def get_voltage(self, spec):
        try:
            return await self._read_voltage(REQ_IO_VOLT, spec)
        except usb.ErrorStall:
            raise GlasgowDeviceError(f"cannot get I/O port {spec} I/O voltage") from None

    async def get_voltage_limit(self, spec):
        try:
            return await self._read_voltage(REQ_LIMIT_VOLT, spec)
        except usb.ErrorStall:
            raise GlasgowDeviceError(f"cannot get I/O port {spec} I/O voltage limit") from None

    async def measure_voltage(self, spec):
        try:
            return await self._read_voltage(REQ_SENSE_VOLT, spec)
        except usb.ErrorStall:
            raise GlasgowDeviceError(f"cannot measure I/O port {spec} sense voltage") from None

    async def set_alert(self, spec, low_volts, high_volts):
        low_millivolts  = round(low_volts * 1000)
        high_millivolts = round(high_volts * 1000)
        await self.control_write(REQ_ALERT_VOLT, 0, self._iobuf_spec_to_mask(spec, one=False),
            struct.pack("<HH", low_millivolts, high_millivolts))
        # Check if we've succeeded
        if await self._status() & ST_ERROR:
            raise GlasgowDeviceError("cannot set I/O port(s) {} voltage alert to {:.2}-{:.2} V"
                                     .format(spec or "(none)",
                                             float(low_volts), float(high_volts)))

    async def reset_alert(self, spec):
        await self.set_alert(spec, 0.0, 5.5)

    async def set_alert_tolerance(self, spec, volts, tolerance):
        low_volts  = volts * (1 - tolerance)
        high_volts = volts * (1 + tolerance)
        await self.set_alert(spec, low_volts, high_volts)

    async def mirror_voltage(self, spec, sense=None, *, tolerance=0.05):
        if sense is None:
            sense = spec
        voltage = await self.measure_voltage(sense)
        if voltage < 1.8 * (1 - tolerance):
            raise GlasgowDeviceError("I/O port {} voltage ({} V) too low"
                                     .format(spec, voltage))
        if voltage > 5.0 * (1 + tolerance):
            raise GlasgowDeviceError("I/O port {} voltage ({} V) too high"
                                     .format(spec, voltage))
        await self.set_voltage(spec, voltage)
        await self.set_alert_tolerance(spec, voltage, tolerance=0.05)
        return voltage

    async def get_alert(self, spec):
        try:
            low_millivolts, high_millivolts = struct.unpack("<HH",
                await self.control_read(
                    REQ_ALERT_VOLT, 0, self._iobuf_spec_to_mask(spec, one=True), 4))
            low_volts  = round(low_millivolts / 1000, 2) # we only have 8 bits of precision
            high_volts = round(high_millivolts / 1000, 2)
            return low_volts, high_volts
        except usb.ErrorStall:
            raise GlasgowDeviceError(f"cannot get I/O port {spec} voltage alert") from None

    async def poll_alert(self):
        try:
            mask, = await self.control_read(REQ_POLL_ALERT, 0, 0, 1)
            return self._mask_to_iobuf_spec(mask)
        except usb.ErrorStall:
            raise GlasgowDeviceError("cannot poll alert status") from None

    @property
    def has_pulls(self):
        return self.revision >= "C"

    async def set_pulls(self, spec, low=set(), high=set()):
        assert self.has_pulls
        assert not {bit for bit in low | high if bit >= len(spec) * 8}

        for index, port in enumerate(spec):
            port_enable = 0
            port_value  = 0
            for port_bit in range(0, 8):
                if index * 8 + port_bit in low | high:
                    port_enable |= 1 << port_bit
                if index * 8 + port_bit in high:
                    port_value  |= 1 << port_bit
            await self.control_write(REQ_PULL, 0, self._iobuf_spec_to_mask(port, one=True),
                struct.pack("BB", port_enable, port_value))
            # Check if we've succeeded
            if await self._status() & ST_ERROR:
                raise GlasgowDeviceError("cannot set I/O port(s) {} pull resistors to "
                                         "low={} high={}"
                                         .format(spec or "(none)", low or "{}", high or "{}"))

    async def test_leds(self, states):
        await self.control_write(REQ_TEST_LEDS, 0, states, [])

    async def _register_error(self, addr):
        if await self._status() & ST_FPGA_RDY:
            raise GlasgowDeviceError(f"register 0x{addr:02x} does not exist") from None
        else:
            raise GlasgowDeviceError("FPGA is not configured") from None

    async def read_register(self, addr, width=1):
        """Read ``width``-byte FPGA register at ``addr``."""
        try:
            value = await self.control_read(REQ_REGISTER, addr, 0, width)
            value = int.from_bytes(value, byteorder="little")
            logger.trace("register %d read: %#04x", addr, value)
            return value
        except usb.ErrorStall:
            await self._register_error(addr)

    async def write_register(self, addr, value, width=1):
        """Write ``value`` to ``width``-byte FPGA register at ``addr``."""
        try:
            logger.trace("register %d write: %#04x", addr, value)
            value = value.to_bytes(width, byteorder="big")
            await self.control_write(REQ_REGISTER, addr, 0, value)
        except usb.ErrorStall:
            await self._register_error(addr)


class GlasgowDeviceConfig:
    """
    Glasgow EEPROM configuration data.

    :ivar int size:
        Total size of configuration block (currently 64).

    :ivar str[1] revision:
        Revision letter, ``A``-``Z``.

    :ivar str[16] serial:
        Serial number, in ISO 8601 format.

    :ivar int bitstream_size:
        Size of bitstream flashed to ICE_MEM, or 0 if there isn't one.

    :ivar bytes[16] bitstream_id:
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
    """
    size = 64
    _encoding = "<B16sI16s2H22sb"

    _FLAG_MODIFIED_DESIGN = 0b00000001

    def __init__(self, revision, serial, bitstream_size=0, bitstream_id=b"\x00"*16,
                 voltage_limit=None, manufacturer="", modified_design=False):
        self.revision = revision
        self.serial   = serial
        self.bitstream_size = bitstream_size
        self.bitstream_id   = bitstream_id
        self.voltage_limit  = [5500, 5500] if voltage_limit is None else voltage_limit
        self.manufacturer   = manufacturer
        self.modified_design = bool(modified_design)

    @staticmethod
    def encode_revision(string):
        """
        Encode the human readable revision to the revision byte as used in the firmware.

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
    def decode_revision(value):
        """
        Decode the revision byte as used in the firmware to the human readable revision.

        This inverts the transformation done by :meth:`encode_revision`.
        """
        major, minor = (value & 0xF0) >> 4, value & 0x0F
        if major == 0:
            return chr(ord("A") + minor - 1) + "0"
        elif minor in range(10):
            return chr(ord("A") + major - 1) + chr(ord("0") + minor)
        else:
            raise ValueError(f"invalid revision value {value:#04x}")

    def encode(self):
        """
        Convert configuration to a byte array that can be loaded into memory or EEPROM.
        """
        data = struct.pack(self._encoding,
                           self.encode_revision(self.revision),
                           self.serial.encode("ascii"),
                           self.bitstream_size,
                           self.bitstream_id,
                           self.voltage_limit[0],
                           self.voltage_limit[1],
                           self.manufacturer.encode("ascii"),
                           (self._FLAG_MODIFIED_DESIGN if self.modified_design else 0))
        return data.ljust(self.size, b"\x00")

    @classmethod
    def decode(cls, data):
        """
        Parse configuration from a byte array loaded from memory or EEPROM.

        Returns :class:`GlasgowConfiguration` or raises :class:`ValueError` if
        the byte array does not contain a valid configuration.
        """
        if len(data) != cls.size:
            raise ValueError("Incorrect configuration length")

        voltage_limit = [0, 0]
        revision, serial, bitstream_size, bitstream_id, \
            voltage_limit[0], voltage_limit[1], manufacturer, flags = \
            struct.unpack_from(cls._encoding, data, 0)
        return cls(cls.decode_revision(revision),
                   serial.decode("ascii"),
                   bitstream_size,
                   bitstream_id,
                   voltage_limit,
                   manufacturer.decode("ascii"),
                   flags & cls._FLAG_MODIFIED_DESIGN)
