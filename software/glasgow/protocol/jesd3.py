# Ref: JEDEC JESD3-C
# Accession: G00029

import re
from glasgow.support.bits import bits, bitarray


__all__ = ["JESD3Parser", "JESD3ParsingError", "JESD3Emitter"]


class JESD3ParsingError(Exception):
    pass


class JESD3Lexer:
    """
    A JESD3 (JED) lexer.

    :type buffer: str
    :attr buffer:
        Input buffer.

    :type position: int
    :attr position:
        Offset into buffer from which the next field will be read.
    """

    # This follows the JESD3-C grammar, with the exception that spaces are more permissive.
    # As described, only 0x0D is allowed in between fields, which is absurd.
    _fields = (
        (rb"N",  rb"[ \t\r\n]*(.*?)"),
        (rb"D",  rb".*?"),
        (rb"QF", rb"([0-9]+)"),
        (rb"QP", rb"([0-9]+)"),
        (rb"QV", rb"([0-9]+)"),
        (rb"F",  rb"([01])"),
        (rb"L",  rb"([0-9]+)[ \t\r\n]+([01 \t\r\n]+)"),
        (rb"C",  rb"([0-9A-F]{4})"),
        (rb"EH", rb"([0-9A-F]+)"),
        (rb"E",  rb"([01]+)"),
        (rb"UA", rb"([\t\r\n\x20-\x29\x2B-\x7E]+)"),
        (rb"UH", rb"([0-9A-F]+)"),
        (rb"U",  rb"([01]+)"),
        (rb"J",  rb"([0-9]+)[ \t\r\n]+([0-9]+)"),
        (rb"G",  rb"([01])"),
        (rb"X",  rb"([01])"),
        (rb"P",  rb"([ \t\r\n]*[0-9]+)+"),
        (rb"V",  rb"([0-9]+)[ \t\r\n]+([0-9BCDFHTUXZ]+)"),
        (rb"S",  rb"([01]+)"),
        (rb"Rb",  rb"([0-9A-F]{8})"),
        (rb"T",  rb"([0-9]+)"),
        (rb"A",  rb"([\t\r\n\x20-\x29\x2B-\x7E]*)([0-9]+)"),
    )
    _stx_spec_re  = re.compile(rb"\x02(.*?)\*[ \t\r\n]*", re.A|re.S)
    _stx_quirk_re = re.compile(rb"\x02()[ \t\r\n]*", re.A|re.S)
    _etx_re       = re.compile(rb"\x03([0-9A-F]{4})", re.A|re.S)
    _ident_re     = re.compile(rb"|".join(ident for ident, args in _fields), re.A|re.S)
    _field_res    = {ident: re.compile(ident + args + rb"[ \t\r\n]*\*[ \t\r\n]*", re.A|re.S)
                     for ident, args in _fields}

    def __init__(self, buffer, quirk_no_design_spec=False):
        if not isinstance(buffer, (bytes, bytearray)):
            raise ValueError(f"JESD3 lexer requires bytes or bytearray as input, not {type(buffer)}")

        self.buffer   = buffer
        self.position = 0
        self.checksum = 0
        self._state   = "start"
        if quirk_no_design_spec:
            self._stx_re = self._stx_quirk_re
        else:
            self._stx_re = self._stx_spec_re

    def line_column(self, position=None):
        """
        Return a ``(line, column)`` tuple for the given or, if not specified, current position.

        Both the line and the column start at 1.
        """
        line = len(re.compile(rb"\n").findall(self.buffer, endpos=self.position))
        if line > 1:
            column = self.position - self.buffer.rindex(b"\n", 0, self.position)
        else:
            column = self.position
        return line + 1, column + 1

    def __iter__(self):
        return self

    def __next__(self):
        """Return the next token and advance the position."""
        if self._state == "start":
            match = self._stx_re.search(self.buffer, self.position)
            if not match:
                raise JESD3ParsingError("could not find STX marker")
            else:
                token = b"start"
                self._state = "fields"
                self.checksum += sum(match.group(0))

        elif self._state == "fields":
            match = self._ident_re.match(self.buffer, self.position)
            if match:
                token = match.group(0)
                match = self._field_res[token].match(self.buffer, self.position)
                if not match:
                    raise JESD3ParsingError("field %s has invalid format at line %d, column %d"
                                            % (token, *self.line_column()))
                else:
                    self.checksum += sum(match.group(0))

            else:
                match = self._etx_re.match(self.buffer, self.position)
                if not match:
                    raise JESD3ParsingError("unrecognized field at line %d, column %d (%r...)"
                                            % (*self.line_column(),
                                               self.buffer[self.position:self.position + 16]))
                else:
                    token = b"end"
                    self._state = "end"
                    self.checksum += 0x03

        elif self._state == "end":
            raise StopIteration

        self.position = match.end()
        return token.decode("ascii"), match.start(), match.groups()


