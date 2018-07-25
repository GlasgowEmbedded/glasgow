import logging

from .. import *
from ..i2c_master import I2CMasterApplet


logger = logging.getLogger(__name__)


class I2CEEPROMInterface:
    def __init__(self, interface, logger, i2c_address):
        self.lower     = interface
        self._logger   = logger
        self._level    = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._i2c_addr = i2c_address

    def _log(self, message, *args):
        self._logger.log(self._level, "I2C EEPROM: i2c_addr=%s " + message,
                         self._i2c_addr, *args)

    def read(self, addr, size, chunk_size=128):
        data = b""
        while size > 0:
            self._log("addr=%#04x", addr)

            result = self.lower.write(self._i2c_addr, [addr])
            if result is None:
                self._log("unacked")
                return None

            if size < chunk_size:
                self._log("read=%d", size)
                chunk = self.lower.read(self._i2c_addr, size, stop=True)
            else:
                self._log("read=%d", chunk_size)
                chunk = self.lower.read(self._i2c_addr, chunk_size)

            if chunk is None:
                self._log("unacked")
                return None
            else:
                self._log("data=<%s>", chunk.hex())

            data += chunk
            addr += len(chunk)
            size -= len(chunk)

        return data

    def write(self, addr, data, page_size=8):
        while len(data) > 0:
            chunk = data[:page_size]
            data  = data[page_size:]
            self._log("addr=%#04x write=<%s>", addr, chunk.hex())
            result = self.lower.write(i2c_addr, [addr, *chunk], stop=True)
            if result is None:
                self._log("unacked")
                return False

            while not self.lower.poll(i2c_addr): pass
            addr += len(chunk)

        return True


class I2CEEPROMApplet(I2CMasterApplet, name="i2c-eeprom"):
    logger = logger
    help = "read 24C-compatible EEPROMs"
    description = """
    Read first 256 bytes of a 24C02-compatible EEPROM.
    """

    def run(self, device, args, interactive=True):
        i2c_iface = super().run(device, args, interactive=False)
        eeprom_iface = I2CEEPROMInterface(i2c_iface, self.logger, 0b1010000)
        if interactive:
            # TODO: implement
            print(eeprom_iface.read(0x00, 0x100).hex())
        else:
            return eeprom_iface

