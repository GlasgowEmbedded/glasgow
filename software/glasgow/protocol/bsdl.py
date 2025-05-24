# Ref: IEEE 1149.1-2013 - IEEE Standard for Test Access Port and Boundary-Scan Architecture
# Accession: G00096

# This is not a good BSDL parser. This is fine, because BSDL is an absolutely atrocious format.
# This parser attempts to parse correct BSDL files right, and to provide some degree of error
# reporting for incorrect BSDL files (at a minimum, source locations), but it does absolutely no
# attempt at validating semantic correctness in the many edge cases BSDL has because this is a huge
# waste of time. Moreover, the semantic model contains only the features needed to use boundary
# scan for IC and board level reverse engineering; it does not attempt to capture the full breadth
# of what the BSDL format defines.
#
# This parser has been validated on a large test set of BSDL files from Xilinx, Lattice, Altera,
# other vendors.

from typing import Optional, Literal
from collections import defaultdict
from dataclasses import dataclass, KW_ONLY
import re

try:
    from ..support.bits import bits
except ImportError:
    bits = lambda value, length: value


__all__ = ["BSDLParseError", "BSDLPortInfo", "BSDLScanCell", "BSDLDevice", "BSDLEntity"]


class BSDLParseError(Exception):
    pass


@dataclass
class BSDLPortInfo:
    kind:  Literal["in", "out", "inout", "buffer", "linkage"]
    pins:  list[str]
    range: Optional[range]
    cells: list[int]


@dataclass
class BSDLScanCell:
    kind:     str
    port:     tuple[str, int]
    function: Literal["input", "output2", "output3", "control", "controlr", "internal",
                      "clock", "bidir", "observe_only"]
    safe:     Optional[int]

    control:  Optional[int] = None # index into cell list
    disable:  Optional[int] = None


@dataclass
class BSDLDevice:
    name:        str
    ports:       dict[str, BSDLPortInfo]

    ir_length:   int
    ir_values:   dict[str, bits]

    scan_cells: list[BSDLScanCell]

    @property
    def scan_length(self):
        return len(self.scan_cells)


@dataclass
class BSDLToken:
    kind:     str
    value:    str
    _:        KW_ONLY
    src_name: str
    source:   str
    offset:   int

    def __str__(self):
        line   = 1 + self.source.count("\n", 0, self.offset)
        column = self.offset - self.source.rfind("\n", 0, self.offset)
        return f"{self.kind} {self.value!r} at {self.src_name}, line {line}, column {column}"


class BSDLLexer:
    _KEYWORDS = """
    attribute bit_vector bit buffer constant end entity generic inout in is linkage of out port
    string to use
    """.split()

    _TOKENS = [
        ("wspace",   r"(?P<>[ \t\r\n]+)"),
        ("comment",  r"--(?P<>.*?)\r?\n"),
        ("punct",    r"(?P<>:=|[.,:;&*()])"),
        ("keyword",  rf"(?P<>{'|'.join(_KEYWORDS)})(?![a-z0-9_])"),
        ("integer",  r"(?P<>[x0-9]+)(?![a-z_])"),
        ("floating", r"(?P<>[0-9]+(\.[0-9]+|e[0-9]+|\.[0-9]+e[0-9]+))"),
        ("ident",    r"(?P<>[a-z_][a-z0-9_]*)"),
        ("string",   r"\"(?P<>[^\"]+)\""),
        ("illegal",  r"(?P<>.)"),
        ("end",      r"(?P<>$)")
    ]

    _REGEX = re.compile(
        "|".join(regex.replace("?P<>", f"?P<{name}>") for name, regex in _TOKENS),
        re.DOTALL | re.IGNORECASE
    )

    def __init__(self, source, src_name):
        self._src_name = src_name
        self._source   = source
        self._offset   = 0

    def __iter__(self):
        return self

    def __next__(self):
        if match := self._REGEX.match(self._source, self._offset):
            offset, self._offset = match.span(0)
            for name, regex in self._TOKENS:
                if (value := match[name]) is not None:
                    return BSDLToken(
                        name, value.upper(),
                        src_name=self._src_name, source=self._source, offset=offset
                    )
            assert False, f"unhandled match: {match}"
        assert False