class JESD3Parser:
    def __init__(self, buffer, **kwargs):
        self._lexer    = JESD3Lexer(buffer, **kwargs)
        self._position = 0

        self.design_spec     = ""
        self.notes           = []
        self.fuse            = None
        self._fuse_default   = None
        self._fuse_bit_count = 0
        self.electrical_fuse = None
        self.user_fuse       = None
        self.security_fuse   = None
        self.device_id       = None

    def _parse_error(self, error):
        raise JESD3ParsingError("%s at line %d, column %d"
                                % (error, *self._lexer.line_column(self._position)))

    def parse(self):
        for token, position, args in self._lexer:
            self._position = position
            # print("lexem: %r %r" % (token, args))
            getattr(self, "_on_" + token)(*args)

    def _on_start(self, design_spec):
        """Start marker and design specification"""
        self.design_spec = design_spec

    def _on_N(self, note):
        """Note"""
        self.notes.append(note)

    def _on_D(self):
        """Device (obsolete)"""

    def _on_QF(self, count):
        """Fuse count"""
        if self.fuse is not None:
            self._parse_error("fuse count specified more than once")
        self.fuse = bitarray(0, int(count, 10))

    def _on_QP(self, count):
        """Pin count (unsupported and ignored)"""

    def _on_QV(self, count):
        """Test vector count (unsupported)"""
        if int(count, 10) > 0:
            self._parse_error("test vectors are unsupported")

    def _on_F(self, state):
        """Fuse default state"""
        if self.fuse is None:
            self._parse_error("fuse default state specified before fuse count")
        if self._fuse_default is not None:
            self._parse_error("fuse default state specified more than once")
        if self._fuse_bit_count > 0:
            self._parse_error("fuse default state specified after fuse list")
        self._fuse_default = int(state, 2)
        self.fuse.setall(self._fuse_default)

    def _on_L(self, index, values):
        """Fuse list"""
        if self.fuse is None:
            self._parse_error("fuse list specified before fuse count")
        index  = int(index, 10)
        values = bits(values[::-1].decode("ascii"))
        if index + len(values) > len(self.fuse):
            self._parse_error("fuse list specifies range [%d:%d] beyond last fuse %d"
                              % (index, index + len(values), len(self.fuse)))
        self.fuse[index:index + len(values)] = values
        self._fuse_bit_count += len(values)

    def _on_C(self, checksum):
        """Fuse checksum"""
        expected_checksum = int(checksum, 16)
        actual_checksum   = sum(self.fuse.to_bytes()) & 0xffff
        if expected_checksum != actual_checksum:
            self._parse_error("fuse checksum mismatch: expected %04X, actual %04X"
                              % (expected_checksum, actual_checksum))

    def _set_electrical_fuse(self, value):
        if self.electrical_fuse is not None:
            self._parse_error("electrical fuse specified more than once")
        self.electrical_fuse = value

    def _on_EH(self, value):
        """Electrical fuse, hex"""
        self._set_electrical_fuse(int(value, 16))

    def _on_E(self, value):
        """Electrical fuse, binary"""
        self._set_electrical_fuse(int(value, 2))

    def _set_user_fuse(self, value):
        if self.user_fuse is not None:
            self._parse_error("user fuse specified more than once")
        self.user_fuse = value

    def _on_UA(self, value):
        """User fuse, 7-bit ASCII"""
        int_value = 0
        for char in reversed(value):
            int_value <<= 7
            int_value |= ord(char)
        self._set_user_fuse(int_value)

    def _on_UH(self, value):
        """User fuse, hex"""
        self._set_user_fuse(int(value, 16))

    def _on_U(self, value):
        """User fuse, binary"""
        self._set_user_fuse(int(value, 2))

    def _on_J(self, arch_code, pinout_code):
        """Device identification"""
        if self.device_id is not None:
            self._parse_error("device identification specified more than once")
        self.device_id = (int(arch_code, 10), int(pinout_code, 10))

    def _on_G(self, value):
        """Security fuse"""
        if self.security_fuse is not None:
            self._parse_error("security fuse specified more than once")
        self.security_fuse = int(value, 2)

    def _on_X(self, value):
        """Default test condition (unsupported and ignored)"""

    def _on_P(self, pin_numbers):
        """Pin list (unsupported and ignored)"""

    def _on_V(self, vector_number, test_conditions):
        """Test vector (unsupported and ignored)"""

    def _on_S(self, test_condition):
        """Signature analysis starting vector (unsupported)"""
        self._parse_error("signature analysis is not supported")

    def _on_R(self, test_sum):
        """Signature analysis resulting vector (unsupported and ignored)"""

    def _on_T(self, test_cycles):
        """Signature analysis test cycle count (unsupported and ignored)"""

    def _on_A(self, subfield, delay):
        """Propagation delay for test vectors (unsupported and ignored)"""

    def _on_end(self, checksum):
        """End marker and checksum"""
        expected_checksum = int(checksum, 16)
        if expected_checksum == 0x0000:
            return
        actual_checksum   = self._lexer.checksum & 0xffff
        if expected_checksum != actual_checksum:
            self._parse_error("transmission checksum mismatch: expected %04X, actual %04X"
                              % (expected_checksum, actual_checksum))

        if self._fuse_default is None and self._fuse_bit_count < len(self.fuse):
            self._parse_error("fuse default state is not specified, and only %d out of %d fuse "
                              "bits are explicitly defined"
                              % (self._fuse_bit_count, len(self.fuse)))


