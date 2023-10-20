import unittest
from amaranth import *

from glasgow.gateware import simulation_test
from glasgow.gateware.registers import I2CRegisters

from .test_i2c import I2CTargetTestbench


class I2CRegistersTestbench(Elaboratable):
    def __init__(self):
        self.i2c = I2CTargetTestbench()
        self.dut = I2CRegisters(self.i2c.dut)
        self.reg_dummy, self.addr_dummy = self.dut.add_rw(8)
        self.reg_rw_8,  self.addr_rw_8  = self.dut.add_rw(8)
        self.reg_ro_8,  self.addr_ro_8  = self.dut.add_ro(8)
        self.reg_rw_16, self.addr_rw_16 = self.dut.add_rw(16)
        self.reg_ro_16, self.addr_ro_16 = self.dut.add_ro(16)
        self.reg_rw_12, self.addr_rw_12 = self.dut.add_rw(12)
        self.reg_ro_12, self.addr_ro_12 = self.dut.add_ro(12)

    def elaborate(self, platform):
        m = Module()
        m.submodules.i2c = self.i2c
        m.submodules.dut = self.dut
        return m


class I2CRegistersTestCase(unittest.TestCase):
    def setUp(self):
        self.tb = I2CRegistersTestbench()

    def simulationSetUp(self, tb):
        yield tb.i2c.dut.address.eq(0b0001000)

    @simulation_test
    def test_address_write_ack(self, tb):
        yield from tb.i2c.start()
        yield from tb.i2c.write_octet(0b00010000)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.write_octet(self.tb.addr_rw_8)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)

    @simulation_test
    def test_address_write_nak(self, tb):
        yield from tb.i2c.start()
        yield from tb.i2c.write_octet(0b00010000)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.write_octet(10)
        self.assertEqual((yield from tb.i2c.read_bit()), 1)

    @simulation_test
    def test_data_write_8(self, tb):
        yield from tb.i2c.start()
        yield from tb.i2c.write_octet(0b00010000)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.write_octet(self.tb.addr_rw_8)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.write_octet(0b10100101)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        self.assertEqual((yield tb.dut.regs_r[self.tb.addr_rw_8]), 0b10100101)
        self.assertEqual((yield tb.dut.regs_r[self.tb.addr_dummy]), 0b00000000)
        yield from tb.i2c.stop()

    @simulation_test
    def test_data_read_8(self, tb):
        yield (tb.dut.regs_r[self.tb.addr_ro_8].eq(0b10100101))
        yield from tb.i2c.start()
        yield from tb.i2c.write_octet(0b00010000)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.write_octet(self.tb.addr_ro_8)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.rep_start()
        yield from tb.i2c.write_octet(0b00010001)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        self.assertEqual((yield from tb.i2c.read_octet()), 0b10100101)
        yield from tb.i2c.write_bit(1)
        yield from tb.i2c.stop()

    @simulation_test
    def test_data_write_16(self, tb):
        yield from tb.i2c.start()
        yield from tb.i2c.write_octet(0b00010000)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.write_octet(self.tb.addr_rw_16)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.write_octet(0b11110000)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.write_octet(0b10100101)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        self.assertEqual((yield tb.dut.regs_r[self.tb.addr_rw_16]), 0b1111000010100101)
        yield from tb.i2c.stop()

    @simulation_test
    def test_data_read_16(self, tb):
        yield (tb.dut.regs_r[self.tb.addr_ro_16].eq(0b1111000010100101))
        yield from tb.i2c.start()
        yield from tb.i2c.write_octet(0b00010000)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.write_octet(self.tb.addr_ro_16)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.rep_start()
        yield from tb.i2c.write_octet(0b00010001)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        self.assertEqual((yield from tb.i2c.read_octet()), 0b10100101)
        yield from tb.i2c.write_bit(0)
        self.assertEqual((yield from tb.i2c.read_octet()), 0b11110000)
        yield from tb.i2c.write_bit(1)
        yield from tb.i2c.stop()

    @simulation_test
    def test_data_write_12(self, tb):
        yield from tb.i2c.start()
        yield from tb.i2c.write_octet(0b00010000)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.write_octet(self.tb.addr_rw_12)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.write_octet(0b00001110)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.write_octet(0b10100101)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        self.assertEqual((yield tb.dut.regs_r[self.tb.addr_rw_12]), 0b111010100101)
        yield from tb.i2c.stop()

    @simulation_test
    def test_data_read_12(self, tb):
        yield (tb.dut.regs_r[self.tb.addr_ro_12].eq(0b111010100101))
        yield from tb.i2c.start()
        yield from tb.i2c.write_octet(0b00010000)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.write_octet(self.tb.addr_ro_12)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.rep_start()
        yield from tb.i2c.write_octet(0b00010001)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        self.assertEqual((yield from tb.i2c.read_octet()), 0b10100101)
        yield from tb.i2c.write_bit(0)
        self.assertEqual((yield from tb.i2c.read_octet()), 0b00001110)
        yield from tb.i2c.write_bit(1)
        yield from tb.i2c.stop()