class BSDLParserBase:
    def __init__(self, source, src_name):
        self._lexer = BSDLLexer(source, src_name)

    def _lex(self):
        for token in self._lexer:
            match token:
                case BSDLToken("wspace" | "comment", _):
                    pass
                case BSDLToken("illegal", _):
                    raise BSDLParseError(f"{token}")
                case _:
                    return token

    def _expect(self, kind, value=None):
        token = self._lex()
        match token:
            case BSDLToken(lex_kind, _) if lex_kind != kind:
                raise BSDLParseError(f"expected {kind}, got {token}")
            case BSDLToken(lex_kind, lex_value) if value is not None and lex_value != value:
                raise BSDLParseError(f"expected {kind} {value!r}, got {token}")
            case BSDLToken(_, lex_value):
                return lex_value


class BSDLPinMap(BSDLParserBase):
    def __init__(self, source, src_name):
        super().__init__(source, src_name)

        self._pins  = defaultdict(lambda: [])
        self._ports = {}

        self._parse()

    @property
    def pins(self) -> dict[str, list[str]]:
        """Mapping of port names to sequences of pin names."""
        return self._pins

    @property
    def ports(self) -> dict[str, tuple[str, int]]:
        """Mapping of pin names to tuples of a port name and an index within the port."""
        return self._ports

    def _add(self, port, pin):
        assert pin not in self._ports
        self._ports[pin] = (port, len(self._pins[port]))
        self._pins[port].append(pin)

    def _parse(self):
        while True:
            port = self._expect("ident")
            self._expect("punct", ":")
            match self._lex():
                case BSDLToken("ident" | "integer", pin):
                    self._add(port, pin)
                case BSDLToken("punct", "("):
                    while True:
                        match self._lex():
                            case BSDLToken("ident" | "integer", pin):
                                self._add(port, pin)
                            case token:
                                raise BSDLParseError(f"expected 'ident' or 'number', got {token}")
                        match self._lex():
                            case BSDLToken("punct", ","):
                                pass
                            case BSDLToken("punct", ")"):
                                break
                            case token:
                                raise BSDLParseError(f"expected ',' or ')', got {token}")
                case token:
                    raise BSDLParseError(f"expected pin or pin list, got {token}")
            match self._lex():
                case BSDLToken("punct", ","):
                    pass
                case BSDLToken("end", _):
                    break
                case token:
                    raise BSDLParseError(f"expected ',' or end of source, got {token}")


class BSDLOpcodeMap(BSDLParserBase):
    def __init__(self, source, src_name):
        super().__init__(source, src_name)

        self._opcodes = {}

        self._parse()

    @property
    def opcodes(self) -> dict[str, bits]:
        """Mapping of instruction names to opcodes."""
        return self._opcodes

    def _parse(self):
        while True:
            name = self._expect("ident")
            self._expect("punct", "(")
            opcode = self._expect("integer")
            match self._lex():
                case BSDLToken("punct", ")"):
                    self._opcodes[name] = bits(int(opcode, 2), len(opcode))
                case BSDLToken("punct", ","):
                    # The standard allows for multiple opcodes, but we just ignore the entire
                    # instruction in this case.
                    while True:
                        match self._lex():
                            case BSDLToken("punct", ")"):
                                break
            match self._lex():
                case BSDLToken("punct", ","):
                    pass
                case BSDLToken("end", _):
                    break
                case token:
                    raise BSDLParseError(f"expected ',' or end of source, got {token}")


