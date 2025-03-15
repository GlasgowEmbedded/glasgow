import unittest
from amaranth import *
from amaranth.lib import io
from amaranth.sim import Tick

from glasgow.gateware import simulation_test
from glasgow.gateware.i2c import I2CInitiator, I2CTarget


class I2CTestbench(Elaboratable):
    def __init__(self):
        self.scl = io.SimulationPort("io", 1)
        self.sda = io.SimulationPort("io", 1)

        self.scl_i = self.scl.i
        self.scl_o = Signal(init=1)
        self.sda_i = self.sda.i
        self.sda_o = Signal(init=1)

        self.period_cyc = 16

    def elaborate(self, platform):
        m = Module()

        m.submodules.dut = self.dut

        m.d.comb += [
            self.scl.i.eq((self.scl.o | ~self.scl.oe) & self.scl_o),
            self.sda.i.eq((self.sda.o | ~self.sda.oe) & self.sda_o),
        ]

        return m

    def dut_state(self):
        return self.dut._fsm.decoding[(yield self.dut._fsm.state)]

    def half_period(self):
        for _ in range(self.period_cyc // 2):
            yield Tick()

    def wait_for(self, fn):
        for _ in range(self.wait_cyc):
            yield Tick()
            if (yield from fn()):
                return True
        return False


class I2CTestCase(unittest.TestCase):
    def assertState(self, tb, state):
        self.assertEqual((yield from tb.dut_state()), state)

    def assertCondition(self, tb, fn):
        self.assertTrue((yield from self.tb.wait_for(fn)))


class I2CInitiatorTestbench(I2CTestbench):
    def __init__(self):
        super().__init__()

        self.dut = I2CInitiator(pads=self, period_cyc=self.period_cyc)
        self.wait_cyc = self.period_cyc * 3

    def strobe(self, signal):
        yield signal.eq(1)
        yield Tick()
        yield signal.eq(0)
        yield Tick()

    def start(self):
        yield from self.strobe(self.dut.start)

    def stop(self):
        yield from self.strobe(self.dut.stop)

    def read(self, ack):
        yield self.dut.ack_i.eq(ack)
        yield from self.strobe(self.dut.read)

    def write(self, data):
        yield self.dut.data_i.eq(data)
        yield from self.strobe(self.dut.write)


class I2CInitiatorTestCase(I2CTestCase):
    def setUp(self):
        self.tb = I2CInitiatorTestbench()

    @simulation_test(testbench=True)
    def test_start(self, tb):
        yield from tb.start()
        yield from self.assertState(tb, "START-SDA-L")
        yield from self.assertCondition(tb, lambda: (yield tb.dut.bus.start))
        self.assertEqual((yield tb.dut.busy), 0)

    @simulation_test(testbench=True)
    def test_repeated_start(self, tb):
        yield tb.dut.bus.sda_o.eq(0)
        yield Tick()
        yield Tick()
        yield from tb.start()
        yield from self.assertState(tb, "START-SCL-L")
        yield from self.assertCondition(tb, lambda: (yield tb.dut.bus.start))
        self.assertEqual((yield tb.dut.busy), 0)

    def start(self, tb):
        yield from tb.start()
        yield from self.assertCondition(tb, lambda: (yield tb.dut.bus.start))

    @simulation_test(testbench=True)
    def test_stop(self, tb):
        yield tb.dut.bus.sda_o.eq(0)
        yield Tick()
        yield Tick()
        yield from tb.stop()
        yield from self.assertState(tb, "STOP-SDA-H")
        yield from self.assertCondition(tb, lambda: (yield tb.dut.bus.stop))
        self.assertEqual((yield tb.dut.busy), 0)

    def stop(self, tb):
        yield from tb.stop()
        yield from self.assertCondition(tb, lambda: (yield tb.dut.bus.stop))

    def write(self, tb, data, bits, ack):
        yield from tb.write(data)
        for n, bit in enumerate(bits):
            yield Tick()
            yield Tick()
            yield from self.assertState(tb, "WRITE-DATA-SCL-L" if n == 0 else "WRITE-DATA-SDA-N")
            yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 0)
            yield from self.assertState(tb, "WRITE-DATA-SDA-X")
            yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 1)
            self.assertEqual((yield tb.sda_i), bit)
            yield Tick()
        yield from self.tb.half_period()
        yield Tick()
        yield Tick()
        yield from self.assertState(tb, "WRITE-ACK-SCL-L")
        yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 0)
        yield tb.sda_o.eq(not ack)
        yield from self.assertState(tb, "WRITE-ACK-SDA-H")
        yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 1)
        yield Tick()
        yield tb.sda_o.eq(1)
        self.assertEqual((yield tb.dut.busy), 1)
        yield from self.tb.half_period()
        yield Tick()
        yield Tick()
        yield Tick()
        yield Tick()
        self.assertEqual((yield tb.dut.busy), 0)
        self.assertEqual((yield tb.dut.ack_o), ack)

    @simulation_test(testbench=True)
    def test_write_ack(self, tb):
        yield tb.dut.bus.sda_o.eq(0)
        yield Tick()
        yield Tick()
        yield from self.write(tb, 0xA5, [1, 0, 1, 0, 0, 1, 0, 1], 1)

    @simulation_test(testbench=True)
    def test_write_nak(self, tb):
        yield tb.dut.bus.sda_o.eq(0)
        yield Tick()
        yield Tick()
        yield from self.write(tb, 0x5A, [0, 1, 0, 1, 1, 0, 1, 0], 0)

    @simulation_test(testbench=True)
    def test_write_tx(self, tb):
        yield from self.start(tb)
        yield from self.write(tb, 0x55, [0, 1, 0, 1, 0, 1, 0, 1], 1)
        yield from self.write(tb, 0x33, [0, 0, 1, 1, 0, 0, 1, 1], 0)
        yield from self.stop(tb)
        yield Tick()
        yield Tick()
        self.assertEqual((yield tb.sda_i), 1)
        self.assertEqual((yield tb.scl_i), 1)

    def read(self, tb, data, bits, ack):
        yield from tb.read(ack)
        for n, bit in enumerate(bits):
            yield Tick()
            yield Tick()
            yield from self.assertState(tb, "READ-DATA-SCL-L" if n == 0 else "READ-DATA-SDA-N")
            yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 0)
            yield tb.sda_o.eq(bit)
            yield from self.assertState(tb, "READ-DATA-SDA-H")
            yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 1)
            yield Tick()
        yield tb.sda_o.eq(1)
        yield from tb.half_period()
        yield Tick()
        yield Tick()
        yield from self.assertState(tb, "READ-ACK-SCL-L")
        yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 0)
        yield from self.assertState(tb, "READ-ACK-SDA-X")
        yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 1)
        self.assertEqual((yield tb.sda_i), not ack)
        self.assertEqual((yield tb.dut.busy), 1)
        yield from self.tb.half_period()
        yield Tick()
        yield Tick()
        yield Tick()
        yield Tick()
        self.assertEqual((yield tb.dut.busy), 0)
        self.assertEqual((yield tb.dut.data_o), data)

    @simulation_test(testbench=True)
    def test_read_ack(self, tb):
        yield tb.dut.bus.sda_o.eq(0)
        yield Tick()
        yield Tick()
        yield from self.read(tb, 0xA5, [1, 0, 1, 0, 0, 1, 0, 1], 1)

    @simulation_test(testbench=True)
    def test_read_nak(self, tb):
        yield tb.dut.bus.sda_o.eq(0)
        yield Tick()
        yield Tick()
        yield from self.read(tb, 0x5A, [0, 1, 0, 1, 1, 0, 1, 0], 0)

    @simulation_test(testbench=True)
    def test_read_tx(self, tb):
        yield from self.start(tb)
        yield from self.read(tb, 0x55, [0, 1, 0, 1, 0, 1, 0, 1], 1)
        yield from self.read(tb, 0x33, [0, 0, 1, 1, 0, 0, 1, 1], 0)
        yield from self.stop(tb)
        yield Tick()
        yield Tick()
        self.assertEqual((yield tb.sda_i), 1)
        self.assertEqual((yield tb.scl_i), 1)


