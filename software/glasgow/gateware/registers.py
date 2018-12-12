from migen import *


__all__ = ["Registers", "I2CRegisters"]


class Registers(Module):
    """
    A set of 8-bit registers.

    :attr reg_count:
        Register count.
    """
    def __init__(self):
        self.reg_count = 0
        self.regs_r = Array()
        self.regs_w = Array()

    def _add_reg(self, *args, **kwargs):
        reg  = Signal(*args, **kwargs)
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
    A set of 8-bit registers, accessible over I2C.
    """
    def __init__(self, i2c_slave):
        super().__init__()
        self.i2c_slave = i2c_slave
        self.address   = Signal(8)

    def do_finalize(self):
        if self.reg_count == 0:
            return

        latch_addr = Signal()
        self.comb += [
            self.i2c_slave.data_o.eq(self.regs_r[self.address]),
            If(self.i2c_slave.write,
                If(latch_addr & (self.i2c_slave.data_i < self.reg_count),
                    self.i2c_slave.ack_o.eq(1)
                ).Elif(~latch_addr,
                    self.i2c_slave.ack_o.eq(1),
                )
            )
        ]
        self.sync += [
            If(self.i2c_slave.start,
                latch_addr.eq(1)
            ),
            If(self.i2c_slave.write,
                If(latch_addr,
                    If(self.i2c_slave.data_i < self.reg_count,
                        latch_addr.eq(0),
                        self.address.eq(self.i2c_slave.data_i)
                    )
                ).Else(
                    self.regs_w[self.address].eq(self.i2c_slave.data_i)
                )
            )
        ]

# -------------------------------------------------------------------------------------------------

import unittest
from migen.fhdl import verilog

from . import simulation_test
from .i2c import I2CSlaveTestbench


class I2CRegistersTestbench(Module):
    def __init__(self):
        self.submodules.i2c = I2CSlaveTestbench()
        self.submodules.dut = I2CRegisters(self.i2c.dut)
        dummy, _ = self.dut.add_rw(8)
        reg_i, _ = self.dut.add_rw(8)
        reg_o, _ = self.dut.add_ro(8)


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
        yield from tb.i2c.write_octet(1)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        self.assertEqual((yield tb.dut.address), 1)

    @simulation_test
    def test_address_write_nak(self, tb):
        yield from tb.i2c.start()
        yield from tb.i2c.write_octet(0b00010000)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.write_octet(5)
        self.assertEqual((yield from tb.i2c.read_bit()), 1)
        self.assertEqual((yield tb.dut.address), 0)

    @simulation_test
    def test_data_write(self, tb):
        yield from tb.i2c.start()
        yield from tb.i2c.write_octet(0b00010000)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.write_octet(1)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.write_octet(0b10100101)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        self.assertEqual((yield tb.dut.regs_r[1]), 0b10100101)
        yield from tb.i2c.write_octet(0b01011010)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        self.assertEqual((yield tb.dut.regs_r[1]), 0b01011010)
        self.assertEqual((yield tb.dut.regs_r[0]), 0b00000000)
        yield from tb.i2c.stop()

    @simulation_test
    def test_data_read(self, tb):
        yield (tb.dut.regs_r[2].eq(0b10100101))
        yield from tb.i2c.start()
        yield from tb.i2c.write_octet(0b00010000)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.write_octet(2)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.rep_start()
        yield from tb.i2c.write_octet(0b00010001)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        self.assertEqual((yield from tb.i2c.read_octet()), 0b10100101)
        yield from tb.i2c.write_bit(1)
        yield from tb.i2c.stop()


if __name__ == "__main__":
    verilog.convert(I2CSlave(None)).write("registers.v")