class BSDLScanCellMap(BSDLParserBase):
    def __init__(self, source, src_name):
        super().__init__(source, src_name)

        self._cells = []

        self._parse()

    @property
    def cells(self) -> list[tuple[int, BSDLScanCell]]:
        """Mapping of cell indices to cells. Under certain circumstances, two cells may be assigned
        the same index; this is called a "merger"."""
        return self._cells

    def _parse(self):
        while True:
            index = int(self._expect("integer"))
            self._expect("punct", "(")
            kind = self._expect("ident")
            self._expect("punct", ",")
            match self._lex():
                case BSDLToken("punct", "*"):
                    port = None
                case BSDLToken("ident", port):
                    pass
                case token:
                    raise BSDLParseError(f"expected '*' or port name, got {token}")
            match self._lex():
                case BSDLToken("punct", "("):
                    port = (port, int(self._expect("integer")))
                    self._expect("punct", ")")
                    self._expect("punct", ",")
                case BSDLToken("punct", ","):
                    if port is not None:
                        port = (port, 0)
                case token:
                    raise BSDLParseError(f"expected ',' or port bit index, got {token}")
            match self._lex():
                case BSDLToken("ident", "INPUT" | "OUTPUT2" | "OUTPUT3" | "CONTROL" | "CONTROLR" |
                               "INTERNAL" | "CLOCK" | "BIDIR" | "OBSERVE_ONLY" as function):
                    function = function.lower()
                case token:
                    raise BSDLParseError(f"expected scan cell function, got {token}")
            self._expect("punct", ",")
            match self._lex():
                case BSDLToken("integer", "0" | "1" as safe):
                    safe = int(safe)
                case BSDLToken("integer", "X"):
                    safe = None
                case token:
                    raise BSDLParseError(f"expected a single bit, got {token}")
            match self._lex():
                case BSDLToken("punct", ")"):
                    cell = BSDLScanCell(kind, port, function, safe)
                case BSDLToken("punct", ","):
                    control = int(self._expect("integer"))
                    self._expect("punct", ",")
                    disable = int(self._expect("integer"))
                    self._expect("punct", ",")
                    disable_result = self._expect("ident")
                    self._expect("punct", ")")
                    cell = BSDLScanCell(kind, port, function, safe, control, disable)
                case token:
                    raise BSDLParseError(f"expected ',' or ')', got {token}")
            self._cells.append((index, cell))
            match self._lex():
                case BSDLToken("punct", ","):
                    pass
                case BSDLToken("end", _):
                    break
                case token:
                    raise BSDLParseError(f"expected ',' or end of source, got {token}")


