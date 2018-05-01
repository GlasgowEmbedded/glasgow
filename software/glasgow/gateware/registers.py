from migen import *
from migen.genlib.fsm import *


__all__ = ['Registers']


class Registers(Module):
    """
    A set of 8-bit registers accessible over I2C.

    :attr registers:
        :class:`Array` of 8-bit signals for registers.
    """
    def __init__(self, i2c_slave, count):
        self.i2c_slave = i2c_slave

        self.address   = Signal(max=2 if count < 2 else count)
        self.registers = Array(Signal(8) for _ in range(count))

        ###

        latch_addr = Signal()

        self.comb += [
            i2c_slave.data_o.eq(self.registers[self.address]),
            If(i2c_slave.write,
                If(latch_addr & (i2c_slave.data_i < count),
                    i2c_slave.ack_o.eq(1)
                ).Elif(~latch_addr,
                    i2c_slave.ack_o.eq(1),
                )
            )
        ]
        self.sync += [
            If(i2c_slave.start,
                latch_addr.eq(1)
            ),
            If(i2c_slave.write,
                If(latch_addr,
                    If(i2c_slave.data_i < count,
                        latch_addr.eq(0),
                        self.address.eq(i2c_slave.data_i)
                    )
                ).Else(
                    self.registers[self.address].eq(i2c_slave.data_i)
                )
            )
        ]

    def __getitem__(self, index):
        return self.registers[index]

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


class RegistersTestbench(Module):
    def __init__(self, count):
        self.submodules.i2c = I2CSlaveTestbench()
        self.submodules.dut = Registers(self.i2c.dut, count)


class RegistersTestCase(unittest.TestCase):
    def setUp(self):
        self.tb = RegistersTestbench(3)

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
        self.assertEqual((yield tb.dut.registers[1]), 0b10100101)
        yield from tb.i2c.write_octet(0b01011010)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        self.assertEqual((yield tb.dut.registers[1]), 0b01011010)
        self.assertEqual((yield tb.dut.registers[0]), 0b00000000)
        yield from tb.i2c.stop()

    @simulation_test
    def test_data_read(self, tb):
        yield (tb.dut.registers[0].eq(0b10100101))
        yield from tb.i2c.start()
        yield from tb.i2c.write_octet(0b00010000)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.write_octet(0)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        yield from tb.i2c.rep_start()
        yield from tb.i2c.write_octet(0b00010001)
        self.assertEqual((yield from tb.i2c.read_bit()), 0)
        self.assertEqual((yield from tb.i2c.read_octet()), 0b10100101)
        yield from tb.i2c.write_bit(1)
        yield from tb.i2c.stop()


if __name__ == "__main__":
    verilog.convert(I2CSlave(None)).write("registers.v")
