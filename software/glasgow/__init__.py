import usb1

from fx2 import *


__all__ = ['GlasgowDevice', 'GlasgowDeviceError']


VID_OPENMOKO = 0x1d50
PID_GLASGOW  = 0x7777

REQ_RW_EEPROM  = 0x10


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
