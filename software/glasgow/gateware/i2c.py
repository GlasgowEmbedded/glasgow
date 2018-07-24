# I2C reference: https://www.nxp.com/docs/en/user-guide/UM10204.pdf

from migen import *
from migen.genlib.fsm import *
from migen.genlib.cdc import MultiReg


__all__ = ['I2CSlave']


class I2CBus(Module):
    """
    I2C bus.

    Decodes bus conditions (start, stop, sample and setup) and provides synchronization.
    """
    def __init__(self, pads):
        self.scl_t = pads.scl_t
        self.sda_t = pads.sda_t

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
            self.scl_t.o.eq(0),
            self.scl_t.oe.eq(~self.scl_o),
            self.sda_t.o.eq(0),
            self.sda_t.oe.eq(~self.sda_o),

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
            MultiReg(self.scl_t.i, self.scl_i, reset=1),
            MultiReg(self.sda_t.i, self.sda_i, reset=1),
        ]


class I2CMaster(Module):
    """
    Simple I2C master.

    Generates start and stop conditions, and transmits and receives octets.
    Clock stretching is supported.

    :param period_cyc:
        Bus clock period, as a multiple of system clock period.
    :type period_cyc: int

    :attr busy:
        Busy flag. Low if the master state machine is idle, high otherwise.
    :attr start:
        Start strobe. When ``busy`` is low, asserting ``start`` for one cycle generates
        a start or repeated start condition on the bus. Ignored when ``busy`` is high.
    :attr stop:
        Stop strobe. When ``busy`` is low, asserting ``stop`` for one cycle generates
        a stop condition on the bus. Ignored when ``busy`` is high.
    :attr write:
        Write strobe. When ``busy`` is low, asserting ``write`` for one cycle receives
        an octet on the bus and latches it to ``data_o``, after which the acknowledge bit
        is asserted if ``ack_i`` is high. Ignored when ``busy`` is high.
    :attr data_i:
        Data octet to be transmitted. Latched immediately after ``write`` is asserted.
    :attr ack_o:
        Received acknowledge bit.
    :attr read:
        Read strobe. When ``busy`` is low, asserting ``read`` for one cycle latches
        ``data_i`` and transmits it on the bus, after which the acknowledge bit
        from the bus is latched to ``ack_o``. Ignored when ``busy`` is high.
    :attr data_o:
        Received data octet.
    :attr ack_i:
        Acknowledge bit to be transmitted. Latched immediately after ``read`` is asserted.
    """
    def __init__(self, pads, period_cyc, clk_stretch=True):
        self.busy   = Signal(reset=1)
        self.start  = Signal()
        self.stop   = Signal()
        self.read   = Signal()
        self.data_i = Signal(8)
        self.ack_o  = Signal()
        self.write  = Signal()
        self.data_o = Signal(8)
        self.ack_i  = Signal()

        self.submodules.bus = bus = I2CBus(pads)

        ###

        period_cyc = int(period_cyc)

        timer = Signal(max=period_cyc)
        stb   = Signal()

        self.sync += [
            If((timer == 0) | ~self.busy,
                timer.eq(period_cyc // 2)
            ).Else(
                timer.eq(timer - 1)
            )
        ]
        self.comb += stb.eq(timer == 0)

        bitno   = Signal(max=8)
        r_shreg = Signal(8)
        w_shreg = Signal(8)
        r_ack   = Signal()

        self.submodules.fsm = FSM(reset_state="IDLE")

        def low(pin_i, pin_o, state, next_state, *exprs):
            self.fsm.act(state,
                If(stb,
                   NextValue(pin_o, 0),
                   NextState(next_state),
                   *exprs
                )
            )
        def high(pin_i, pin_o, state, next_state, *exprs):
            self.fsm.act(state,
                If(stb,
                    NextValue(pin_o, 1)
                ).Elif(pin_o == 1,
                    If(~clk_stretch | (pin_i == 1),
                        NextState(next_state),
                        *exprs
                    )
                )
            )
        def scl_l(state, next_state, *exprs):
            low(bus.scl_i, bus.scl_o, state, next_state, *exprs)
        def scl_h(state, next_state, *exprs):
            high(bus.scl_i, bus.scl_o, state, next_state, *exprs)
        def sda_l(state, next_state, *exprs):
            low(bus.sda_i, bus.sda_o, state, next_state, *exprs)
        def sda_h(state, next_state, *exprs):
            high(bus.sda_i, bus.sda_o, state, next_state, *exprs)

        self.fsm.act("IDLE",
            NextValue(self.busy, 1),
            If(self.start,
                If(bus.scl_i & bus.sda_i,
                    NextState("START-SDA-L")
                ).Elif(~bus.scl_i,
                    NextState("START-SCL-H")
                ).Elif(bus.scl_i,
                    NextState("START-SCL-L")
                )
            ).Elif(self.stop,
                If(bus.scl_i & ~bus.sda_o,
                    NextState("STOP-SDA-H")
                ).Elif(~bus.scl_i,
                    NextState("STOP-SCL-H")
                ).Elif(bus.scl_i,
                    NextState("STOP-SCL-L")
                )
            ).Elif(self.write,
                NextValue(w_shreg, self.data_i),
                NextState("WRITE-SCL-L")
            ).Elif(self.read,
                NextValue(r_ack, self.ack_i),
                NextState("READ-SCL-L")
            ).Else(
                NextValue(self.busy, 0)
            )
        )
        # start
        scl_l("START-SCL-L", "START-SDA-H")
        sda_h("START-SDA-H", "START-SCL-H")
        scl_h("START-SCL-H", "START-SDA-L")
        sda_l("START-SDA-L", "IDLE")
        # stop
        scl_l("STOP-SCL-L",  "STOP-SDA-L")
        sda_l("STOP-SDA-L",  "STOP-SCL-H")
        scl_h("STOP-SCL-H",  "STOP-SDA-H")
        sda_h("STOP-SDA-H",  "IDLE")
        # write
        scl_l("WRITE-SCL-L", "WRITE-SCL-H",
            NextValue(bus.sda_o, w_shreg[7]),
            NextValue(w_shreg, Cat(0, w_shreg[0:7])),
        )
        scl_h("WRITE-SCL-H", "WRITE-SCL-L",
            NextValue(bitno, bitno + 1),
            If(bitno == 7,
                NextState("WRITE-ACK-SCL-L")
            )
        )
        scl_l("WRITE-ACK-SCL-L", "WRITE-ACK-SCL-H",
            NextValue(bus.sda_o, 1)
        )
        scl_h("WRITE-ACK-SCL-H", "HOLD",
            NextValue(self.ack_o, ~bus.sda_i)
        )
        # read
        scl_l("READ-SCL-L",  "READ-SCL-H",
            NextValue(bus.sda_o, 1)
        )
        scl_h("READ-SCL-H",  "READ-SCL-L",
            NextValue(r_shreg, Cat(bus.sda_i, r_shreg[0:7])),
            NextValue(bitno, bitno + 1),
            If(bitno == 7,
                NextState("READ-ACK-SCL-L")
            )
        )
        scl_l("READ-ACK-SCL-L", "READ-ACK-SCL-H",
            NextValue(bus.sda_o, ~r_ack)
        )
        scl_h("READ-ACK-SCL-H", "HOLD",
            NextValue(self.data_o, r_shreg)
        )
        # hold
        self.fsm.act("HOLD",
            If(stb,
                NextState("IDLE")
            )
        )


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
    :attr read:
        Read strobe. Active for one cycle immediately before latching ``data_o``.
    :attr data_o:
        Data octet to be transmitted to the master. Latched immedately after receiving
        a read command.
    """
    def __init__(self, pads):
        self.address = Signal(7)
        self.start   = Signal()
        self.stop    = Signal()
        self.write   = Signal()
        self.data_i  = Signal(8)
        self.ack_o   = Signal()
        self.read    = Signal()
        self.data_o  = Signal(8)
        self.ack_i   = Signal()

        self.submodules.bus = bus = I2CBus(pads)

        ###

        bitno   = Signal(max=8)
        shreg_i = Signal(8)
        shreg_o = Signal(8)

        self.submodules.fsm = FSM(reset_state="IDLE")
        self.comb += self.stop.eq(self.fsm.after_entering("IDLE"))
        self.fsm.act("IDLE",
            If(bus.start,
                NextState("START"),
            )
        )
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
                    If(shreg_i[1:] == self.address,
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
                NextState("START")
            ).Elif(bus.setup,
                If(~shreg_i[0],
                    self.start.eq(1),
                    NextValue(bus.sda_o, 1),
                    NextState("WRITE-SHIFT")
                )
            ).Elif(bus.sample,
                If(shreg_i[0],
                    self.start.eq(1),
                    NextState("READ-SHIFT"),
                    NextValue(shreg_o, self.data_o)
                )
            )
        )
        self.fsm.act("WRITE-SHIFT",
            If(bus.stop,
                NextState("IDLE")
            ).Elif(bus.start,
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
                NextState("START")
            ).Elif(~bus.scl_i & self.ack_o,
                NextValue(bus.sda_o, 0)
            ).Elif(bus.setup,
                NextValue(bus.sda_o, 1),
                NextState("WRITE-SHIFT")
            )
        )
        self.comb += self.read.eq(self.fsm.before_entering("READ-SHIFT"))
        self.fsm.act("READ-SHIFT",
            If(bus.stop,
                NextState("IDLE")
            ).Elif(bus.start,
                NextState("START")
            ).Elif(bus.setup,
                NextValue(bitno, bitno + 1),
                NextValue(bus.sda_o, shreg_o[7]),
                NextValue(shreg_o, shreg_o << 1),
            ).Elif(bus.sample,
                If(bitno == 0,
                    NextValue(bus.sda_o, 1),
                    NextState("READ-ACK")
                )
            )
        )
        self.fsm.act("READ-ACK",
            If(bus.stop,
                NextState("IDLE")
            ).Elif(bus.start,
                NextState("START")
            ).Elif(bus.sample,
                If(~bus.sda_i,
                    NextState("READ-SHIFT")
                ).Else(
                    NextState("IDLE")
                )
            )
        )

# -------------------------------------------------------------------------------------------------

import functools
import unittest

from migen.fhdl import verilog


def simulation_test(case):
    @functools.wraps(case)
    def wrapper(self):
        def setup_wrapper():
            if hasattr(self, "simulationSetUp"):
                yield from self.simulationSetUp(self.tb)
            yield from case(self, self.tb)
        run_simulation(self.tb, setup_wrapper(), vcd_name="test.vcd")
    return wrapper


class I2CTestbench(Module):
    def __init__(self):
        self.scl_t = TSTriple()
        self.sda_t = TSTriple()

        self.scl_i = self.scl_t.i
        self.scl_o = Signal(reset=1)
        self.sda_i = self.sda_t.i
        self.sda_o = Signal(reset=1)

        self.period_cyc = 16

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
        for _ in range(self.period_cyc // 2):
            yield

    def wait_for(self, fn):
        for _ in range(self.wait_cyc):
            yield
            if (yield from fn()):
                return True
        return False


class I2CTestCase(unittest.TestCase):
    def assertState(self, tb, state):
        self.assertEqual((yield from tb.dut_state()), state)

    def assertCondition(self, tb, fn):
        self.assertTrue((yield from self.tb.wait_for(fn)))


class I2CMasterTestbench(I2CTestbench):
    def __init__(self):
        super().__init__()

        self.submodules.dut = I2CMaster(pads=self, period_cyc=self.period_cyc)
        self.wait_cyc = self.period_cyc * 3

    def strobe(self, signal):
        yield signal.eq(1)
        yield
        yield signal.eq(0)
        yield

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


class I2CMasterTestCase(I2CTestCase):
    def setUp(self):
        self.tb = I2CMasterTestbench()

    @simulation_test
    def test_start(self, tb):
        yield from tb.start()
        yield from self.assertState(tb, "START-SDA-L")
        yield from self.assertCondition(tb, lambda: (yield tb.dut.bus.start))
        self.assertEqual((yield tb.dut.busy), 0)

    @simulation_test
    def test_repeated_start(self, tb):
        yield tb.dut.bus.sda_o.eq(0)
        yield
        yield
        yield from tb.start()
        yield from self.assertState(tb, "START-SCL-L")
        yield from self.assertCondition(tb, lambda: (yield tb.dut.bus.start))
        self.assertEqual((yield tb.dut.busy), 0)

    def start(self, tb):
        yield from tb.start()
        yield from self.assertCondition(tb, lambda: (yield tb.dut.bus.start))

    @simulation_test
    def test_stop(self, tb):
        yield tb.dut.bus.sda_o.eq(0)
        yield
        yield
        yield from tb.stop()
        yield from self.assertState(tb, "STOP-SDA-H")
        yield from self.assertCondition(tb, lambda: (yield tb.dut.bus.stop))
        self.assertEqual((yield tb.dut.busy), 0)

    def stop(self, tb):
        yield from tb.stop()
        yield from self.assertCondition(tb, lambda: (yield tb.dut.bus.stop))

    def write(self, tb, data, bits, ack):
        yield from tb.write(data)
        for bit in bits:
            yield from self.assertState(tb, "WRITE-SCL-L")
            yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 0)
            yield from self.assertState(tb, "WRITE-SCL-H")
            yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 1)
            self.assertEqual((yield tb.sda_i), bit)
            yield
        yield from self.assertState(tb, "WRITE-ACK-SCL-L")
        yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 0)
        yield tb.sda_o.eq(not ack)
        yield from self.assertState(tb, "WRITE-ACK-SCL-H")
        yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 1)
        yield tb.sda_o.eq(1)
        self.assertEqual((yield tb.dut.busy), 1)
        yield from self.tb.half_period()
        yield
        yield
        self.assertEqual((yield tb.dut.busy), 0)
        self.assertEqual((yield tb.dut.ack_o), ack)

    @simulation_test
    def test_write_ack(self, tb):
        yield tb.dut.bus.sda_o.eq(0)
        yield
        yield
        yield from self.write(tb, 0xA5, [1, 0, 1, 0, 0, 1, 0, 1], 1)

    @simulation_test
    def test_write_nak(self, tb):
        yield tb.dut.bus.sda_o.eq(0)
        yield
        yield
        yield from self.write(tb, 0x5A, [0, 1, 0, 1, 1, 0, 1, 0], 0)

    @simulation_test
    def test_write_tx(self, tb):
        yield from self.start(tb)
        yield from self.write(tb, 0x55, [0, 1, 0, 1, 0, 1, 0, 1], 1)
        yield from self.write(tb, 0x33, [0, 0, 1, 1, 0, 0, 1, 1], 0)
        yield from self.stop(tb)
        yield
        yield
        self.assertEqual((yield tb.sda_i), 1)
        self.assertEqual((yield tb.scl_i), 1)

    def read(self, tb, data, bits, ack):
        yield from tb.read(ack)
        for bit in bits:
            yield from self.assertState(tb, "READ-SCL-L")
            yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 0)
            yield tb.sda_o.eq(bit)
            yield from self.assertState(tb, "READ-SCL-H")
            yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 1)
            yield
        yield tb.sda_o.eq(1)
        yield from self.assertState(tb, "READ-ACK-SCL-L")
        yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 0)
        yield from self.assertState(tb, "READ-ACK-SCL-H")
        yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 1)
        self.assertEqual((yield tb.sda_i), not ack)
        self.assertEqual((yield tb.dut.busy), 1)
        yield from self.tb.half_period()
        yield
        yield
        self.assertEqual((yield tb.dut.busy), 0)
        self.assertEqual((yield tb.dut.data_o), data)

    @simulation_test
    def test_read_ack(self, tb):
        yield tb.dut.bus.sda_o.eq(0)
        yield
        yield
        yield from self.read(tb, 0xA5, [1, 0, 1, 0, 0, 1, 0, 1], 1)

    @simulation_test
    def test_read_nak(self, tb):
        yield tb.dut.bus.sda_o.eq(0)
        yield
        yield
        yield from self.read(tb, 0x5A, [0, 1, 0, 1, 1, 0, 1, 0], 0)

    @simulation_test
    def test_read_tx(self, tb):
        yield from self.start(tb)
        yield from self.read(tb, 0x55, [0, 1, 0, 1, 0, 1, 0, 1], 1)
        yield from self.read(tb, 0x33, [0, 0, 1, 1, 0, 0, 1, 1], 0)
        yield from self.stop(tb)
        yield
        yield
        self.assertEqual((yield tb.sda_i), 1)
        self.assertEqual((yield tb.scl_i), 1)


class I2CSlaveTestbench(I2CTestbench):
    def __init__(self):
        super().__init__()

        self.submodules.dut = I2CSlave(pads=self)
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
        yield # tHD;DAT
        yield self.sda_o.eq(1)
        yield from self.half_period()
        yield self.scl_o.eq(1)
        yield from self.half_period()
        yield from self.start()

    def stop(self):
        yield self.scl_o.eq(0)
        yield # tHD;DAT
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


class I2CSlaveTestCase(I2CTestCase):
    def setUp(self):
        self.tb = I2CSlaveTestbench()

    def simulationSetUp(self, tb):
        yield tb.dut.address.eq(0b0101000)

    @simulation_test
    def test_addr_shift(self, tb):
        yield tb.dut.address.eq(0b1111111)
        yield from self.assertState(tb, "IDLE")
        yield from tb.start()
        yield from self.assertState(tb, "START")
        for _ in range(8):
            yield from tb.write_bit(1)
            yield from self.assertState(tb, "ADDR-SHIFT")

    @simulation_test
    def test_addr_stop(self, tb):
        yield from tb.start()
        yield from tb.write_bit(0)
        yield from tb.write_bit(1)
        yield from tb.stop()
        yield from self.assertState(tb, "IDLE")

    @simulation_test
    def test_addr_nak(self, tb):
        yield from tb.start()
        yield from tb.write_octet(0b11110001)
        self.assertEqual((yield from tb.read_bit()), 1)
        yield from self.assertState(tb, "IDLE")

    @simulation_test
    def test_addr_r_ack(self, tb):
        yield from tb.start()
        yield from tb.write_octet(0b01010001)
        yield tb.scl_o.eq(0)
        yield from tb.half_period()
        yield from self.assertState(tb, "ADDR-ACK")
        self.assertEqual((yield tb.sda_i), 0)
        yield tb.scl_o.eq(1)
        yield from self.assertCondition(tb, lambda: (yield tb.dut.start))
        yield
        yield from self.assertState(tb, "READ-SHIFT")

    @simulation_test
    def test_addr_w_ack(self, tb):
        yield from tb.start()
        yield from tb.write_octet(0b01010000)
        self.assertEqual((yield from tb.read_bit()), 0)
        yield from self.assertState(tb, "ADDR-ACK")
        yield tb.scl_o.eq(0)
        yield from self.assertCondition(tb, lambda: (yield tb.dut.start))
        yield
        yield from self.assertState(tb, "WRITE-SHIFT")

    def start_addr(self, tb, read):
        yield from tb.start()
        yield from tb.write_octet(0b01010000 | read)
        self.assertEqual((yield from tb.read_bit()), 0)

    @simulation_test
    def test_write_shift(self, tb):
        yield from self.start_addr(tb, read=False)
        yield from tb.write_octet(0b10100101)
        yield tb.scl_o.eq(0)
        yield from self.assertCondition(tb, lambda: (yield tb.dut.write))
        self.assertEqual((yield tb.dut.data_i), 0b10100101)
        yield
        yield from self.assertState(tb, "WRITE-ACK")

    @simulation_test
    def test_read_shift(self, tb):
        yield from tb.start()
        yield from tb.write_octet(0b01010001)
        yield tb.scl_o.eq(0)
        yield from tb.half_period()
        self.assertEqual((yield tb.sda_i), 0)
        # this sequence ensures combinatorial feedback works
        yield tb.scl_o.eq(1)
        yield
        yield
        yield tb.dut.data_o.eq(0b10100101)
        yield
        self.assertEqual((yield tb.dut.read), 1)
        yield tb.dut.data_o.eq(0)
        yield
        self.assertEqual((yield tb.dut.read), 0)
        yield from tb.half_period()
        yield tb.scl_o.eq(1)
        self.assertEqual((yield from tb.read_octet()), 0b10100101)
        yield
        yield from self.assertState(tb, "READ-ACK")

    @simulation_test
    def test_write_stop(self, tb):
        yield from self.start_addr(tb, read=False)
        yield from tb.write_bit(0)
        yield from tb.write_bit(1)
        yield from tb.stop()
        yield from self.assertState(tb, "IDLE")

    @simulation_test
    def test_read_stop(self, tb):
        yield tb.dut.data_o.eq(0b11111111)
        yield from self.start_addr(tb, read=True)
        yield from tb.read_bit()
        yield from tb.read_bit()
        yield from tb.stop()
        yield from self.assertState(tb, "IDLE")

    @simulation_test
    def test_write_ack(self, tb):
        yield from self.start_addr(tb, read=False)
        yield from tb.write_octet(0b10100101)
        # this sequence ensures combinatorial feedback works
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
        yield from self.start_addr(tb, read=False)
        yield from tb.write_octet(0b10100101)
        self.assertEqual((yield from tb.read_bit()), 1)

    @simulation_test
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
        yield
        yield from self.assertState(tb, "IDLE")

    @simulation_test
    def test_read_ack(self, tb):
        yield tb.dut.data_o.eq(0b10100101)
        yield from self.start_addr(tb, read=True)
        self.assertEqual((yield from tb.read_octet()), 0b10100101)
        yield from tb.write_bit(0)
        yield from self.assertState(tb, "READ-SHIFT")

    @simulation_test
    def test_read_nak(self, tb):
        yield tb.dut.data_o.eq(0b10100101)
        yield from self.start_addr(tb, read=True)
        self.assertEqual((yield from tb.read_octet()), 0b10100101)
        yield from tb.write_bit(0)
        yield from self.assertState(tb, "READ-SHIFT")

    @simulation_test
    def test_read_nak_stop(self, tb):
        yield tb.dut.data_o.eq(0b10100101)
        yield from self.start_addr(tb, read=True)
        self.assertEqual((yield from tb.read_octet()), 0b10100101)
        yield tb.scl_o.eq(0)
        yield from tb.half_period()
        yield from self.assertState(tb, "READ-ACK")
        yield tb.scl_o.eq(1)
        yield from self.assertCondition(tb, lambda: (yield tb.dut.stop))
        yield
        yield from self.assertState(tb, "IDLE")


class _DummyPads(Module):
    def __init__(self):
        self.scl_t = TSTriple()
        self.sda_t = TSTriple()


if __name__ == "__main__":
    verilog.convert(I2CMaster(_DummyPads(), 16)).write("i2cmaster.v")
    verilog.convert(I2CSlave(_DummyPads())).write("i2cslave.v")
