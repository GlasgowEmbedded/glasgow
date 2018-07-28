import re
import argparse


__all__ = ["GlasgowAppletError", "GlasgowApplet"]


class GlasgowAppletError(Exception):
    """An exception raised when an applet encounters an error."""


class GlasgowApplet:
    all_applets = {}

    def __init_subclass__(cls, name, **kwargs):
        super().__init_subclass__(**kwargs)

        if name in cls.all_applets:
            raise ValueError("Applet {!r} already exists".format(name))

        cls.all_applets[name] = cls
        cls.name = name

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_build_arguments(parser)

    def build(self, target):
        raise NotImplemented

    @classmethod
    def add_run_arguments(cls, parser, access):
        access.add_run_arguments(parser)

    def run(self, device, args):
        raise NotImplemented

    @classmethod
    def add_interact_arguments(cls, parser):
        pass

    def interact(self, device, args, interface):
        pass


from .hd44780 import HD44780Applet
from .i2c_master import I2CMasterApplet
from .i2c.bmp280 import I2CBMP280Applet
from .i2c.eeprom_24c import I2CEEPROM24CApplet
from .program_ice40 import ProgramICE40Applet
from .selftest import SelfTestApplet
from .uart import UARTApplet
