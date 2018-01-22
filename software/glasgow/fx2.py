import usb1


VID_CYPRESS = 0x04B4
PID_FX2     = 0x8613

_CMD_RW_RAM       = 0xA0
_CMD_RW_EEPROM_SB = 0xA2
_CMD_RENUM        = 0xA8
_CMD_RW_EEPROM_DB = 0xA9


class FX2DeviceError(Exception):
    pass


class FX2Device:
    def __init__(self, vid=VID_CYPRESS, pid=PID_FX2):
        self._context = usb1.USBContext()
        self._device = self._context.openByVendorIDAndProductID(vid, pid)
        if self._device is None:
            raise FX2DeviceError(f"Device {vid:04x}:{pid:04x} not found")
        self._device.setAutoDetachKernelDriver(True)

        self._eeprom_size = None

    def read_ram(self, addr, length):
        """
        Read ``length`` bytes at ``addr`` from internal RAM.
        Note that not all memory can be addressed this way; consult the TRM.
        """
        if addr & 1: # unaligned
            return self._device.controlRead(0x40, _CMD_RW_RAM, addr, 0, length + 1)[1:]
        else:
            return self._device.controlRead(0x40, _CMD_RW_RAM, addr, 0, length)

    def write_ram(self, addr, data):
        """
        Write ``data`` to ``addr`` to internal RAM.
        Note that not all memory can be addressed this way; consult the TRM.
        """
        self._device.controlWrite(0x40, _CMD_RW_RAM, addr, 0, data)

    def cpu_reset(self, is_reset):
        """Bring CPU in or out of reset."""
        self.write_ram(0xE600, [1 if is_reset else 0])

    @staticmethod
    def _eeprom_cmd(addr_width):
        if addr_width == 1:
            return _CMD_RW_EEPROM_SB
        elif addr_width == 2:
            return _CMD_RW_EEPROM_DB
        else:
            raise ValueError(f"Address width {addr_width} is not supported")

    def read_eeprom(self, addr, length, addr_width):
        """Read ``length`` bytes at ``addr`` from boot EEPROM."""
        return self._device.controlRead(0x40, self._eeprom_cmd(addr_width), addr, 0, length)

    def write_eeprom(self, addr, data, addr_width):
        """Write ``data`` to ``addr`` in boot EEPROM."""
        self._device.controlWrite(0x40, self._eeprom_cmd(addr_width), addr, 0, data)

    def reenumerate(self):
        """Trigger re-enumeration."""
        self._device.controlWrite(0x40, _CMD_RENUM, 0, 0, [])
