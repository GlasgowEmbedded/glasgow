# I2C reference: https://www.nxp.com/docs/en/user-guide/UM10204.pdf

from migen import *
from migen.genlib.fsm import *
from migen.genlib.cdc import MultiReg


class I2CBus(Module):
    def __init__(self, scl, sda):
        self.scl_i = Signal()
        self.scl_o = Signal(reset=1)
        self.sda_i = Signal()
        self.sda_o = Signal(reset=1)

        self.sample = Signal(name="bus_sample")
        self.setup  = Signal(name="bus_setup")
        self.start  = Signal(name="bus_start")
        self.stop   = Signal(name="bus_stop")

        ###

        scl_r = Signal(reset=1)
        sda_r = Signal(reset=1)

        self.comb += [
            scl.o.eq(0),
            scl.oe.eq(~self.scl_o),
            sda.o.eq(0),
            sda.oe.eq(~self.sda_o),

            self.sample.eq(~scl_r & self.scl_i),
            self.setup.eq(scl_r & ~self.scl_i),
            self.start.eq(self.scl_i & sda_r & ~self.sda_i),
            self.stop.eq(self.scl_i & ~sda_r & self.sda_i),
        ]

        self.sync += [
            scl_r.eq(self.scl_i),
            sda_r.eq(self.sda_i),
        ]

        self.specials += [
            MultiReg(scl.i, self.scl_i, reset=1),
            MultiReg(sda.i, self.sda_i, reset=1),
        ]


class I2CSlave(Module):
    """
    Simple I2C slave.

    Clock stretching is not supported.
    Builtin responses (identification, general call, etc.) are not provided.

    :attr address:
        The 7-bit address the slave will respond to.
    :attr start:
        Start strobe. Active for one cycle immediately after acknowledging address.
    :attr stop:
        Stop stobe. Active for one cycle immediately after a stop condition that terminates
        a transaction that addressed this device.
    :attr write:
        Write strobe. Active for one cycle immediately after receiving a data octet.
    :attr data_i:
        Data octet received from the master. Valid when ``write`` is high.
    :attr ack_o:
        Acknowledge strobe. If active for at least one cycle during the acknowledge bit
        setup period (one half-period after write strobe is asserted), acknowledge is asserted.
        Otherwise, no acknowledge is asserted. May use combinatorial feedback from ``write``.
    """
    def __init__(self, scl, sda):
        self.address = Signal(7)
        self.start   = Signal()
        self.stop    = Signal()
        self.write   = Signal()
        self.data_i  = Signal(8)
        self.ack_o   = Signal()
        self.read    = Signal()
        self.data_o  = Signal(8)
        self.ack_i   = Signal()

        self.submodules.bus = bus = I2CBus(scl, sda)

        ###

        bitno   = Signal(max=8)
        shreg_i = Signal(8)

        self.submodules.fsm = FSM(reset_state="IDLE")
        self.comb += self.stop.eq(self.fsm.after_entering("IDLE"))
        self.fsm.act("IDLE",
            If(bus.start,
                NextState("START"),
            )
        )
        self.comb += self.start.eq(self.fsm.after_entering("START"))
        self.fsm.act("START",
            If(bus.stop,
                # According to the spec, technically illegal, "but many devices handle
                # this anyway". Can Philips, like, decide on whether they want it or not??
                NextState("IDLE")
            ).Elif(bus.setup,
                NextValue(bitno, 0),
                NextState("ADDR-SHIFT")
            )
        )
        self.fsm.act("ADDR-SHIFT",
            If(bus.stop,
                NextState("IDLE")
            ).Elif(bus.start,
                NextState("START")
            ).Elif(bus.sample,
                NextValue(shreg_i, (shreg_i << 1) | bus.sda_i),
            ).Elif(bus.setup,
                NextValue(bitno, bitno + 1),
                If(bitno == 7,
                    If(shreg_i[1:8] == self.address,
                        NextValue(bus.sda_o, 0),
                        NextState("ADDR-ACK")
                    ).Else(
                        NextState("IDLE")
                    )
                )
            )
        )
        self.fsm.act("ADDR-ACK",
            If(bus.stop,
                NextState("IDLE")
            ).Elif(bus.start,
                NextValue(bitno, 0),
                NextState("START")
            ).Elif(bus.setup,
                self.start.eq(1),
                NextValue(bus.sda_o, 1),
                If(shreg_i[0],
                    #NextState("READ-SHIFT")
                    NextState("IDLE")
                ).Else(
                    NextState("WRITE-SHIFT")
                )
            )
        )
        self.fsm.act("WRITE-SHIFT",
            If(bus.stop,
                NextState("IDLE")
            ).Elif(bus.start,
                NextValue(bitno, 0),
                NextState("START")
            ).Elif(bus.sample,
                NextValue(shreg_i, (shreg_i << 1) | bus.sda_i),
            ).Elif(bus.setup,
                NextValue(bitno, bitno + 1),
                If(bitno == 7,
                    NextValue(self.data_i, shreg_i),
                    NextState("WRITE-ACK")
                )
            )
        )
        self.comb += self.write.eq(self.fsm.after_entering("WRITE-ACK"))
        self.fsm.act("WRITE-ACK",
            If(bus.stop,
                NextState("IDLE")
            ).Elif(bus.start,
                NextValue(bitno, 0),
                NextState("START")
            ).Elif(~bus.scl_i & self.ack_o,
                NextValue(bus.sda_o, 0)
            ).Elif(bus.setup,
                NextValue(bus.sda_o, 1),
                NextState("WRITE-SHIFT")
            )
        )

