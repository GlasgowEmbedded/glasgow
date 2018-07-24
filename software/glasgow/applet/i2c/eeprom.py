import logging

from .. import *
from ..i2c_master import I2CMasterApplet


logger = logging.getLogger(__name__)


class I2CEEPROMInterface:
    def __init__(self, interface):
        self.lower = interface

    def write(self, i2c_addr, addr, data, page_size=8):
        while len(data) > 0:
            chunk = data[:page_size]
            data  = data[page_size:]
            self.lower.write(i2c_addr, [addr, *chunk], stop=True)
            while not self.lower.poll(i2c_addr): pass
            addr += len(chunk)

    def read(self, i2c_addr, addr, size, chunk_size=32):
        data = b""
        while size > 0:
            self.lower.write(i2c_addr, [addr])
            chunk = self.lower.read(i2c_addr, min(size, chunk_size))
            data += chunk
            addr += len(chunk)
            size -= len(chunk)
        self.lower.stop()
        return data


class I2CEEPROMApplet(I2CMasterApplet, name="i2c-eeprom"):
    logger = logger
    help = "read 24C-compatible EEPROMs"
    description = """
    Read first 256 bytes of a 24C02-compatible EEPROM.
    """

    def run(self, device, args, interactive=True):
        i2c_iface = super().run(device, args, interactive=False)
        eeprom_iface = I2CEEPROMInterface(i2c_iface)
        if interactive:
            # TODO: implement
            print(eeprom_iface.read(0b1010000, 0x00, 0x100).hex())
        else:
            return eeprom_iface

