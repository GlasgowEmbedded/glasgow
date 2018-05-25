import re
import time
import struct
import logging
import usb1

from fx2 import *
from fx2.format import input_data


__all__ = ['GlasgowDevice', 'GlasgowDeviceError']

logger = logging.getLogger(__name__)


VID_QIHW       = 0x20b7
PID_GLASGOW    = 0x9db1

REQ_EEPROM       = 0x10
REQ_FPGA_CFG     = 0x11
REQ_STATUS       = 0x12
REQ_REGISTER     = 0x13
REQ_IO_VOLT      = 0x14
REQ_SENSE_VOLT   = 0x15
REQ_ALERT_VOLT   = 0x16
REQ_POLL_ALERT   = 0x17
REQ_BITSTREAM_ID = 0x18

ST_ERROR       = 1<<0
ST_FPGA_RDY    = 1<<1
ST_ALERT       = 1<<2

IO_BUF_A       = 1<<0
IO_BUF_B       = 1<<1


class GlasgowConfig:
    """
    Glasgow EEPROM configuration data.

    size : int
        Total size of configuration block (currently 64).
    revision : str[1]
        Revision letter, ``A``-``Z``.
    serial : str[16]
        Serial number, in ISO 8601 format.
    bitstream_size : int
        Size of bitstream flashed to ICE_MEM, or 0 if there isn't one.
    bitstream_id : bytes[16]
        Opaque string that uniquely identifies bitstream functionality,
        but not necessarily any particular routing and placement.
        Only meaningful if ``bitstream_size`` is set.
    """
    size = 64
    _encoding = "<1s16sI16s"

    def __init__(self, revision, serial, bitstream_size=0, bitstream_id="\x00"*16):
        self.revision = revision
        self.serial   = serial
        self.bitstream_size = bitstream_size
        self.bitstream_id   = bitstream_id

    def encode(self):
        """
        Convert configuration to a byte array that can be loaded into memory or EEPROM.
        """
        data = struct.pack(self._encoding,
                           self.revision.encode("ascii"),
                           self.serial.encode("ascii"),
                           self.bitstream_size,
                           self.bitstream_id)
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

        revision, serial, bitstream_size, bitstream_id = \
            struct.unpack_from(cls._encoding, data, 0)
        return GlasgowConfig(revision.decode("ascii"),
                             serial.decode("ascii"),
                             bitstream_size,
                             bitstream_id)


class GlasgowDeviceError(FX2DeviceError):
    """An exception raised on a communication error."""


