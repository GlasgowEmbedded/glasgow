import usb1

from fx2 import *


__all__ = ['GlasgowDevice', 'GlasgowDeviceError']


VID_OPENMOKO = 0x1d50
PID_GLASGOW  = 0x7777

REQ_EEPROM   = 0x10
REQ_FPGA     = 0x11


class GlasgowDeviceError(FX2DeviceError):
    """An exception raised on a communication error."""


class GlasgowDevice(FX2Device):
    def __init__(self):
        super().__init__(VID_OPENMOKO, PID_GLASGOW)
        if self._device.getDevice().getbcdDevice() == 0:
            raise GlasgowDeviceError("Device is missing firmware")

    def read_eeprom(self, idx, addr, length):
        """Read ``length`` bytes at ``addr`` from EEPROM at index ``idx``."""
        return self.control_read(usb1.REQUEST_TYPE_VENDOR, REQ_RW_EEPROM, addr, idx, length)

    def write_eeprom(self, idx, addr, data):
        """Write ``data`` to ``addr`` in EEPROM at index ``idx``."""
        self.control_write(usb1.REQUEST_TYPE_VENDOR, REQ_RW_EEPROM, addr, idx, data)

    def download_bitstream(self, data):
        """Download bitstream ``data`` to FPGA."""
        # Send consecutive chunks of bitstream.
        # Sending 0th chunk resets the FPGA.
        index = 0
        while index * 1024 < len(data):
            self.control_write(usb1.REQUEST_TYPE_VENDOR, REQ_FPGA, 0, index,
                               data[index * 1024:(index + 1)*1024])
            index += 1
        # Complete configuration by sending a request with no data.
        try:
            self.control_write(usb1.REQUEST_TYPE_VENDOR, REQ_FPGA, 0, index, [])
        except usb1.USBErrorPipe:
            raise GlasgowDeviceError("FPGA configuration failed")
