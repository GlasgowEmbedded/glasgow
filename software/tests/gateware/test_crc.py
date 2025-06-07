from typing import Iterable
import unittest
from amaranth import *
from amaranth.lib import wiring, crc
from amaranth.sim import Simulator
from amaranth.back import rtlil

from glasgow.gateware.stream import stream_put, stream_assert
from glasgow.gateware.crc import *


END = object()


def run(dut, input: list[Iterable[int]], output: list[Iterable[int]], *, error=False, end=False):
    async def testbench_i(ctx):
        for packet in input:
            for index, byte in enumerate(packet):
                await stream_put(ctx, dut.i, {
                    "data":  byte,
                    "first": index == 0,
                    "last":  not end and index == len(packet) - 1,
                })
            if end:
                await stream_put(ctx, dut.i, {
                    "end":   1,
                })

    async def testbench_o(ctx):
        for packet in output:
            for index, byte in enumerate(packet):
                await stream_assert(ctx, dut.o, {
                    "data":  byte,
                    "first": index == 0,
                    "last":  not error and index == len(packet) - 1
                })

    sim = Simulator(dut)
    sim.add_clock(1e-6)
    sim.add_testbench(testbench_i)
    sim.add_testbench(testbench_o)
    with sim.write_vcd("crc.vcd"):
        sim.run()


def append(algorithm, data, *, data_width=8, flip=False):
    checksum = algorithm(data_width).compute(data)
    if flip:
        checksum ^= 1
    return data + checksum.to_bytes(algorithm.crc_width // data_width, "little")


class PacketChecksumTestCase(unittest.TestCase):
    def test_append(self):
        algorithm = crc.catalog.CRC32_ETHERNET
        for data in (b"\0", b"a", b"ab", b"abcd", b"abcde"):
            run(ChecksumAppender(algorithm), [data], [append(algorithm, data)])

    def test_verify_ok(self):
        algorithm = crc.catalog.CRC32_ETHERNET
        for end in (False, True):
            for data in (b"\0", b"a", b"ab", b"abcd", b"abcde"):
                run(ChecksumVerifier(algorithm), [append(algorithm, data)], [data],
                    end=end)

    def test_verify_fail(self):
        algorithm = crc.catalog.CRC32_ETHERNET
        for end in (False, True):
            for data in (b"\0", b"a", b"ab", b"abcd", b"abcde"):
                run(ChecksumVerifier(algorithm), [append(algorithm, data, flip=True)], [data],
                    error=True, end=end)
