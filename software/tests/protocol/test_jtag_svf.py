import re
import unittest

from glasgow.support.bits import *
from glasgow.protocol.jtag_svf import SVFLexer, SVFParser, SVFParsingError


class SVFLexerTestCase(unittest.TestCase):
    def assertLexes(self, source, tokens):
        self.lexer = SVFLexer(source)
        self.assertEqual(list(self.lexer), tokens)

    def test_eof(self):
        self.assertLexes("", [])

    def test_comment(self):
        self.assertLexes("!foo",
                         [])
        self.assertLexes("//foo",
                         [])
        self.assertLexes("//foo\n!bar\n",
                         [])
        self.assertLexes("//foo\n!bar\nTRST",
                         ["TRST"])

    def test_keyword(self):
        self.assertLexes("TRST",
                         ["TRST"])
        self.assertLexes("TRST OFF;",
                         ["TRST", "OFF", ";"])

    def test_integer(self):
        self.assertLexes("8",       [8])
        self.assertLexes("12",      [12])

    def test_real(self):
        self.assertLexes("1E6",     [1e6])
        self.assertLexes("1E+6",    [1e6])
        self.assertLexes("1E-6",    [1e-6])
        self.assertLexes("1.1E6",   [1.1e6])
        self.assertLexes("1.1",     [1.1])

    def test_bits(self):
        self.assertLexes("(0)",        [bits("")])
        self.assertLexes("(1)",        [bits("1")])
        self.assertLexes("(F)",        [bits("1111")])
        self.assertLexes("(f)",        [bits("1111")])
        self.assertLexes("(0F)",       [bits("1111")])
        self.assertLexes("(A\n5)",     [bits("10100101")]) # Test literals split over two lines
        self.assertLexes("(A\n\t5)",   [bits("10100101")]) # With potential whitespace
        self.assertLexes("(A\n  5)",   [bits("10100101")])
        self.assertLexes("(A\r\n5)",   [bits("10100101")]) # Support both LF & LFCR
        self.assertLexes("(A\r\n\t5)", [bits("10100101")])
        self.assertLexes("(A\r\n  5)", [bits("10100101")])
        self.assertLexes("(FF)",       [bits("11111111")])
        self.assertLexes("(1AA)",      [bits("110101010")])

    def test_literal(self):
        self.assertLexes("(HHZZL)",     [("HHZZL",)])
        self.assertLexes("(IN FOO)",    [("IN FOO",)])

    def test_error(self):
        with self.assertRaises(SVFParsingError):
            SVFLexer("XXX").next()


class SVFMockEventHandler:
    def __init__(self):
        self.events = []

    def __getattr__(self, name):
        if name.startswith("svf_"):
            def svf_event(**kwargs):
                self.events.append((name, kwargs))
            return svf_event
        else:
            return super().__getattr__(name)


