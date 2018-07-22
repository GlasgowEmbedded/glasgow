from migen.build.generic_programmer import GenericProgrammer
from ..device import GlasgowDevice


__all__ = ['GlasgowProgrammer']


class GlasgowProgrammer(GenericProgrammer):
    # def flash(self, address, bitstream_file):
    #     pass

    def load_bitstream(self, bitstream_file):
        with open(bitstream_file, "rb") as f:
            GlasgowDevice().download_bitstream(f.read())
