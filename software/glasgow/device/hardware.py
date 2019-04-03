import re
import time
import struct
import logging
import usb1
import asyncio
import threading
from fx2 import REQ_RAM, REG_CPUCS
from fx2.format import input_data

from ..support.logging import *
from . import GlasgowDeviceError
from .config import GlasgowConfig


__all__ = ["GlasgowHardwareDevice"]

logger = logging.getLogger(__name__)


VID_QIHW         = 0x20b7
PID_GLASGOW      = 0x9db1

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

ST_ERROR         = 1<<0
ST_FPGA_RDY      = 1<<1
ST_ALERT         = 1<<2

IO_BUF_A         = 1<<0
IO_BUF_B         = 1<<1


class _PollerThread(threading.Thread):
    def __init__(self, context):
        super().__init__()
        self.daemon  = True
        self.context = context

    def run(self):
        while True:
            self.context.handleEvents()


class GlasgowHardwareDevice:
    def _open_device(self, vendor_id, product_id):
        try:
            self.usb = self.usb_context.openByVendorIDAndProductID(vendor_id, product_id)
        except usb1.USBErrorAccess:
            raise GlasgowDeviceError("cannot access device {:04x}:{:04x}"
                                     .format(vendor_id, product_id))
        if self.usb is None:
            raise GlasgowDeviceError("device {:04x}:{:04x} not found"
                                     .format(vendor_id, product_id))

        try:
            self.usb.setAutoDetachKernelDriver(True)
        except usb1.USBErrorNotSupported:
            pass

    def _write_ram(self, addr, data):
        while len(data) > 0:
            chunk_length = min(len(data), 4096)
            self.usb.controlWrite(usb1.REQUEST_TYPE_VENDOR, REQ_RAM, addr, 0, data[:chunk_length])
            addr += chunk_length
            data = data[chunk_length:]

    def _cpu_reset(self, is_reset):
        self._write_ram(REG_CPUCS, [1 if is_reset else 0])

    def _download_firmware(self, chunks):
        self._cpu_reset(True)
        for address, data in chunks:
            self._write_ram(address, data)
        self._cpu_reset(False)

    def __init__(self, firmware_file=None, vendor_id=VID_QIHW, product_id=PID_GLASGOW):
        self.usb_context = usb1.USBContext()
        self.usb_poller = _PollerThread(self.usb_context)
        self.usb_poller.start()

        self._open_device(vendor_id, product_id)

        device_id = self.usb.getDevice().getbcdDevice()
        self.revision = GlasgowConfig.decode_revision(device_id & 0xFF)

        if device_id & 0xFF00 in (0x0000, 0xA000):
            logger.debug("found rev%s device without firmware", self.revision)

            if firmware_file is None:
                raise GlasgowDeviceError("firmware is not uploaded")

            logger.debug("loading firmware from %s", firmware_file)
            with open(firmware_file, "rb") as f:
                self._download_firmware(input_data(f, fmt="ihex"))

            # let the device re-enumerate and re-acquire it
            time.sleep(1)
            self._open_device(VID_QIHW, PID_GLASGOW)

            # still not the right firmware?
            if self.usb.getDevice().getbcdDevice() & 0xFF00 in (0x0000, 0xA000):
                raise GlasgowDeviceError("firmware upload failed")

        # https://github.com/vpelletier/python-libusb1/issues/39
        # serial = self.usb.getDevice().getSerialNumber()
        serial = self.usb.getASCIIStringDescriptor(
            self.usb.getDevice().device_descriptor.iSerialNumber)
        logger.debug("found rev%s device with serial %s", self.revision, serial)

    async def _do_transfer(self, is_read, setup):
        transfer = self.usb.getTransfer()
        future = asyncio.Future()
        setup(transfer)

        def usb_callback(transfer):
            if transfer.isSubmitted():
                return # transfer not completed
            if future.cancelled():
                return # future cancelled

            status = transfer.getStatus()
            if status == usb1.TRANSFER_COMPLETED:
                if is_read:
                    future.set_result(transfer.getBuffer()[:transfer.getActualLength()])
                else:
                    future.set_result(None)
            elif status == usb1.TRANSFER_CANCELLED:
                future.cancel()
            elif status == usb1.TRANSFER_STALL:
                future.set_exception(usb1.USBErrorPipe())
            elif status == usb1.TRANSFER_NO_DEVICE:
                future.set_exception(GlasgowDeviceError("device lost"))
            else:
                future.set_exception(GlasgowDeviceError("transfer error: {}".format(status)))

        loop = asyncio.get_event_loop()
        transfer.setCallback(lambda transfer: loop.call_soon_threadsafe(usb_callback, transfer))
        transfer.submit()

        def done_callback(future):
            if future.cancelled():
                # It's tempting to protect the call to `cancel` with `if transfer.isSubmitted():`,
                # but this creates a possible race condition, since libusb is multithreaded.
                # Instead, ignore the error raised on submitted transfers.
                try:
                    transfer.cancel()
                except usb1.USBErrorNotFound:
                    pass
        future.add_done_callback(done_callback)

        return await future

    async def control_read(self, request_type, request, value, index, length):
        logger.trace("USB: CONTROL IN type=%#04x request=%#04x "
                     "value=%#06x index=%#06x length=%d (submit)",
                     request_type, request, value, index, length)
        data = await self._do_transfer(is_read=True, setup=lambda transfer:
            transfer.setControl(request_type|usb1.ENDPOINT_IN, request, value, index, length))
        logger.trace("USB: CONTROL IN data=<%s> (completed)", dump_hex(data))
        return data

    async def control_write(self, request_type, request, value, index, data):
        if not isinstance(data, (bytes, bytearray)):
            data = bytes(data)
        logger.trace("USB: CONTROL OUT type=%#04x request=%#04x "
                     "value=%#06x index=%#06x data=<%s> (submit)",
                     request_type, request, value, index, dump_hex(data))
        await self._do_transfer(is_read=False, setup=lambda transfer:
            transfer.setControl(request_type|usb1.ENDPOINT_OUT, request, value, index, data))
        logger.trace("USB: CONTROL OUT (completed)")

    async def bulk_read(self, endpoint, length):
        logger.trace("USB: BULK EP%d IN length=%d (submit)", endpoint & 0x7f, length)
        data = await self._do_transfer(is_read=True, setup=lambda transfer:
            transfer.setBulk(endpoint|usb1.ENDPOINT_IN, length))
        logger.trace("USB: BULK EP%d IN data=<%s> (completed)", endpoint & 0x7f, dump_hex(data))
        return data

    async def bulk_write(self, endpoint, data):
        if not isinstance(data, (bytes, bytearray)):
            data = bytes(data)
        logger.trace("USB: BULK EP%d OUT data=<%s> (submit)", endpoint & 0x7f, dump_hex(data))
        await self._do_transfer(is_read=False, setup=lambda transfer:
            transfer.setBulk(endpoint|usb1.ENDPOINT_OUT, data))
        logger.trace("USB: BULK EP%d OUT (completed)", endpoint & 0x7f)

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
            data += await self.control_read(usb1.REQUEST_TYPE_VENDOR, REQ_EEPROM,
                                            addr, idx, chunk_length)
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
            await self.control_write(usb1.REQUEST_TYPE_VENDOR, REQ_EEPROM,
                                     addr, idx, data[:chunk_length])
            addr += chunk_length
            data  = data[chunk_length:]

    @staticmethod
    def _adjust_eeprom_addr_for_kind(kind, addr):
        if kind == "fx2":
            base_offset = 0
        elif kind == "ice":
            base_offset = 1
        else:
            raise ValueError("Unknown EEPROM kind {}".format(kind))
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
        result = await self.control_read(usb1.REQUEST_TYPE_VENDOR, REQ_STATUS, 0, 0, 1)
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
        bitstream_id = await self.control_read(usb1.REQUEST_TYPE_VENDOR, REQ_BITSTREAM_ID,
                                               0, 0, 16)
        if re.match(rb"^\x00+$", bitstream_id):
            return None
        return bytes(bitstream_id)

    async def download_bitstream(self, bitstream, bitstream_id=b"\xff" * 16):
        """Download ``bitstream`` with ID ``bitstream_id`` to FPGA."""
        # Send consecutive chunks of bitstream.
        # Sending 0th chunk resets the FPGA.
        index = 0
        while index * 1024 < len(bitstream):
            await self.control_write(usb1.REQUEST_TYPE_VENDOR, REQ_FPGA_CFG,
                                     0, index, bitstream[index * 1024:(index + 1) * 1024])
            index += 1
        # Complete configuration by setting bitstream ID.
        # This starts the FPGA.
        try:
            await self.control_write(usb1.REQUEST_TYPE_VENDOR, REQ_BITSTREAM_ID,
                                     0, 0, bitstream_id)
        except usb1.USBErrorPipe:
            raise GlasgowDeviceError("FPGA configuration failed")

    async def download_target(self, target, rebuild=False, toolchain_opts={}):
        bitstream_id = target.get_bitstream_id()
        if await self.bitstream_id() == bitstream_id and not rebuild:
            logger.info("device already has bitstream ID %s", bitstream_id.hex())
        else:
            logger.info("building bitstream ID %s", bitstream_id.hex())
            bitstream = target.get_bitstream(**toolchain_opts)
            await self.download_bitstream(bitstream, bitstream_id)

    async def _iobuf_enable(self, on):
        await self.control_write(usb1.REQUEST_TYPE_VENDOR, REQ_IOBUF_ENABLE, on, 0, [])

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
                raise GlasgowDeviceError("unknown I/O port {}".format(port))
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
        await self.control_write(usb1.REQUEST_TYPE_VENDOR, req,
            0, self._iobuf_spec_to_mask(spec, one=False), struct.pack("<H", millivolts))

    async def set_voltage(self, spec, volts):
        await self._write_voltage(REQ_IO_VOLT, spec, volts)
        # Check if we've succeeded
        if await self._status() & ST_ERROR:
            raise GlasgowDeviceError("cannot set I/O port(s) {} voltage to {:.2} V"
                                     .format(spec or "(none)", float(volts)))

    async def set_voltage_limit(self, spec, volts):
        await self._write_voltage(REQ_LIMIT_VOLT, spec, volts)
        # Check if we've succeeded
        if await self._status() & ST_ERROR:
            raise GlasgowDeviceError("cannot set I/O port(s) {} voltage limit to {:.2} V"
                                     .format(spec or "(none)", float(volts)))

    async def _read_voltage(self, req, spec):
        millivolts, = struct.unpack("<H",
            await self.control_read(usb1.REQUEST_TYPE_VENDOR, req,
                0, self._iobuf_spec_to_mask(spec, one=True), 2))
        volts = round(millivolts / 1000, 2) # we only have 8 bits of precision
        return volts

    async def get_voltage(self, spec):
        try:
            return await self._read_voltage(REQ_IO_VOLT, spec)
        except usb1.USBErrorPipe:
            raise GlasgowDeviceError("cannot get I/O port {} I/O voltage".format(spec))

    async def get_voltage_limit(self, spec):
        try:
            return await self._read_voltage(REQ_LIMIT_VOLT, spec)
        except usb1.USBErrorPipe:
            raise GlasgowDeviceError("cannot get I/O port {} I/O voltage limit".format(spec))

    async def measure_voltage(self, spec):
        try:
            return await self._read_voltage(REQ_SENSE_VOLT, spec)
        except usb1.USBErrorPipe:
            raise GlasgowDeviceError("cannot measure I/O port {} sense voltage".format(spec))

    async def set_alert(self, spec, low_volts, high_volts):
        low_millivolts  = round(low_volts * 1000)
        high_millivolts = round(high_volts * 1000)
        await self.control_write(usb1.REQUEST_TYPE_VENDOR, REQ_ALERT_VOLT,
            0, self._iobuf_spec_to_mask(spec, one=False),
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

    async def mirror_voltage(self, spec, tolerance=0.05):
        voltage = await self.measure_voltage(spec)
        if voltage < 1.8 * (1 - tolerance):
            raise GlasgowDeviceError("I/O port {} voltage ({} V) too low"
                                     .format(spec, voltage))
        if voltage > 5.0 * (1 + tolerance):
            raise GlasgowDeviceError("I/O port {} voltage ({} V) too high"
                                     .format(spec, voltage))
        await self.set_voltage(spec, voltage)
        await self.set_alert_tolerance(spec, voltage, tolerance=0.05)

    async def get_alert(self, spec):
        try:
            low_millivolts, high_millivolts = struct.unpack("<HH",
                await self.control_read(usb1.REQUEST_TYPE_VENDOR, REQ_ALERT_VOLT,
                    0, self._iobuf_spec_to_mask(spec, one=True), 4))
            low_volts  = round(low_millivolts / 1000, 2) # we only have 8 bits of precision
            high_volts = round(high_millivolts / 1000, 2)
            return low_volts, high_volts
        except usb1.USBErrorPipe:
            raise GlasgowDeviceError("cannot get I/O port {} voltage alert".format(spec))

    async def poll_alert(self):
        try:
            mask, = await self.control_read(usb1.REQUEST_TYPE_VENDOR, REQ_POLL_ALERT, 0, 0, 1)
            return self._mask_to_iobuf_spec(mask)
        except usb1.USBErrorPipe:
            raise GlasgowDeviceError("cannot poll alert status")

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
            await self.control_write(usb1.REQUEST_TYPE_VENDOR, REQ_PULL,
                0, self._iobuf_spec_to_mask(port, one=True),
                struct.pack("BB", port_enable, port_value))
            # Check if we've succeeded
            if await self._status() & ST_ERROR:
                raise GlasgowDeviceError("cannot set I/O port(s) {} pull resistors to low={} high={}"
                                         .format(spec or "(none)", low or "{}", high or "{}"))

    async def _register_error(self, addr):
        if await self._status() & ST_FPGA_RDY:
            raise GlasgowDeviceError("register 0x{:02x} does not exist".format(addr))
        else:
            raise GlasgowDeviceError("FPGA is not configured")

    async def read_register(self, addr, width=1):
        """Read ``width``-byte FPGA register at ``addr``."""
        try:
            value = await self.control_read(usb1.REQUEST_TYPE_VENDOR, REQ_REGISTER, addr, 0, width)
            value = int.from_bytes(value, byteorder="little")
            logger.trace("register %d read: %#04x", addr, value)
            return value
        except usb1.USBErrorPipe:
            await self._register_error(addr)

    async def write_register(self, addr, value, width=1):
        """Write ``value`` to ``width``-byte FPGA register at ``addr``."""
        try:
            logger.trace("register %d write: %#04x", addr, value)
            value = value.to_bytes(width, byteorder="big")
            await self.control_write(usb1.REQUEST_TYPE_VENDOR, REQ_REGISTER, addr, 0, value)
        except usb1.USBErrorPipe:
            await self._register_error(addr)