class GlasgowDevice(FX2Device):
    def __init__(self, firmware_file=None, vendor_id=VID_QIHW, product_id=PID_GLASGOW):
        super().__init__(vendor_id, product_id)

        device_id = self.usb.getDevice().getbcdDevice()
        if device_id & 0xFF00 in (0x0000, 0xA000):
            revision = chr(ord("A") + (device_id & 0xFF) - 1)
            logger.debug("found rev%s device without firmware", revision)

            if firmware_file is None:
                raise GlasgowDeviceError("Firmware is not uploaded")
            else:
                logger.debug("loading firmware from %s", firmware_file)
                with open(firmware_file, "rb") as f:
                    self.load_ram(input_data(f, fmt="ihex"))

                # let the device re-enumerate and re-acquire it
                time.sleep(1)
                super().__init__(VID_QIHW, PID_GLASGOW)

                # still not the right firmware?
                if self.usb.getDevice().getbcdDevice() & 0xFF00 in (0x0000, 0xA000):
                    raise GlasgowDeviceError("Firmware upload failed")

        logger.debug("found device with serial %s",
                     self.usb.getDevice().getSerialNumber())

    def _read_eeprom_raw(self, idx, addr, length, chunk_size=0x1000):
        """
        Read ``length`` bytes at ``addr`` from EEPROM at index ``idx``
        in ``chunk_size`` byte chunks.
        """
        data = bytearray()
        while length > 0:
            chunk_length = min(length, chunk_size)
            logger.debug("reading EEPROM chip %d range %04x-%04x",
                         idx, addr, addr + chunk_length - 1)
            data += self.control_read(usb1.REQUEST_TYPE_VENDOR, REQ_EEPROM,
                                      addr, idx, chunk_length)
            addr += chunk_length
            length -= chunk_length
        return data

    def _write_eeprom_raw(self, idx, addr, data, chunk_size=0x1000):
        """
        Write ``data`` to ``addr`` in EEPROM at index ``idx``
        in ``chunk_size`` byte chunks.
        """
        while len(data) > 0:
            chunk_length = min(len(data), chunk_size)
            logger.debug("writing EEPROM chip %d range %04x-%04x",
                         idx, addr, addr + chunk_length - 1)
            self.control_write(usb1.REQUEST_TYPE_VENDOR, REQ_EEPROM,
                               addr, idx, data[:chunk_length])
            addr += chunk_length
            data = data[chunk_length:]

    @staticmethod
    def _adjust_eeprom_addr_for_kind(kind, addr):
        if kind == "fx2":
            base_offset = 0
        elif kind == "ice":
            base_offset = 1
        else:
            raise ValueError("Unknown EEPROM kind {}".format(kind))
        return 0x10000 * base_offset + addr

    def read_eeprom(self, kind, addr, length):
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
            result += self._read_eeprom_raw(addr >> 16, chunk_addr, chunk_length)
            addr   += chunk_length
            length -= chunk_length
        return result

    def write_eeprom(self, kind, addr, data):
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
            self._write_eeprom_raw(addr >> 16, chunk_addr, data[:chunk_length])
            addr += chunk_length
            data  = data[chunk_length:]

    def _status(self):
        return self.control_read(usb1.REQUEST_TYPE_VENDOR, REQ_STATUS, 0, 0, 1)[0]

    def status(self):
        """
        Query device status.

        Returns a set of flags out of ``{"fpga-ready", "alert"}``.
        """
        status_word = self._status()
        status_set = set()
        # Status should be queried and ST_ERROR cleared after every operation that may set it,
        # so we ignore it here.
        if status_word & ST_FPGA_RDY:
            status_set.add("fpga-ready")
        if status_word & ST_ALERT:
            status_set.add("alert")
        return status_set

    def _register_error(self, addr):
        if self._status() & ST_FPGA_RDY:
            raise GlasgowDeviceError("Register 0x{:02x} does not exit".format(addr))
        else:
            raise GlasgowDeviceError("FPGA is not configured")

    def read_register(self, addr):
        """Read byte FPGA register at ``addr``."""
        try:
            return self.control_read(usb1.REQUEST_TYPE_VENDOR, REQ_REGISTER, addr, 0, 1)[0]
        except usb1.USBErrorPipe:
            self._register_error(addr)

    def write_register(self, addr, value):
        """Write ``value`` to byte FPGA register at ``addr``."""
        try:
            self.control_write(usb1.REQUEST_TYPE_VENDOR, REQ_REGISTER, addr, 0, [value])
        except usb1.USBErrorPipe:
            self._register_error(addr)

    def bitstream_id(self):
        """
        Get bitstream ID for the bitstream currently running on the FPGA,
        or ``None`` if the FPGA does not have a bitstream.
        """
        bitstream_id = self.control_read(usb1.REQUEST_TYPE_VENDOR, REQ_BITSTREAM_ID, 0, 0, 16)
        if re.match(rb"^\x00+$", bitstream_id):
            return None
        return bytes(bitstream_id)

    def download_bitstream(self, bitstream, bitstream_id=b"\xff" * 16):
        """Download ``bitstream`` with ID ``bitstream_id`` to FPGA."""
        # Send consecutive chunks of bitstream.
        # Sending 0th chunk resets the FPGA.
        index = 0
        while index * 1024 < len(bitstream):
            self.control_write(usb1.REQUEST_TYPE_VENDOR, REQ_FPGA_CFG, 0, index,
                               bitstream[index * 1024:(index + 1)*1024])
            index += 1
        # Complete configuration by setting bitstream ID.
        # This starts the FPGA.
        try:
            self.control_write(usb1.REQUEST_TYPE_VENDOR, REQ_BITSTREAM_ID, 0, 0, bitstream_id)
        except usb1.USBErrorPipe:
            raise GlasgowDeviceError("FPGA configuration failed")

    @staticmethod
    def _iobuf_spec_to_mask(spec, one):
        if one and len(spec) != 1:
            raise GlasgowDeviceError("Exactly one I/O port may be specified for this operation")

        mask = 0
        for port in str(spec):
            if   port == "A":
                mask |= IO_BUF_A
            elif port == "B":
                mask |= IO_BUF_B
            else:
                raise GlasgowDeviceError("Unknown I/O port {}".format(port))
        return mask

    @staticmethod
    def _mask_to_iobuf_spec(mask):
        spec = ""
        if mask & IO_BUF_A:
            spec += "A"
        if mask & IO_BUF_B:
            spec += "B"
        return spec

    def set_voltage(self, spec, volts):
        millivolts = round(volts * 1000)
        self.control_write(usb1.REQUEST_TYPE_VENDOR, REQ_IO_VOLT,
            0, self._iobuf_spec_to_mask(spec, one=False), struct.pack("<H", millivolts))
        # Check if we've succeeded
        if self._status() & ST_ERROR:
            raise GlasgowDeviceError("Cannot set I/O port(s) {} voltage to {:.2} V"
                                     .format(spec or "(none)", float(volts)))

    def _read_voltage(self, req, spec):
        millivolts = struct.unpack("<H",
            self.control_read(usb1.REQUEST_TYPE_VENDOR, req,
                0, self._iobuf_spec_to_mask(spec, one=True), 2))[0]
        volts = round(millivolts / 1000, 2) # we only have 8 bits of precision
        return volts

    def get_voltage(self, spec):
        try:
            return self._read_voltage(REQ_IO_VOLT, spec)
        except usb1.USBErrorPipe:
            raise GlasgowDeviceError("Cannot get I/O port {} I/O voltage".format(spec))

    def measure_voltage(self, spec):
        try:
            return self._read_voltage(REQ_SENSE_VOLT, spec)
        except usb1.USBErrorPipe:
            raise GlasgowDeviceError("Cannot measure I/O port {} sense voltage".format(spec))

    def set_alert(self, spec, low_volts, high_volts):
        low_millivolts  = round(low_volts * 1000)
        high_millivolts = round(high_volts * 1000)
        self.control_write(usb1.REQUEST_TYPE_VENDOR, REQ_ALERT_VOLT,
            0, self._iobuf_spec_to_mask(spec, one=False),
            struct.pack("<HH", low_millivolts, high_millivolts))
        # Check if we've succeeded
        if self._status() & ST_ERROR:
            raise GlasgowDeviceError("Cannot set I/O port(s) {} voltage alert to {:.2}-{:.2} V"
                                     .format(spec or "(none)",
                                             float(low_volts), float(high_volts)))

    def reset_alert(self, spec):
        self.set_alert(spec, 0.0, 5.5)

    def set_alert_tolerance(self, spec, volts, tolerance):
        low_volts  = volts * (1 - tolerance)
        high_volts = volts * (1 + tolerance)
        self.set_alert(spec, low_volts, high_volts)

    def mirror_voltage(self, spec, tolerance=0.05):
        voltage = self.measure_voltage(spec)
        if voltage < 1.8 * (1 - tolerance):
            raise GlasgowDeviceError("I/O port {} voltage ({} V) too low"
                                     .format(spec, voltage))
        if voltage > 5.0 * (1 + tolerance):
            raise GlasgowDeviceError("I/O port {} voltage ({} V) too high"
                                     .format(spec, voltage))
        self.set_voltage(spec, voltage)
        self.set_alert_tolerance(spec, voltage, tolerance=0.05)

    def get_alert(self, spec):
        try:
            low_millivolts, high_millivolts = struct.unpack("<HH",
                self.control_read(usb1.REQUEST_TYPE_VENDOR, REQ_ALERT_VOLT,
                    0, self._iobuf_spec_to_mask(spec, one=True), 4))
            low_volts  = round(low_millivolts / 1000, 2) # we only have 8 bits of precision
            high_volts = round(high_millivolts / 1000, 2)
            return low_volts, high_volts
        except usb1.USBErrorPipe:
            raise GlasgowDeviceError("Cannot get I/O port {} voltage alert".format(spec))

    def poll_alert(self):
        try:
            mask = self.control_read(usb1.REQUEST_TYPE_VENDOR, REQ_POLL_ALERT, 0, 0, 1)[0]
            return self._mask_to_iobuf_spec(mask)
        except usb1.USBErrorPipe:
            raise GlasgowDeviceError("Cannot poll alert status")

    def get_port(self, port):
        if port == "A":
            interface_num = 0
        elif port == "B":
            interface_num = 1
        else:
            raise GlasgowDeviceError("Unknown I/O port {}".format(port))

        return GlasgowPort(self, interface_num)


