from nmigen.compat import *


__all__ = ["Registers", "I2CRegisters"]


class Registers(Module):
    """
    A register array.

    :attr reg_count:
        Register count.
    """
    def __init__(self):
        self.reg_count = 0
        self.regs_r = Array()
        self.regs_w = Array()

    def _add_reg(self, *args, **kwargs):
        reg  = Signal(*args, **kwargs, src_loc_at=2)
        addr = self.reg_count
        self.reg_count += 1
        return reg, addr

    def add_ro(self, *args, **kwargs):
        reg, addr = self._add_reg(*args, **kwargs)
        self.regs_r.append(reg)
        self.regs_w.append(Signal(name="ro_reg_dummy"))
        return reg, addr

    def add_rw(self, *args, **kwargs):
        reg, addr = self._add_reg(*args, **kwargs)
        self.regs_r.append(reg)
        self.regs_w.append(reg)
        return reg, addr


class I2CRegisters(Registers):
    """
    A register array, accessible over I2C.

    Note that for multibyte registers, the register data is read in little endian, but written
    in big endian. This replaces a huge multiplexer with a shift register, but is a bit cursed.
    """
    def __init__(self, i2c_target):
        super().__init__()
        self.i2c_target = i2c_target

    def do_finalize(self):
        if self.reg_count == 0:
            return

        latch_addr = Signal()
        reg_addr   = Signal(max=max(self.reg_count, 2))
        reg_data   = Signal(max(s.nbits for s in self.regs_r))
        self.comb += [
            self.i2c_target.data_o.eq(reg_data),
            If(self.i2c_target.write,
                If(latch_addr,
                    If(self.i2c_target.data_i < self.reg_count,
                        self.i2c_target.ack_o.eq(1)
                    )
                ).Elif(~latch_addr,
                    self.i2c_target.ack_o.eq(1),
                )
            )
        ]
        self.sync += [
            If(self.i2c_target.start,
                latch_addr.eq(1)
            ),
            If(self.i2c_target.write,
                latch_addr.eq(0),
                If(latch_addr,
                    reg_addr.eq(self.i2c_target.data_i),
                    reg_data.eq(self.regs_r[self.i2c_target.data_i]),
                ).Else(
                    reg_data.eq(Cat(self.i2c_target.data_i, reg_data)),
                    self.regs_w[reg_addr].eq(Cat(self.i2c_target.data_i, reg_data)),
                )
            ),
            If(self.i2c_target.read,
                reg_data.eq(reg_data >> 8),
            )
        ]

# -------------------------------------------------------------------------------------------------

import unittest

from . import simulation_test
from .i2c import I2CTargetTestbench


class I2CRegistersTestbench(Module):
    def __init__(self):
        self.submodules.i2c = I2CTargetTestbench()
        self.submodules.dut = I2CRegisters(self.i2c.dut)
        self.reg_dummy, self.addr_dummy = self.dut.add_rw(8)
        self.reg_rw_8,  self.addr_rw_8  = self.dut.add_rw(8)
        self.reg_ro_8,  self.addr_ro_8  = self.dut.add_ro(8)
        self.reg_rw_16, self.addr_rw_16 = self.dut.add_rw(16)
        self.reg_ro_16, self.addr_ro_16 = self.dut.add_ro(16)
        self.reg_rw_12, self.addr_rw_12 = self.dut.add_rw(12)
        self.reg_ro_12, self.addr_ro_12 = self.dut.add_ro(12)


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