# -------------------------------------------------------------------------------------------------

import functools
import unittest
import pprint


def simulation_test(case):
    @functools.wraps(case)
    def wrapper(self):
        def setup_wrapper():
            yield from self.simulationSetUp(self.tb)
            yield from case(self, self.tb)
        run_simulation(self.tb, setup_wrapper(), vcd_name="test.vcd")
    return wrapper


class I2CSlaveTestbench(Module):
    def __init__(self):
        self.scl_t = TSTriple()
        self.sda_t = TSTriple()

        self.scl_i = self.scl_t.i
        self.scl_o = Signal(reset=1)
        self.sda_i = self.sda_t.i
        self.sda_o = Signal(reset=1)

        self.submodules.dut = I2CSlave(self.scl_t, self.sda_t)

        self.period = 16

        ###

        self.comb += [
            self.scl_t.i.eq((self.scl_t.o | ~self.scl_t.oe) & self.scl_o),
            self.sda_t.i.eq((self.sda_t.o | ~self.sda_t.oe) & self.sda_o),
        ]

    def do_finalize(self):
        self.states = {v: k for k, v in self.dut.fsm.encoding.items()}

    def dut_state(self):
        return self.states[(yield self.dut.fsm.state)]

    def half_period(self):
        for _ in range(8):
            yield

    def wait_for(self, fn):
        for _ in range(4):
            yield
            if (yield from fn()):
                return True
        return False

    def start(self):
        assert (yield self.scl_i) == 1
        assert (yield self.sda_i) == 1
        yield self.sda_o.eq(0)
        yield from self.half_period()

    def stop(self):
        yield self.scl_o.eq(0)
        yield self.sda_o.eq(0)
        yield from self.half_period()
        yield self.scl_o.eq(1)
        yield from self.half_period()
        yield self.sda_o.eq(1)
        yield from self.half_period()

    def write_bit(self, bit):
        assert (yield self.scl_i) == 1
        yield self.scl_o.eq(0)
        yield # tHD;DAT
        yield self.sda_o.eq(bit)
        yield from self.half_period()
        yield self.scl_o.eq(1)
        yield from self.half_period()

    def write_octet(self, octet):
        for bit in range(8)[::-1]:
            yield from self.write_bit((octet >> bit) & 1)

    def read_bit(self):
        assert (yield self.scl_i) == 1
        yield self.scl_o.eq(0)
        yield from self.half_period()
        yield self.scl_o.eq(1)
        bit = (yield self.sda_i)
        yield from self.half_period()
        return bit

    def read_octet(self):
        octet = 0
        for bit in range(8):
            octet = (octet << 1) | (yield from self.read_bit())
        return octet


