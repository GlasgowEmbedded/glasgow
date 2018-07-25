import struct


class GlasgowConfig:
    """
    Glasgow EEPROM configuration data.

    :type size: int
    :attr size:
        Total size of configuration block (currently 64).

    :type revision: str[1]
    :attr revision:
        Revision letter, ``A``-``Z``.

    :type serial: str[16]
    :attr serial:
        Serial number, in ISO 8601 format.

    :type bitstream_size: int
    :attr bitstream_size:
        Size of bitstream flashed to ICE_MEM, or 0 if there isn't one.

    :type bitstream_id: bytes[16]
    :attr bitstream_id:
        Opaque string that uniquely identifies bitstream functionality,
        but not necessarily any particular routing and placement.
        Only meaningful if ``bitstream_size`` is set.

    :type voltage_limit: int[2]
    :attr voltage_limit:
        Maximum allowed I/O port voltage, in millivolts.
    """
    size = 64
    _encoding = "<1s16sI16s2h"

    def __init__(self, revision, serial, bitstream_size=0, bitstream_id="\x00"*16,
                 voltage_limit=None):
        self.revision = revision
        self.serial   = serial
        self.bitstream_size = bitstream_size
        self.bitstream_id   = bitstream_id
        self.voltage_limit  = [5500, 5500] if voltage_limit is None else voltage_limit

    def encode(self):
        """
        Convert configuration to a byte array that can be loaded into memory or EEPROM.
        """
        data = struct.pack(self._encoding,
                           self.revision.encode("ascii"),
                           self.serial.encode("ascii"),
                           self.bitstream_size,
                           self.bitstream_id,
                           self.voltage_limit[0],
                           self.voltage_limit[1])
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
            voltage_limit[0], voltage_limit[1] = \
            struct.unpack_from(cls._encoding, data, 0)
        return cls(revision.decode("ascii"),
                   serial.decode("ascii"),
                   bitstream_size,
                   bitstream_id,
                   voltage_limit)