class SVFParserTestCase(unittest.TestCase):
    def setUp(self):
        self.maxDiff = None

    def assertParses(self, source, events):
        self.handler = SVFMockEventHandler()
        self.parser = SVFParser(source, self.handler)
        self.parser.parse_file()
        self.assertEqual(self.handler.events, events)

    def assertErrors(self, source, error):
        with self.assertRaisesRegex(SVFParsingError, fr"^{re.escape(error)}"):
            self.handler = SVFMockEventHandler()
            self.parser = SVFParser(source, self.handler)
            self.parser.parse_file()

    def test_frequency(self):
        self.assertParses("FREQUENCY;",
                          [("svf_frequency", {"frequency": None})])
        self.assertParses("FREQUENCY 1E6 HZ;",
                          [("svf_frequency", {"frequency": 1e6})])
        self.assertParses("FREQUENCY 1000 HZ;",
                          [("svf_frequency", {"frequency": 1000})])

        self.assertErrors("FREQUENCY 1E6;",
                          "expected HZ")

    def test_trst(self):
        self.assertParses("TRST ON;",
                          [("svf_trst", {"mode": "ON"})])
        self.assertParses("TRST OFF;",
                          [("svf_trst", {"mode": "OFF"})])
        self.assertParses("TRST Z;",
                          [("svf_trst", {"mode": "Z"})])
        self.assertParses("TRST ABSENT;",
                          [("svf_trst", {"mode": "ABSENT"})])

        self.assertErrors("TRST HZ;",
                          "expected TRST mode")

    def test_state(self):
        self.assertParses("STATE IDLE;",
                          [("svf_state", {"state": "IDLE", "path": []})])
        self.assertParses("STATE IRUPDATE IDLE;",
                          [("svf_state", {"state": "IDLE", "path": ["IRUPDATE"]})])
        self.assertParses("STATE IREXIT2 IRUPDATE IDLE;",
                          [("svf_state", {"state": "IDLE", "path": ["IREXIT2", "IRUPDATE"]})])

        self.assertErrors("STATE;",
                          "at least one state required")
        self.assertErrors("STATE IRSHIFT;",
                          "last state must be a stable state")
        self.assertErrors("STATE RESET IRSHIFT;",
                          "last state must be a stable state")

    def test_endir_enddr(self):
        for command, event in [
            ("ENDIR", "svf_endir"),
            ("ENDDR", "svf_enddr")
        ]:
            self.assertParses(f"{command} IRPAUSE;",
                              [(event, {"state": "IRPAUSE"})])

            self.assertErrors(f"{command} IRSHIFT;",
                              "expected stable TAP state")
            self.assertErrors(f"{command};",
                              "expected stable TAP state")

    def test_hir_sir_tir_hdr_sdr_tdr(self):
        for command, event in [
            ("HIR", "svf_hir"),
            ("SIR", "svf_sir"),
            ("TIR", "svf_tir"),
            ("HDR", "svf_hdr"),
            ("SDR", "svf_sdr"),
            ("TDR", "svf_tdr"),
        ]:
            self.assertParses(f"{command} 0;", [
                (event, {
                    "tdi":   bits(""),
                    "smask": bits(""),
                    "tdo":   None,
                    "mask":  bits(""),
                }),
            ])
            self.assertParses(f"{command} 8 TDI(a);", [
                (event, {
                    "tdi":   bits("00001010"),
                    "smask": bits("11111111"),
                    "tdo":   None,
                    "mask":  bits("00000000"),
                }),
            ])
            self.assertParses(f"{command} 6 TDI(0a);", [
                (event, {
                    "tdi":   bits("001010"),
                    "smask": bits("111111"),
                    "tdo":   None,
                    "mask":  bits("000000"),
                }),
            ])
            self.assertParses("{c} 8 TDI(a); {c} 8;".format(c=command), [
                (event, {
                    "tdi":   bits("00001010"),
                    "smask": bits("11111111"),
                    "tdo":   None,
                    "mask":  bits("00000000"),
                }),
                (event, {
                    "tdi":   bits("00001010"),
                    "smask": bits("11111111"),
                    "tdo":   None,
                    "mask":  bits("00000000"),
                }),
            ])
            self.assertParses("{c} 8 TDI(a) SMASK(3); {c} 8; {c} 12 TDI(b);"
                              .format(c=command), [
                (event, {
                    "tdi":   bits("00001010"),
                    "smask": bits("00000011"),
                    "tdo":   None,
                    "mask":  bits("00000000"),
                }),
                (event, {
                    "tdi":   bits("00001010"),
                    "smask": bits("00000011"),
                    "tdo":   None,
                    "mask":  bits("00000000"),
                }),
                (event, {
                    "tdi":   bits("000000001011"),
                    "smask": bits("111111111111"),
                    "tdo":   None,
                    "mask":  bits("000000000000"),
                }),
            ])
            self.assertParses("{c} 8 TDI(0) TDO(a) MASK(3); {c} 8; "
                              "{c} 8 TDO(1); {c} 12 TDI(0) TDO(b);"
                              .format(c=command), [
                (event, {
                    "tdi":   bits("00000000"),
                    "smask": bits("11111111"),
                    "tdo":   bits("00001010"),
                    "mask":  bits("00000011"),
                }),
                (event, {
                    "tdi":   bits("00000000"),
                    "smask": bits("11111111"),
                    "tdo":   None,
                    "mask":  bits("00000000"),
                }),
                (event, {
                    "tdi":   bits("00000000"),
                    "smask": bits("11111111"),
                    "tdo":   bits("00000001"),
                    "mask":  bits("00000011"),
                }),
                (event, {
                    "tdi":   bits("000000000000"),
                    "smask": bits("111111111111"),
                    "tdo":   bits("000000001011"),
                    "mask":  bits("111111111111"),
                }),
            ])

            self.assertErrors(f"{command} 8 TDI(aaa);",
                              "scan data length 12 exceeds command length 8")
            self.assertErrors(f"{command} 8 TDI(0) TDI(0);",
                              "parameter TDI specified twice")
            self.assertErrors(f"{command} 8;",
                              "initial value for parameter TDI required")
            self.assertErrors("{c} 8 TDI(aa); {c} 12;".format(c=command),
                              "parameter TDI needs to be specified again because "
                              "the length changed")

    def test_runtest(self):
        self.assertParses("RUNTEST 20000 TCK;", [
            ("svf_runtest", {
                "run_state": "IDLE",  "run_count": 20000, "run_clock": "TCK",
                "min_time":  None,    "max_time":  None,  "end_state": "IDLE"
            }),
        ])
        self.assertParses("RUNTEST 20000 TCK 1E3 SEC;", [
            ("svf_runtest", {
                "run_state": "IDLE",  "run_count": 20000, "run_clock": "TCK",
                "min_time":  1e3,     "max_time":  None,  "end_state": "IDLE"
            }),
        ])
        self.assertParses("RUNTEST 20000 TCK 1E3 SEC MAXIMUM 1E6 SEC;", [
            ("svf_runtest", {
                "run_state": "IDLE",  "run_count": 20000, "run_clock": "TCK",
                "min_time":  1e3,     "max_time":  1e6,   "end_state": "IDLE"
            }),
        ])
        self.assertParses("RUNTEST 20000 TCK 1E3 SEC MAXIMUM 1E6 SEC ENDSTATE RESET;", [
            ("svf_runtest", {
                "run_state": "IDLE",  "run_count": 20000, "run_clock": "TCK",
                "min_time":  1e3,     "max_time":  1e6,   "end_state": "RESET"
            }),
        ])
        self.assertParses("RUNTEST 20000 TCK 1E3 SEC MAXIMUM 1E6 SEC ENDSTATE RESET;", [
            ("svf_runtest", {
                "run_state": "IDLE",  "run_count": 20000, "run_clock": "TCK",
                "min_time":  1e3,     "max_time":  1e6,   "end_state": "RESET"
            }),
        ])
        self.assertParses("RUNTEST 20000 TCK ENDSTATE RESET; RUNTEST 100 TCK;", [
            ("svf_runtest", {
                "run_state": "IDLE",  "run_count": 20000, "run_clock": "TCK",
                "min_time":  None,    "max_time":  None,  "end_state": "RESET"
            }),
            ("svf_runtest", {
                "run_state": "IDLE",  "run_count": 100,   "run_clock": "TCK",
                "min_time":  None,    "max_time":  None,  "end_state": "RESET"
            }),
        ])
        self.assertParses("RUNTEST RESET 20000 TCK ENDSTATE RESET; RUNTEST IDLE 100 TCK;", [
            ("svf_runtest", {
                "run_state": "RESET", "run_count": 20000, "run_clock": "TCK",
                "min_time":  None,    "max_time":  None,  "end_state": "RESET"
            }),
            ("svf_runtest", {
                "run_state": "IDLE",  "run_count": 100,   "run_clock": "TCK",
                "min_time":  None,    "max_time":  None,  "end_state": "IDLE"
            }),
        ])

        self.assertParses("RUNTEST 20000 SCK;", [
            ("svf_runtest", {
                "run_state": "IDLE",  "run_count": 20000, "run_clock": "SCK",
                "min_time":  None,    "max_time":  None,  "end_state": "IDLE"
            }),
        ])

        self.assertParses("RUNTEST 1 SEC;", [
            ("svf_runtest", {
                "run_state": "IDLE",  "run_count": None,  "run_clock": "TCK",
                "min_time":  1,       "max_time":  None,  "end_state": "IDLE"
            }),
        ])
        self.assertParses("RUNTEST 1 SEC MAXIMUM 2 SEC;", [
            ("svf_runtest", {
                "run_state": "IDLE",  "run_count": None,  "run_clock": "TCK",
                "min_time":  1,       "max_time":  2,     "end_state": "IDLE"
            }),
        ])
        self.assertParses("RUNTEST 200 TCK ENDSTATE RESET; RUNTEST 1 SEC;", [
            ("svf_runtest", {
                "run_state": "IDLE",  "run_count": 200,   "run_clock": "TCK",
                "min_time":  None,    "max_time":  None,  "end_state": "RESET"
            }),
            ("svf_runtest", {
                "run_state": "IDLE",  "run_count": None,  "run_clock": "TCK",
                "min_time":  1,       "max_time":  None,  "end_state": "RESET"
            }),
        ])

        self.assertErrors("RUNTEST;",
                          "expected number")
        self.assertErrors("RUNTEST 2 SEC MAXIMUM 1 SEC;",
                          "maximum time must be greater than minimum time")

    def test_piomap(self):
        self.assertParses("PIOMAP (IN FOO OUT BAR);",
                          [("svf_piomap", {"mapping": "IN FOO OUT BAR"})])

        self.assertErrors("PIOMAP;",
                          "expected data")

    def test_pio(self):
        self.assertParses("PIO (LHZX);",
                          [("svf_pio", {"vector": "LHZX"})])

        self.assertErrors("PIO;",
                          "expected data")

    def test_last_command(self):
        handler = SVFMockEventHandler()
        parser = SVFParser(" TRST OFF; SIR 8 TDI (aa); ", handler)
        parser.parse_command()
        self.assertEqual(parser.last_command(), " TRST OFF;")
        parser.parse_command()
        self.assertEqual(parser.last_command(), " SIR 8 TDI (aa);")

# -------------------------------------------------------------------------------------------------

class SVFPrintingEventHandler:
    def __getattr__(self, name):
        if name.startswith("svf_"):
            def svf_event(**kwargs):
                print((name, kwargs))
            return svf_event
        else:
            return super().__getattr__(name)


if __name__ == "__main__":
    import sys
    with open(sys.argv[1]) as f:
        SVFParser(f.read(), SVFPrintingEventHandler()).parse_file()