class I2CTargetTestbench(I2CTestbench):
    def __init__(self):
        super().__init__()

        self.dut = I2CTarget(pads=self)
        self.wait_cyc = self.period_cyc // 4

    def start(self):
        assert (yield self.scl_i) == 1
        assert (yield self.sda_i) == 1
        yield self.sda_o.eq(0)
        yield from self.half_period()

    def rep_start(self):
        assert (yield self.scl_i) == 1
        assert (yield self.sda_i) == 0
        yield self.scl_o.eq(0)
        yield Tick() # tHD;DAT
        yield self.sda_o.eq(1)
        yield from self.half_period()
        yield self.scl_o.eq(1)
        yield from self.half_period()
        yield from self.start()

    def stop(self):
        yield self.scl_o.eq(0)
        yield Tick() # tHD;DAT
        yield self.sda_o.eq(0)
        yield from self.half_period()
        yield self.scl_o.eq(1)
        yield from self.half_period()
        yield self.sda_o.eq(1)
        yield from self.half_period()

    def write_bit(self, bit):
        assert (yield self.scl_i) == 1
        yield self.scl_o.eq(0)
        yield Tick() # tHD;DAT
        yield self.sda_o.eq(bit)
        yield from self.half_period()
        yield self.scl_o.eq(1)
        yield from self.half_period()
        yield self.sda_o.eq(1)

    def write_octet(self, octet):
        for bit in range(8)[::-1]:
            yield from self.write_bit((octet >> bit) & 1)

    def read_bit(self):
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


