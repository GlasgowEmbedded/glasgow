# Ref: JEDEC JESD3-C
# Accession: G00029

from bitarray import bitarray


__all__ = ["JEDParser"]


class JEDParsingError(Exception):
    pass


class JEDParser:
    def __init__(self, buffer):
        try:
            self.header, buffer = buffer.split("\x02", 1)
        except ValueError:
            raise JEDParsingError("Could not find STX marker")
        try:
            buffer, trailer = buffer.split("\x03", 1)
        except ValueError:
            raise JEDParsingError("Could not find ETX marker")

        checksum, self.trailer = trailer[:4], trailer[4:]

        expected_checksum = "%04X" % ((5 + sum(ord(i) for i in buffer)) & 0xffff)

        if checksum.upper() != expected_checksum and checksum != "0000":
            raise JEDParsingError("Incorrect checksum: expected %r, got %r" % (
                expected_checksum, checksum))

        self._parse(buffer)

    def _parse(self, buffer):
        self.notes = []
        self.bits = None
        self.pin_count = None
        self.fuse_count = None
        self.test_vector_count = None
        self.fuse_default_state = 0
        self.electrical_fuse = None
        self.user_fuse = None
        self.security_fuse = None
        self.device_id = None

        fields = buffer.split("*")
        # The spec says that the first field has no identifier and is free text.
        # However, Xilinx violates the spec and starts immediately with a field
        # with an identifier. Therefore, we try to parse everything. If we come
        # across a JED file that actually follows the spec and includes a
        # non-empty free text field here, we'll have to add some heuristic
        # to ignore it...

        if fields[-1].strip():
            raise JEDParsingError("Junk after the final field terminator")

        have_data = False

        for field in fields[:-1]:
            field = field.strip()
            if not field:
                continue

            ident = field[0]
            if ident == "N": # Note
                self.notes.append(field[1:])
            elif ident == "D": # Device, obsolete
                pass
            elif ident == "Q":
                if field[1] == "F":
                    if self.fuse_count is not None:
                        raise JEDParsingError("Duplicate QF field")
                    self.fuse_count = int(field[2:])
                    self.bits = bitarray(self.fuse_count, endian="little")
                    self.bits.setall(self.fuse_default_state)
                elif field[1] == "P":
                    self.pin_count = int(field[2:])
                elif field[1] == "V":
                    self.test_vector_count = int(field[2:])
                else:
                    raise JEDParsingError("Unknown field %s" % field[:2])
            elif ident == "F": # Fuse default state"
                if have_data:
                    raise JEDParsingError("F field found after L field(s)")
                self.fuse_default_state = int(field[1:])
                if self.bits is not None:
                    self.bits.setall(self.fuse_default_state)
            elif ident == "L": # Fuse list
                try:
                    address, data = field[1:].split(None, 1)
                    address = int(address)
                    data = "".join(data.split())
                except ValueError:
                    raise JEDParsingError("Invalid L field: %r" % field)

                if data.replace("0", "").replace("1", ""):
                    raise JEDParsingError("Invalid L field: %r" % field)

                if not self.bits:
                    raise JEDParsingError("L field before QF field")

                if address < 0 or (address + len(data)) > self.fuse_count:
                    raise JEDParsingError("Fuse address out of range: %d+%d (max %d bits)" % address, len(data), self.fuse_count)

                self.have_data = True
                self.bits[address:address + len(data)] = bitarray(data, endian="little")
            elif ident == "C": # Fuse checksum
                checksum = field[1:].strip().upper()
                expected_checksum = "%02X" % (sum(self.bits.tobytes()) & 0xffff)
                if checksum != expected_checksum:
                    raise JEDParsingError("Incorrect fuse checksum: expected %r, got %r" % (
                        expected_checksum, checksum))
            elif ident == "E": # Electrical fuse
                try:
                    if field[1:2] == "H":
                        self.electrical_fuse = int(field[2:].strip(), 16)
                    else:
                        self.electrical_fuse = int(field[1:], 2)
                except ValueError:
                    raise JEDParsingError("Invalid H field: %r" % field)
            elif ident == "U": # User fuse
                try:
                    if field[1:2] == "H":
                        self.user_fuse = int(field[2:].strip(), 16)
                    if field[1:2] == "A":
                        self.user_fuse = 0
                        # 7-bit ASCII...
                        for c in field[-1:1:-1]:
                            self.user_fuse <<= 7
                            self.user_fuse |= ord(c)
                    else:
                        self.user_fuse = int(field[1:], 2)
                except ValueError:
                    raise JEDParsingError("Invalid U field: %r" % field)
            elif ident == "J": # Device ID
                try:
                    arch_code, pinout_code = field[1:].strip().split()
                    self.device_id = int(arch_code), int(pinout_code)
                except ValueError:
                    raise JEDParsingError("Invalid J field: %r" % field)
            elif ident in "XPV": # Test vectors, not supported yet
                pass
            elif ident == "G": # Security fuse
                try:
                    self.security_fuse = int(field[1:], 2)
                except ValueError:
                    raise JEDParsingError("Invalid G field: %r" % field)
            elif ident in "SRT": # Signature analysis, not supported yet
                pass
            elif ident == "A": # Access time, not supported yet
                pass
            else:
                raise JEDParsingError("Invalid field: %r" % field)

if __name__ == "__main__":
    import sys
    with open(sys.argv[1], "r") as f:
        bits = JEDParser(f.read()).bits
        for i in range(0, len(bits) + 63, 64):
            print("%08x: %s" % (i, bits[i:i + 64].to01()))