class BSDLEntity(BSDLParserBase):
    def __init__(self, source, src_name):
        super().__init__(source, src_name)

        self._name   = None
        self._params = {}
        self._ports  = {}
        self._attrs  = {}
        self._consts = {}

        self._parse()

    def _parse_entity(self):
        self._name = self._expect("ident")
        self._expect("keyword", "IS")
        self._expect("keyword", "GENERIC")
        self._expect("punct", "(")
        while True:
            param = self._expect("ident")
            self._expect("punct", ":")
            self._expect("keyword", "STRING")
            self._expect("punct", ":=")
            value = self._expect("string")
            self._params[param] = value
            match self._lex():
                case BSDLToken("punct", ";"):
                    pass
                case BSDLToken("punct", ")"):
                    break
                case token:
                    raise BSDLParseError(f"expected ';' or ')', got {token}")
        self._expect("punct", ";")

    def _parse_port_list(self):
        self._expect("punct", "(")
        while True:
            names = [self._expect("ident")]
            while True:
                match self._lex():
                    case BSDLToken("punct", ","):
                        names.append(self._expect("ident"))
                    case BSDLToken("punct", ":"):
                        break
            match self._lex():
                case BSDLToken("keyword", "IN" | "OUT" | "INOUT" | "BUFFER" | "LINKAGE" as kind):
                    kind = kind.lower()
                case token:
                    raise BSDLParseError(f"expected port direction, got {token}")
            match self._lex():
                case BSDLToken("keyword", "BIT"):
                    range_ = range(1, 2)
                case BSDLToken("keyword", "BIT_VECTOR"):
                    self._expect("punct", "(")
                    start = int(self._expect("integer"))
                    self._expect("keyword", "TO")
                    stop = int(self._expect("integer"))
                    range_ = range(start, stop + 1)
                    self._expect("punct", ")")
                case token:
                    raise BSDLParseError(f"expected port type, got {token}")
            for name in names:
                self._ports[name] = (kind, range_)
            match self._lex():
                case BSDLToken("punct", ";"):
                    pass
                case BSDLToken("punct", ")"):
                    break
                case token:
                    raise BSDLParseError(f"expected ';' or ')', got {token}")
        self._expect("punct", ";")

    def _parse_value(self):
        match self._lex():
            case BSDLToken("ident", param):
                value = self._params[param]
                self._expect("punct", ";")
            case BSDLToken("string", value):
                while True:
                    match self._lex():
                        case BSDLToken("punct", "&"):
                            pass
                        case BSDLToken("string", part):
                            value += part
                        case BSDLToken("punct", ";"):
                            return value
                        case token:
                            raise BSDLParseError(f"expected value, got {token}")
            case BSDLToken("integer", value):
                value = int(value)
                self._expect("punct", ";")
            case token:
                raise BSDLParseError(f"expected value, got {token}")
        return value

    def _parse_attribute(self):
        name = self._expect("ident")
        self._expect("keyword", "OF")
        target = self._expect("ident")
        if target != self._name:
            while True:
                match self._lex():
                    case BSDLToken("punct", ";"):
                        return
        self._expect("punct", ":")
        self._expect("keyword", "ENTITY")
        self._expect("keyword", "IS")
        value = self._parse_value()
        self._attrs[name] = value

    def _parse_constant(self):
        name = self._expect("ident")
        self._expect("punct", ":")
        self._expect("ident", "PIN_MAP_STRING")
        self._expect("punct", ":=")
        value = self._parse_value()
        self._consts[name] = value

    def _parse(self):
        while True:
            match self._lex():
                case BSDLToken("keyword", "ENTITY"):
                    self._parse_entity()
                case BSDLToken("keyword", "PORT"):
                    self._parse_port_list()
                case BSDLToken("keyword", "USE"):
                    while True:
                        match self._lex():
                            case BSDLToken("punct", ";"):
                                break
                case BSDLToken("keyword", "ATTRIBUTE"):
                    self._parse_attribute()
                case BSDLToken("keyword", "CONSTANT"):
                    self._parse_constant()
                case BSDLToken("keyword", "END"):
                    entity = self._expect("ident")
                    break
                case token:
                    raise BSDLParseError(f"cannot parse {token}")

    def _extract_attribute(self, name):
        if name not in self._attrs:
            raise BSDLParseError(f"expected {name!r} attribute to be defined")
        return self._attrs[name]

    def _extract_constant(self, name):
        if name not in self._consts:
            raise BSDLParseError(f"expected {name!r} constant to be defined")
        return self._consts[name]

    def device(self) -> BSDLDevice:
        pin_map_name = self._extract_attribute("PIN_MAP")
        pin_map = BSDLPinMap(self._extract_constant(pin_map_name),
                             f"{pin_map_name}: PIN_MAP_STRING")

        ir_length = self._extract_attribute("INSTRUCTION_LENGTH")
        opcode_map = BSDLOpcodeMap(self._extract_attribute("INSTRUCTION_OPCODE"),
                                   "INSTRUCTION_OPCODE")

        port_cells = defaultdict(lambda: set())
        bscan_cells = [None] * self._extract_attribute("BOUNDARY_LENGTH")
        bscan_cell_map = BSDLScanCellMap(self._extract_attribute("BOUNDARY_REGISTER"),
                                         "BOUNDARY_REGISTER")
        for index, cell in bscan_cell_map.cells:
            assert bscan_cells[index] is None
            bscan_cells[index] = cell
            if cell.port is not None:
                port, port_bit = cell.port
                port_cells[port].add(index)

        return BSDLDevice(
            name=self._name,
            ports={
                port: BSDLPortInfo(
                    kind=kind,
                    pins=pin_map._pins[port],
                    range=range_,
                    cells=port_cells[port]
                )
                for port, (kind, range_) in self._ports.items()
            },
            ir_length=ir_length,
            ir_values=opcode_map.opcodes,
            scan_cells=bscan_cells,
        )


if __name__ == "__main__":
    import sys, pprint
    with open(sys.argv[1], "r") as file:
        pprint.pp(BSDLEntity(file.read(), file.name).device())