class I2CSlaveTestCase(unittest.TestCase):
    def setUp(self):
        self.tb = I2CSlaveTestbench()

    def simulationSetUp(self, tb):
        yield tb.dut.address.eq(0b0101000)

    @simulation_test
    def test_addr_shift(self, tb):
        yield tb.dut.address.eq(0b1111111)
        self.assertEqual((yield from tb.dut_state()), "IDLE")
        yield from tb.start()
        self.assertEqual((yield from tb.dut_state()), "START")
        for _ in range(8):
            yield from tb.write_bit(1)
            self.assertEqual((yield from tb.dut_state()), "ADDR-SHIFT")

    @simulation_test
    def test_addr_stop(self, tb):
        yield from tb.start()
        yield from tb.write_bit(0)
        yield from tb.write_bit(1)
        yield from tb.stop()
        self.assertEqual((yield from tb.dut_state()), "IDLE")

    @simulation_test
    def test_addr_nak(self, tb):
        yield from tb.start()
        yield from tb.write_octet(0b11110001)
        self.assertEqual((yield from tb.read_bit()), 1)
        self.assertEqual((yield from tb.dut_state()), "IDLE")

    @simulation_test
    def test_addr_r_ack(self, tb):
        yield from tb.start()
        yield from tb.write_octet(0b01010001)
        self.assertEqual((yield from tb.read_bit()), 0)
        self.assertEqual((yield from tb.dut_state()), "ADDR-ACK")
        yield tb.scl_o.eq(0)
        self.assertTrue((yield from tb.wait_for(lambda: (yield tb.dut.start))))
        yield
        # self.assertEqual((yield from tb.dut_state()), "READ-SHIFT")

    @simulation_test
    def test_addr_w_ack(self, tb):
        yield from tb.start()
        yield from tb.write_octet(0b01010000)
        self.assertEqual((yield from tb.read_bit()), 0)
        self.assertEqual((yield from tb.dut_state()), "ADDR-ACK")
        yield tb.scl_o.eq(0)
        self.assertTrue((yield from tb.wait_for(lambda: (yield tb.dut.start))))
        yield
        self.assertEqual((yield from tb.dut_state()), "WRITE-SHIFT")

    @simulation_test
    def test_write_shift(self, tb):
        yield from tb.start()
        yield from tb.write_octet(0b01010000)
        self.assertEqual((yield from tb.read_bit()), 0)
        yield from tb.write_octet(0b10100101)
        yield tb.scl_o.eq(0)
        self.assertTrue((yield from tb.wait_for(lambda: (yield tb.dut.write))))
        self.assertEqual((yield tb.dut.data_i), 0b10100101)
        yield
        self.assertEqual((yield from tb.dut_state()), "WRITE-ACK")

    @simulation_test
    def test_write_stop(self, tb):
        yield from tb.start()
        yield from tb.write_octet(0b01010000)
        self.assertEqual((yield from tb.read_bit()), 0)
        yield from tb.write_bit(0)
        yield from tb.write_bit(1)
        yield from tb.stop()
        self.assertEqual((yield from tb.dut_state()), "IDLE")

    @simulation_test
    def test_write_ack(self, tb):
        yield from tb.start()
        yield from tb.write_octet(0b01010000)
        self.assertEqual((yield from tb.read_bit()), 0)
        yield from tb.write_octet(0b10100101)
        # this convoluted sequence ensures combinatorial feedback works
        yield tb.scl_o.eq(0)
        yield
        yield
        yield
        yield tb.dut.ack_o.eq(1)
        yield
        self.assertEqual((yield tb.dut.write), 1)
        yield tb.dut.ack_o.eq(0)
        yield
        self.assertEqual((yield tb.dut.write), 0)
        yield from tb.half_period()
        yield tb.scl_o.eq(1)
        self.assertEqual((yield tb.sda_i), 0)

    @simulation_test
    def test_write_nak(self, tb):
        yield from tb.start()
        yield from tb.write_octet(0b01010000)
        self.assertEqual((yield from tb.read_bit()), 0)
        yield from tb.write_octet(0b10100101)
        self.assertEqual((yield from tb.read_bit()), 1)

    @simulation_test
    def test_write_ack_stop(self, tb):
        yield from tb.start()
        yield from tb.write_octet(0b01010000)
        self.assertEqual((yield from tb.read_bit()), 0)
        yield from tb.write_octet(0b10100101)
        self.assertEqual((yield from tb.read_bit()), 1)
        yield tb.scl_o.eq(0)
        yield tb.sda_o.eq(0)
        yield from tb.half_period()
        yield tb.scl_o.eq(1)
        yield from tb.half_period()
        yield tb.sda_o.eq(1)
        self.assertTrue((yield from tb.wait_for(lambda: (yield tb.dut.stop))))
        yield
        self.assertEqual((yield from tb.dut_state()), "IDLE")


if __name__ == "__main__":
    from migen.fhdl import verilog


    scl = TSTriple()
    sda = TSTriple()
    engine = I2CSlave(scl, sda)

    verilog.convert(engine).write("i2cslave.v")