class GlasgowPort:
    def __init__(self, device, interface_num):
        self.device = device

        config_num = device.usb.getConfiguration()
        for config in device.usb.getDevice().iterConfigurations():
            if config.getConfigurationValue() == config_num:
                break

        interfaces = list(config.iterInterfaces())
        if interface_num > len(interfaces):
            raise GlasgowDeviceError("Interface {} is not present in configuration {}"
                                     .format(interface_num, config_num))
        interface = interfaces[interface_num]

        settings = list(interface.iterSettings())
        setting = settings[0] # we use the same endpoints in all alternative settings
        for endpoint in setting.iterEndpoints():
            address = endpoint.getAddress()
            packet_size = endpoint.getMaxPacketSize()
            if address & usb1.ENDPOINT_DIR_MASK == usb1.ENDPOINT_IN:
                self.endpoint_in = address
                self.in_packet_size = packet_size
            if address & usb1.ENDPOINT_DIR_MASK == usb1.ENDPOINT_OUT:
                self.endpoint_out = address
                self.out_packet_size = packet_size
        assert self.endpoint_in != None and self.endpoint_out != None

        try:
            self.interface = device.usb.claimInterface(interface_num)
        except usb1.USBErrorBusy:
            raise GlasgowDeviceError("I/O port {} already claimed".format(port))

        self.buffer_in  = bytearray()
        self.buffer_out = bytearray()

    def read(self, length):
        self.flush()

        while len(self.buffer_in) < length:
            self.buffer_in += self.device.bulk_read(self.endpoint_in, self.in_packet_size)

        result = self.buffer_in[:length]
        self.buffer_in = self.buffer_in[length:]
        return result

    def read_str(self, length, encoding="utf-8"):
        return self.read(length).decode(encoding)

    def write(self, data):
        self.buffer_out += bytearray(data)

        # You can only write around 16 MB into an USB endpoint in one call,
        # better just packetize it here.
        while len(self.buffer_out) > self.out_packet_size:
            self.device.bulk_write(self.endpoint_out, self.buffer_out[:self.out_packet_size])
            self.buffer_out = self.buffer_out[self.out_packet_size:]

    def write_str(self, data, encoding="utf-8"):
        return self.write(data.encode(encoding))

    def flush(self):
        while len(self.buffer_out) > 0:
            self.device.bulk_write(self.endpoint_out, self.buffer_out[:self.out_packet_size])
            self.buffer_out = self.buffer_out[self.out_packet_size:]

    def __del__(self):
        self.flush()
