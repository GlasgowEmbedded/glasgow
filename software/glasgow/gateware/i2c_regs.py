from migen import *
from migen.genlib.fsm import *


__all__ = ['I2CRegisters']


class I2CRegisters(Module):
    """
    A set of 8-bit registers accessible over I2C.

    :attr registers:
        :class:`Array` of 8-bit signals for registers.
    """
    def __init__(self, i2c_slave):
        self.i2c_slave = i2c_slave

        self.reg_count = 0
        self.regs_r = Array()
        self.regs_w = Array()

        self.address = Signal(max=8)

    def _add_reg(self):
        reg  = Signal(8)
        addr = self.reg_count
        self.reg_count += 1
        return reg, addr

    def add_ro(self):
        reg, addr = self._add_reg()
        self.regs_r.append(reg)
        self.regs_w.append(Signal(8))
        return reg, addr

    def add_rw(self):
        reg, addr = self._add_reg()
        self.regs_r.append(reg)
        self.regs_w.append(reg)
        return reg, addr

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

import functools
import unittest

from migen.fhdl import verilog

from .i2c import I2CSlaveTestbench


def simulation_test(case):
    @functools.wraps(case)
    def wrapper(self):
        def setup_wrapper():
            yield from self.simulationSetUp(self.tb)
            yield from case(self, self.tb)
        run_simulation(self.tb, setup_wrapper(), vcd_name="test.vcd")
    return wrapper


class I2CRegistersTestbench(Module):
    def __init__(self):
        self.submodules.i2c = I2CSlaveTestbench()
        self.submodules.dut = I2CRegisters(self.i2c.dut)
        dummy, _ = self.dut.add_rw()
        reg_i, _ = self.dut.add_rw()
        reg_o, _ = self.dut.add_ro()


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