class JESD3Emitter:
    def __init__(self, fuses, *, quirk_no_design_spec=False):
        if not isinstance(fuses, (bits, bitarray)):
            raise TypeError("JESD3Emitter needs a bits or bitarray instance")
        self.fuses = fuses
        self.quirk_no_design_spec = quirk_no_design_spec
        self.comments = []

    def add_comment(self, comment):
        self.comments.append(comment)

    def emit(self):
        buffer = bytearray()
        if self.quirk_no_design_spec:
            buffer += b"\x02"
        else:
            buffer += b"\x02*\n"
        buffer += b"QF%d*\n" % len(self.fuses)
        buffer += b"F0*\n"
        for comment in self.comments:
            buffer += b"N " + comment + b"*\n"
        for pos in range(0, len(self.fuses), 64):
            chunk = self.fuses[pos:pos+64]
            buffer += b"L%07d " % pos
            for bit in chunk:
                buffer += b"%d" % bit
            buffer += b"*\n"
        buffer += b"C%04X*\n" % (sum(self.fuses.to_bytes()) & 0xffff)
        buffer += b"\x03"
        checksum = sum(buffer) & 0xffff
        buffer += b"%04X" % checksum
        return bytes(buffer)


if __name__ == "__main__":
    import sys
    with open(sys.argv[1], "rb") as f:
        parser = JESD3Parser(f.read(), quirk_no_design_spec=False)
        parser.parse()
        for i in range(0, len(parser.fuse) + 63, 64):
            print(f"{i:08x}: {parser.fuse[i:i + 64]}")
