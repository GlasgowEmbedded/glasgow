import unittest

from glasgow.support.bits import bits
from glasgow.support.chunked_fifo import ChunkedFIFO


class ChunkedFIFOTestCase(unittest.TestCase):
    def setUp(self):
        self.fifo = ChunkedFIFO()

    def test_zero_write(self):
        self.fifo.write(b"")
        with self.assertRaises(IndexError):
            self.fifo.read()

    def test_zero_read(self):
        self.assertEqual(self.fifo.read(0), b"")
        self.fifo.write(b"A")
        self.assertEqual(self.fifo.read(0), b"")
        self.assertEqual(self.fifo.read(), b"A")

    def test_fast(self):
        self.fifo.write(b"AB")
        self.fifo.write(b"CD")
        self.assertEqual(self.fifo.read(), b"AB")
        self.assertEqual(self.fifo.read(), b"CD")

    def test_chunked(self):
        self.fifo.write(b"ABCD")
        self.fifo.write(b"EF")
        self.assertEqual(self.fifo.read(1), b"A")
        self.assertEqual(self.fifo.read(1), b"B")
        self.assertEqual(self.fifo.read(2), b"CD")
        self.assertEqual(self.fifo.read(), b"EF")

    def test_chunked_chunked(self):
        self.fifo.write(b"ABCD")
        self.fifo.write(b"EF")
        self.assertEqual(self.fifo.read(1), b"A")
        self.assertEqual(self.fifo.read(1), b"B")
        self.assertEqual(self.fifo.read(2), b"CD")
        self.assertEqual(self.fifo.read(1), b"E")
        self.assertEqual(self.fifo.read(1), b"F")

    def test_chunked_fast(self):
        self.fifo.write(b"ABCD")
        self.fifo.write(b"EF")
        self.assertEqual(self.fifo.read(1), b"A")
        self.assertEqual(self.fifo.read(1), b"B")
        self.assertEqual(self.fifo.read(), b"CD")
        self.assertEqual(self.fifo.read(), b"EF")

    def test_bool(self):
        self.assertFalse(self.fifo)
        self.fifo.write(b"ABC")
        self.assertTrue(self.fifo)
        self.fifo.read(1)
        self.assertTrue(self.fifo)
        self.fifo.read(2)
        self.assertFalse(self.fifo)

    def test_len(self):
        self.assertEqual(len(self.fifo), 0)
        self.fifo.write(b"ABCD")
        self.assertEqual(len(self.fifo), 4)
        self.fifo.write(b"EF")
        self.assertEqual(len(self.fifo), 6)
        self.fifo.read(1)
        self.assertEqual(len(self.fifo), 5)
        self.fifo.read(3)
        self.assertEqual(len(self.fifo), 2)

    def test_write_bits(self):
        self.fifo.write(bits("1010"))
        self.assertEqual(len(self.fifo), 1)
        self.assertEqual(self.fifo.read(1), b"\x0a")
