import random
import unittest

from glasgow.support.bits import *
from glasgow.protocol.jesd3 import *

class JESD3TestCase(unittest.TestCase):
    def test_roundtrip(self):
        data = bitarray(random.randbytes(1234))
        del data[-3:]
        emitter = JESD3Emitter(data)
        emitter.add_comment(b"MEOW")
        jed = emitter.emit()
        parser = JESD3Parser(jed)
        parser.parse()
        self.assertEqual(data, parser.fuse)