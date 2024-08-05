import unittest
from amaranth import *
from amaranth.lib import io

from glasgow.gateware import simulation_test
from glasgow.gateware.uart import UART


class UARTTestbench(Elaboratable):
    def __init__(self):
        self.rx = io.SimulationPort("i", 1)
        self.tx = io.SimulationPort("o", 1)

        self.bit_cyc = 4

        self.dut = UART(ports=self, bit_cyc=self.bit_cyc)

    def elaborate(self, platform):
        return self.dut


class UARTRXTestCase(unittest.TestCase):
    def setUp(self):
        self.tb = UARTTestbench()

    def cyc(self, tb, err=None):
        has_err = False
        for _ in range(tb.bit_cyc):
            yield
            if err is not None:
                has_err |= (yield err)
            else:
                self.assertEqual((yield tb.dut.rx_err), 0)
        if err is not None:
            self.assertTrue(has_err)

    def bit(self, tb, bit):
        yield tb.rx.i.eq(bit)
        yield from self.cyc(tb)

    def start(self, tb):
        yield from self.bit(tb, 0)
        yield # CDC latency
        self.assertEqual((yield tb.dut.rx_rdy), 0)

    def data(self, tb, bit):
        yield from self.bit(tb, bit)
        self.assertEqual((yield tb.dut.rx_rdy), 0)

    def stop(self, tb):
        yield from self.bit(tb, 1)
        self.assertEqual((yield tb.dut.rx_rdy), 0)

    def byte(self, tb, bits):
        yield from self.start(tb)
        for bit in bits:
            yield from self.data(tb, bit)
        yield from self.stop(tb)

    def ack(self, tb, data):
        self.assertEqual((yield tb.dut.rx_rdy), 0)
        yield
        yield
        yield
        self.assertEqual((yield tb.dut.rx_rdy), 1)
        self.assertEqual((yield tb.dut.rx_data), data)
        yield tb.dut.rx_ack.eq(1)
        yield
        yield tb.dut.rx_ack.eq(0)
        yield
        yield
        self.assertEqual((yield tb.dut.rx_rdy), 0)

    @simulation_test
    def test_rx_0x55(self, tb):
        yield from self.byte(tb, [1, 0, 1, 0, 1, 0, 1, 0])
        yield from self.ack(tb, 0x55)

    @simulation_test
    def test_rx_0xC3(self, tb):
        yield from self.byte(tb, [1, 1, 0, 0, 0, 0, 1, 1])
        yield from self.ack(tb, 0xC3)

    @simulation_test
    def test_rx_0x81(self, tb):
        yield from self.byte(tb, [1, 0, 0, 0, 0, 0, 0, 1])
        yield from self.ack(tb, 0x81)

    @simulation_test
    def test_rx_0xA5(self, tb):
        yield from self.byte(tb, [1, 0, 1, 0, 0, 1, 0, 1])
        yield from self.ack(tb, 0xA5)

    @simulation_test
    def test_rx_0xFF(self, tb):
        yield from self.byte(tb, [1, 1, 1, 1, 1, 1, 1, 1])
        yield from self.ack(tb, 0xFF)

    @simulation_test
    def test_rx_back_to_back(self, tb):
        yield from self.byte(tb, [1, 0, 1, 0, 1, 0, 1, 0])
        yield from self.ack(tb, 0x55)
        yield from self.byte(tb, [0, 1, 0, 1, 0, 1, 0, 1])
        yield from self.ack(tb, 0xAA)

    @simulation_test
    def test_rx_ferr(self, tb):
        yield from self.start(tb)
        for bit in [1, 1, 1, 1, 1, 1, 1, 1]:
            yield from self.data(tb, bit)
        yield tb.rx.i.eq(0)
        yield # CDC latency
        yield from self.cyc(tb, err=tb.dut.rx_ferr)

    @simulation_test
    def test_rx_ovf(self, tb):
        yield from self.byte(tb, [1, 0, 1, 0, 0, 1, 0, 1])
        yield tb.rx.i.eq(0)
        yield # CDC latency
        yield
        yield
        self.assertEqual((yield tb.dut.rx_ovf), 1)
        yield from self.cyc(tb)
        for bit in [1, 0, 1, 0, 0, 1, 0, 1]:
            yield from self.data(tb, bit)
        yield from self.stop(tb)
        yield from self.ack(tb, 0xA5)


class UARTTXTestCase(unittest.TestCase):
    def setUp(self):
        self.tb = UARTTestbench()

    def half_cyc(self, tb):
        for _ in range(tb.bit_cyc // 2):
            yield

    def cyc(self, tb):
        for _ in range(tb.bit_cyc):
            yield

    def bit(self, tb, bit):
        yield from self.cyc(tb)
        self.assertEqual((yield tb.tx.o), bit)

    def start(self, tb, data):
        self.assertEqual((yield tb.tx.o), 1)
        self.assertEqual((yield tb.dut.tx_rdy), 1)
        yield tb.dut.tx_data.eq(data)
        yield tb.dut.tx_ack.eq(1)
        yield
        yield tb.dut.tx_ack.eq(0)
        yield
        self.assertEqual((yield tb.dut.tx_rdy), 0)
        self.assertEqual((yield tb.tx.o), 0)
        yield from self.half_cyc(tb)
        self.assertEqual((yield tb.tx.o), 0)

    def data(self, tb, bit):
        self.assertEqual((yield tb.dut.tx_rdy), 0)
        yield from self.bit(tb, bit)

    def stop(self, tb):
        self.assertEqual((yield tb.dut.tx_rdy), 0)
        yield from self.bit(tb, 1)

    def byte(self, tb, data, bits):
        yield from self.start(tb, data)
        for bit in bits:
            yield from self.data(tb, bit)
        yield from self.stop(tb)
        yield
        yield

    @simulation_test
    def test_tx_0x55(self, tb):
        yield from self.byte(tb, 0x55, [1, 0, 1, 0, 1, 0, 1, 0])

    @simulation_test
    def test_tx_0x81(self, tb):
        yield from self.byte(tb, 0x81, [1, 0, 0, 0, 0, 0, 0, 1])

    @simulation_test
    def test_tx_0xFF(self, tb):
        yield from self.byte(tb, 0xFF, [1, 1, 1, 1, 1, 1, 1, 1])

    @simulation_test
    def test_tx_0x00(self, tb):
        yield from self.byte(tb, 0x00, [0, 0, 0, 0, 0, 0, 0, 0])

    @simulation_test
    def test_tx_back_to_back(self, tb):
        yield from self.byte(tb, 0xAA, [0, 1, 0, 1, 0, 1, 0, 1])
        yield from self.byte(tb, 0x55, [1, 0, 1, 0, 1, 0, 1, 0])