class I2CTargetTestCase(I2CTestCase):
    def setUp(self):
        self.tb = I2CTargetTestbench()

    def simulationSetUp(self, tb):
        yield tb.dut.address.eq(0b0101000)

    @simulation_test(testbench=True)
    def test_addr_shift(self, tb):
        yield tb.dut.address.eq(0b1111111)
        yield from self.assertState(tb, "IDLE")
        yield from tb.start()
        yield from self.assertState(tb, "START")
        for _ in range(8):
            yield from tb.write_bit(1)
            yield from self.assertState(tb, "ADDR-SHIFT")

    @simulation_test(testbench=True)
    def test_addr_stop(self, tb):
        yield from tb.start()
        yield from tb.write_bit(0)
        yield from tb.write_bit(1)
        yield from tb.stop()
        yield from self.assertState(tb, "IDLE")

    @simulation_test(testbench=True)
    def test_addr_nak(self, tb):
        yield from tb.start()
        yield from tb.write_octet(0b11110001)
        self.assertEqual((yield from tb.read_bit()), 1)
        yield from self.assertState(tb, "IDLE")

    @simulation_test(testbench=True)
    def test_addr_r_ack(self, tb):
        yield from tb.start()
        yield from tb.write_octet(0b01010001)
        yield tb.scl_o.eq(0)
        yield from self.assertCondition(tb, lambda: (yield tb.dut.start))
        yield Tick()
        yield from self.assertState(tb, "ADDR-ACK")
        self.assertEqual((yield tb.sda_i), 0)
        yield Tick()
        yield tb.scl_o.eq(1)
        yield from tb.half_period()
        yield from self.assertState(tb, "READ-SHIFT")

    @simulation_test(testbench=True)
    def test_addr_w_ack(self, tb):
        yield from tb.start()
        yield from tb.write_octet(0b01010000)
        yield tb.scl_o.eq(0)
        yield from self.assertCondition(tb, lambda: (yield tb.dut.start))
        yield Tick()
        yield from self.assertState(tb, "ADDR-ACK")
        self.assertEqual((yield tb.sda_i), 0)
        yield Tick()
        yield tb.scl_o.eq(1)
        yield from tb.half_period()
        yield tb.scl_o.eq(0)
        yield from tb.half_period()
        yield from self.assertState(tb, "WRITE-SHIFT")

    def start_addr(self, tb, read):
        yield from tb.start()
        yield from tb.write_octet(0b01010000 | read)
        self.assertEqual((yield from tb.read_bit()), 0)

    @simulation_test(testbench=True)
    def test_write_shift(self, tb):
        yield from self.start_addr(tb, read=False)
        yield from tb.write_octet(0b10100101)
        yield tb.scl_o.eq(0)
        yield from self.assertCondition(tb, lambda: (yield tb.dut.write))
        self.assertEqual((yield tb.dut.data_i), 0b10100101)
        yield Tick()
        yield from self.assertState(tb, "WRITE-ACK")

    @simulation_test(testbench=True)
    def test_read_shift(self, tb):
        yield from tb.start()
        yield from tb.write_octet(0b01010001)
        yield tb.scl_o.eq(0)
        yield from tb.half_period()
        self.assertEqual((yield tb.sda_i), 0)
        # this sequence ensures combinatorial feedback works
        yield Tick()
        yield tb.scl_o.eq(1)
        yield Tick()
        yield tb.dut.data_o.eq(0b10100101)
        yield Tick()
        self.assertEqual((yield tb.dut.read), 1)
        yield Tick()
        yield tb.dut.data_o.eq(0)
        yield Tick()
        self.assertEqual((yield tb.dut.read), 0)
        yield from tb.half_period()
        yield tb.scl_o.eq(1)
        self.assertEqual((yield from tb.read_octet()), 0b10100101)
        yield Tick()
        yield from self.assertState(tb, "READ-ACK")

    @simulation_test(testbench=True)
    def test_write_stop(self, tb):
        yield from self.start_addr(tb, read=False)
        yield from tb.write_bit(0)
        yield from tb.write_bit(1)
        yield from tb.stop()
        yield from self.assertState(tb, "IDLE")

    @simulation_test(testbench=True)
    def test_read_stop(self, tb):
        yield tb.dut.data_o.eq(0b11111111)
        yield from self.start_addr(tb, read=True)
        yield from tb.read_bit()
        yield from tb.read_bit()
        yield from tb.stop()
        yield from self.assertState(tb, "IDLE")

    @simulation_test(testbench=True)
    def test_write_ack(self, tb):
        yield from self.start_addr(tb, read=False)
        yield from tb.write_octet(0b10100101)
        # this sequence ensures combinatorial feedback works
        yield tb.scl_o.eq(0)
        yield Tick()
        yield Tick()
        yield Tick()
        yield tb.dut.ack_o.eq(1)
        self.assertEqual((yield tb.dut.write), 1)
        yield Tick()
        yield tb.dut.ack_o.eq(0)
        yield Tick()
        self.assertEqual((yield tb.dut.write), 0)
        yield from tb.half_period()
        yield tb.scl_o.eq(1)
        self.assertEqual((yield tb.sda_i), 0)

    @simulation_test(testbench=True)
    def test_write_nak(self, tb):
        yield from self.start_addr(tb, read=False)
        yield from tb.write_octet(0b10100101)
        self.assertEqual((yield from tb.read_bit()), 1)

    @simulation_test(testbench=True)
    def test_write_ack_stop(self, tb):
        yield from self.start_addr(tb, read=False)
        yield from tb.write_octet(0b10100101)
        self.assertEqual((yield from tb.read_bit()), 1)
        yield tb.scl_o.eq(0)
        yield tb.sda_o.eq(0)
        yield from tb.half_period()
        yield tb.scl_o.eq(1)
        yield from tb.half_period()
        yield tb.sda_o.eq(1)
        yield from self.assertCondition(tb, lambda: (yield tb.dut.stop))
        yield Tick()
        yield from self.assertState(tb, "IDLE")

    @simulation_test(testbench=True)
    def test_read_ack(self, tb):
        yield tb.dut.data_o.eq(0b10101010)
        yield from self.start_addr(tb, read=True)
        self.assertEqual((yield from tb.read_octet()), 0b10101010)
        yield from tb.write_bit(0)
        yield from self.assertState(tb, "READ-SHIFT")

    @simulation_test(testbench=True)
    def test_read_nak(self, tb):
        yield tb.dut.data_o.eq(0b10100101)
        yield from self.start_addr(tb, read=True)
        self.assertEqual((yield from tb.read_octet()), 0b10100101)
        yield from tb.write_bit(0)
        yield from self.assertState(tb, "READ-SHIFT")

    @simulation_test(testbench=True)
    def test_read_nak_stop(self, tb):
        yield tb.dut.data_o.eq(0b10100101)
        yield from self.start_addr(tb, read=True)
        self.assertEqual((yield from tb.read_octet()), 0b10100101)
        yield tb.scl_o.eq(0)
        yield from tb.half_period()
        yield from self.assertState(tb, "READ-ACK")
        yield tb.scl_o.eq(1)
        yield from self.assertCondition(tb, lambda: (yield tb.dut.stop))
        yield Tick()
        yield from self.assertState(tb, "IDLE")

    @simulation_test(testbench=True)
    def test_read_ack_read(self, tb):
        yield tb.dut.data_o.eq(0b10100101)
        yield from self.start_addr(tb, read=True)
        self.assertEqual((yield from tb.read_octet()), 0b10100101)
        yield tb.dut.data_o.eq(0b00110011)
        yield from tb.write_bit(0)
        self.assertEqual((yield from tb.read_octet()), 0b00110011)
        yield from tb.write_bit(0)
        yield from self.assertState(tb, "READ-SHIFT")
