import unittest

from ....support.bits import *
from ... import *
from . import JTAGProbeApplet, JTAGProbeInterface, JTAGProbeError


class JTAGInterrogationTestCase(unittest.TestCase):
    def setUp(self):
        self.iface = JTAGProbeInterface(interface=None, logger=JTAGProbeApplet.logger)

    def test_dr_empty(self):
        self.assertEqual(self.iface.interrogate_dr(bits("")), [])

    def test_dr_bypass(self):
        self.assertEqual(self.iface.interrogate_dr(bits("0")), [None])

    def test_dr_idcode(self):
        dr = bits("00111011101000000000010001110111")
        self.assertEqual(self.iface.interrogate_dr(dr), [0x3ba00477])

    def test_dr_truncated(self):
        dr = bits("0011101110100000000001000111011")
        with self.assertRaisesRegex(JTAGProbeError,
                r"^TAP #0 has truncated DR IDCODE=<1101110001000000000010111011100>$"):
            self.iface.interrogate_dr(dr)
        self.assertEqual(self.iface.interrogate_dr(dr, check=False), None)

    def test_dr_bypass_idcode(self):
        dr = bits("001110111010000000000100011101110")
        self.assertEqual(self.iface.interrogate_dr(dr), [None, 0x3ba00477])

    def test_dr_idcode_bypass(self):
        dr = bits("000111011101000000000010001110111")
        self.assertEqual(self.iface.interrogate_dr(dr), [0x3ba00477, None])

    def test_dr_invalid(self):
        dr = bits("00000000000000000000000011111111")
        with self.assertRaisesRegex(JTAGProbeError,
                r"^TAP #0 has invalid DR IDCODE=000000ff$"):
            self.iface.interrogate_dr(dr)
        self.assertEqual(self.iface.interrogate_dr(dr, check=False), None)

    def test_ir_1tap_0start(self):
        ir = bits("0100")
        with self.assertRaisesRegex(JTAGProbeError,
                r"^IR capture does not start with <10> transition$"):
            self.iface.interrogate_ir(ir, 1)
        self.assertEqual(self.iface.interrogate_ir(ir, 1, check=False),
                         None)

    def test_ir_1tap_0start_1length(self):
        ir = bits("0100")
        with self.assertRaisesRegex(JTAGProbeError,
                r"^IR capture does not start with <10> transition$"):
            self.iface.interrogate_ir(ir, 1, ir_lengths=[4])
        self.assertEqual(self.iface.interrogate_ir(ir, 1, ir_lengths=[4], check=False),
                         None)

    def test_ir_1tap_1start(self):
        ir = bits("0001")
        self.assertEqual(self.iface.interrogate_ir(ir, 1),
                         [4])

    def test_ir_1tap_2start(self):
        ir = bits("0101")
        self.assertEqual(self.iface.interrogate_ir(ir, 1),
                         [4])

    def test_ir_1tap_2start_1length(self):
        ir = bits("0101")
        self.assertEqual(self.iface.interrogate_ir(ir, 1, ir_lengths=[4]),
                         [4])

    def test_ir_1tap_2start_1length_over(self):
        ir = bits("0101")
        with self.assertRaisesRegex(JTAGProbeError,
                r"^IR capture length differs from sum of IR lengths$"):
            self.iface.interrogate_ir(ir, 1, ir_lengths=[5])
        self.assertEqual(self.iface.interrogate_ir(ir, 1, ir_lengths=[5], check=False),
                         None)

    def test_ir_2tap_1start(self):
        ir = bits("0001")
        with self.assertRaisesRegex(JTAGProbeError,
                r"^IR capture has fewer <10> transitions than TAPs$"):
            self.iface.interrogate_ir(ir, 2)
        self.assertEqual(self.iface.interrogate_ir(ir, 2, check=False),
                         None)

    def test_ir_2tap_1start_2length(self):
        ir = bits("0001")
        with self.assertRaisesRegex(JTAGProbeError,
                r"^IR capture has fewer <10> transitions than TAPs$"):
            self.iface.interrogate_ir(ir, 2, ir_lengths=[2, 2])
        self.assertEqual(self.iface.interrogate_ir(ir, 2, ir_lengths=[2, 2], check=False),
                         None)

    def test_ir_2tap_2start(self):
        ir = bits("01001")
        self.assertEqual(self.iface.interrogate_ir(ir, 2),
                         [3, 2])

    def test_ir_2tap_3start(self):
        ir = bits("01001001")
        with self.assertRaisesRegex(JTAGProbeError,
                r"^IR capture insufficiently constrains IR lengths$"):
            self.iface.interrogate_ir(ir, 2)
        self.assertEqual(self.iface.interrogate_ir(ir, 2, check=False),
                         None)

    def test_ir_2tap_3start_1length(self):
        ir = bits("01001001")
        with self.assertRaisesRegex(JTAGProbeError,
                r"^IR length count differs from TAP count$"):
            self.iface.interrogate_ir(ir, 3, ir_lengths=[1])
        self.assertEqual(self.iface.interrogate_ir(ir, 3, ir_lengths=[1], check=False),
                         None)

    def test_ir_2tap_3start_2length(self):
        ir = bits("01001001")
        self.assertEqual(self.iface.interrogate_ir(ir, 2, ir_lengths=[6, 2]),
                         [6, 2])
        self.assertEqual(self.iface.interrogate_ir(ir, 2, ir_lengths=[3, 5]),
                         [3, 5])


class JTAGProbeAppletTestCase(GlasgowAppletTestCase, applet=JTAGProbeApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
