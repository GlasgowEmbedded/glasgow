# Ref: JEDEC JESD3-C
# Accession: G00029

import re
from bitarray import bitarray


__all__ = ["JESD3Parser", "JESD3ParsingError"]


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
        (r"N",  r"[ \t\r\n]*(.*?)"),
        (r"D",  r".*?"),
        (r"QF", r"([0-9]+)"),
        (r"QP", r"([0-9]+)"),
        (r"QV", r"([0-9]+)"),
        (r"F",  r"([01])"),
        (r"L",  r"([0-9]+)[ \t\r\n]+([01 \t\r\n]+)"),
        (r"C",  r"([0-9A-F]{4})"),
        (r"EH", r"([0-9A-F]+)"),
        (r"E",  r"([01]+)"),
        (r"UA", r"([\t\r\n\x20-\x29\x2B-\x7E]+)"),
        (r"UH", r"([0-9A-F]+)"),
        (r"U",  r"([01]+)"),
        (r"J",  r"([0-9]+)[ \t\r\n]+([0-9]+)"),
        (r"G",  r"([01])"),
        (r"X",  r"([01])"),
        (r"P",  r"([ \t\r\n]*[0-9]+)+"),
        (r"V",  r"([0-9]+)[ \t\r\n]+([0-9BCDFHTUXZ]+)"),
        (r"S",  r"([01]+)"),
        (r"R",  r"([0-9A-F]{8})"),
        (r"T",  r"([0-9]+)"),
        (r"A",  r"([\t\r\n\x20-\x29\x2B-\x7E]*)([0-9]+)"),
    )
    _stx_spec_re  = re.compile(r"\x02(.*?)\*[ \t\r\n]*", re.A|re.S)
    _stx_quirk_re = re.compile(r"\x02()[ \t\r\n]*", re.A|re.S)
    _etx_re       = re.compile(r"\x03([0-9A-F]{4})", re.A|re.S)
    _ident_re     = re.compile(r"|".join(ident for ident, args in _fields), re.A|re.S)
    _field_res    = {ident: re.compile(ident + args + r"[ \t\r\n]*\*[ \t\r\n]*", re.A|re.S)
                     for ident, args in _fields}

    def __init__(self, buffer, quirk_no_design_spec=False):
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
        line = len(re.compile(r"\n").findall(self.buffer, endpos=self.position))
        if line > 1:
            column = self.position - self.buffer.rindex("\n", 0, self.position)
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
                token = "start"
                self._state = "fields"
                self.checksum += sum(map(ord, match.group(0)))

        elif self._state == "fields":
            match = self._ident_re.match(self.buffer, self.position)
            if match:
                token = match.group(0)
                match = self._field_res[token].match(self.buffer, self.position)
                if not match:
                    raise JESD3ParsingError("field %s has invalid format at line %d, column %d"
                                            % (token, *self.line_column()))
                else:
                    self.checksum += sum(map(ord, match.group(0)))

            else:
                match = self._etx_re.match(self.buffer, self.position)
                if not match:
                    raise JESD3ParsingError("unrecognized field at line %d, column %d (%r...)"
                                            % (*self.line_column(),
                                               self.buffer[self.position:self.position + 16]))
                else:
                    token = "end"
                    self._state = "end"
                    self.checksum += 0x03

        elif self._state == "end":
            raise StopIteration

        self.position = match.end()
        return token, match.start(), match.groups()


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
        self.fuse = bitarray(int(count, 10), endian="little")

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
        values = bitarray(re.sub(r"[ \r\n]", "", values), endian="little")
        if index + len(values) > len(self.fuse):
            self._parse_error("fuse list specifies range [%d:%d] beyond last fuse %d"
                              % (index, index + len(values), len(self.fuse)))
        self.fuse[index:index + len(values)] = values
        self._fuse_bit_count += len(values)

    def _on_C(self, checksum):
        """Fuse checksum"""
        expected_checksum = int(checksum, 16)
        actual_checksum   = sum(self.fuse.tobytes()) & 0xffff
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

        if self._fuse_default is not None and self._fuse_bit_count < len(self.fuse):
            self._parse_error("fuse default state is not specified, and only %d out of %d fuse "
                              "bits are explicitly defined"
                              % (self._fuse_bit_count, len(self.fuse)))


if __name__ == "__main__":
    import sys
    with open(sys.argv[1], "r") as f:
        parser = JESD3Parser(f.read(), quirk_no_design_spec=False)
        parser.parse()
        for i in range(0, len(parser.fuse) + 63, 64):
            print("%08x: %s" % (i, parser.fuse[i:i + 64].to01()))
