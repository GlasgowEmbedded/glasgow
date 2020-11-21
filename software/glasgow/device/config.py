import struct
import re


__all__ = ["GlasgowConfig"]


class GlasgowConfig:
    """
    Glasgow EEPROM configuration data.

    :ivar int size:
        Total size of configuration block (currently 64).

    :ivar str[1] revision:
        Revision letter, ``A``-``Z``.

    :ivar str[16] serial:
        Serial number, in ISO 8601 format.

    :ivar int bitstream_size:
        Size of bitstream flashed to ICE_MEM, or 0 if there isn't one.

    :ivar bytes[16] bitstream_id:
        Opaque string that uniquely identifies bitstream functionality,
        but not necessarily any particular routing and placement.
        Only meaningful if ``bitstream_size`` is set.

    :ivar int[2] voltage_limit:
        Maximum allowed I/O port voltage, in millivolts.
    """
    size = 64
    _encoding = "<B16sI16s2H"

    def __init__(self, revision, serial, bitstream_size=0, bitstream_id=b"\x00"*16,
                 voltage_limit=None):
        self.revision = revision
        self.serial   = serial
        self.bitstream_size = bitstream_size
        self.bitstream_id   = bitstream_id
        self.voltage_limit  = [5500, 5500] if voltage_limit is None else voltage_limit

    @staticmethod
    def encode_revision(string):
        """
        Encode the human readable revision to the revision byte as used in the firmware.

        The revision byte encodes the letter ``X`` and digit ``N`` in ``revXN`` in the high and
        low nibble respectively. The high nibble is the letter (1 means ``A``) and the low nibble
        is the digit.
        """
        if re.match(r"^[A-Z][0-9]$", string):
            major, minor = string
            return ((ord(major) - ord("A") + 1) << 4) | (ord(minor) - ord("0"))
        else:
            raise ValueError("invalid revision string {!r}".format(string))

    @staticmethod
    def decode_revision(value):
        """
        Decode the revision byte as used in the firmware to the human readable revision.

        This inverts the transformation done by :meth:`encode_revision`.
        """
        major, minor = (value & 0xF0) >> 4, value & 0x0F
        if major == 0:
            return chr(ord("A") + minor - 1) + "0"
        elif minor in range(10):
            return chr(ord("A") + major - 1) + chr(ord("0") + minor)
        else:
            raise ValueError("invalid revision value {:#04x}".format(value))

    def encode(self):
        """
        Convert configuration to a byte array that can be loaded into memory or EEPROM.
        """
        data = struct.pack(self._encoding,
                           self.encode_revision(self.revision),
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
        return cls(cls.decode_revision(revision),
                   serial.decode("ascii"),
                   bitstream_size,
                   bitstream_id,
                   voltage_limit)
