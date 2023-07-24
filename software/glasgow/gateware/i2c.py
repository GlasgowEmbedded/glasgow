# I2C reference: https://www.nxp.com/docs/en/user-guide/UM10204.pdf

from amaranth import *
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.io import Pin


__all__ = ["I2CInitiator", "I2CTarget"]


class I2CBus(Elaboratable):
    """
    I2C bus.

    Decodes bus conditions (start, stop, sample and setup) and provides synchronization.
    """
    def __init__(self, pads):
        self.scl_t = pads.scl_t if hasattr(pads, "scl_t") else pads.scl
        self.sda_t = pads.sda_t if hasattr(pads, "sda_t") else pads.sda

        self.scl_i = Signal()
        self.scl_o = Signal(reset=1)
        self.sda_i = Signal()
        self.sda_o = Signal(reset=1)

        self.sample = Signal(name="bus_sample")
        self.setup  = Signal(name="bus_setup")
        self.start  = Signal(name="bus_start")
        self.stop   = Signal(name="bus_stop")

    def elaborate(self, platform):
        m = Module()

        scl_r = Signal(reset=1)
        sda_r = Signal(reset=1)

        m.d.comb += [
            self.scl_t.o.eq(0),
            self.scl_t.oe.eq(~self.scl_o),
            self.sda_t.o.eq(0),
            self.sda_t.oe.eq(~self.sda_o),

            self.sample.eq(~scl_r & self.scl_i),
            self.setup.eq(scl_r & ~self.scl_i),
            self.start.eq(self.scl_i & sda_r & ~self.sda_i),
            self.stop.eq(self.scl_i & ~sda_r & self.sda_i),
        ]
        m.d.sync += [
            scl_r.eq(self.scl_i),
            sda_r.eq(self.sda_i),
        ]
        m.submodules += [
            FFSynchronizer(self.scl_t.i, self.scl_i, reset=1),
            FFSynchronizer(self.sda_t.i, self.sda_i, reset=1),
        ]

        return m


class I2CInitiator(Elaboratable):
    """
    Simple I2C transaction initiator.

    Generates start and stop conditions, and transmits and receives octets.
    Clock stretching is supported.

    :param period_cyc:
        Bus clock period, as a multiple of system clock period.
    :type period_cyc: int
    :param clk_stretch:
        If true, SCL will be monitored for devices stretching the clock. Otherwise,
        only internally generated SCL is considered.
    :type clk_stretch: bool

    :attr busy:
        Busy flag. Low if the state machine is idle, high otherwise.
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
        self.period_cyc = int(period_cyc)
        self.clk_stretch = clk_stretch

        self.busy   = Signal(reset=1)
        self.start  = Signal()
        self.stop   = Signal()
        self.read   = Signal()
        self.data_i = Signal(8)
        self.ack_o  = Signal()
        self.write  = Signal()
        self.data_o = Signal(8)
        self.ack_i  = Signal()

        self.bus = I2CBus(pads)

    def elaborate(self, platform):
        m = Module()

        m.submodules.bus = self.bus

        timer = Signal(range(self.period_cyc))
        stb   = Signal()

        with m.If((timer == 0) | ~self.busy):
            m.d.sync += timer.eq(self.period_cyc // 4)
        with m.Elif((not self.clk_stretch) | (self.bus.scl_o == self.bus.scl_i)):
            m.d.sync += timer.eq(timer - 1)
        m.d.comb += stb.eq(timer == 0)

        bitno   = Signal(range(8))
        r_shreg = Signal(8)
        w_shreg = Signal(8)
        r_ack   = Signal()

        with m.FSM() as fsm:
            self._fsm = fsm
            def scl_l(state, next_state, *exprs):
                with m.State(state):
                    with m.If(stb):
                        m.d.sync += self.bus.scl_o.eq(0)
                        m.next = next_state
                        m.d.sync += exprs

            def scl_h(state, next_state, *exprs):
                with m.State(state):
                    with m.If(stb):
                        m.d.sync += self.bus.scl_o.eq(1)
                    with m.Elif(self.bus.scl_o == 1):
                        with m.If((not self.clk_stretch) | (self.bus.scl_i == 1)):
                            m.next = next_state
                            m.d.sync += exprs

            def stb_x(state, next_state, *exprs, bit7_next_state=None):
                with m.State(state):
                    with m.If(stb):
                        m.next = next_state
                        if bit7_next_state is not None:
                            with m.If(bitno == 7):
                                m.next = bit7_next_state
                        m.d.sync += exprs

            with m.State("IDLE"):
                m.d.sync += self.busy.eq(1)
                with m.If(self.start):
                    with m.If(self.bus.scl_i & self.bus.sda_i):
                        m.next = "START-SDA-L"
                    with m.Elif(~self.bus.scl_i):
                        m.next = "START-SCL-H"
                    with m.Elif(self.bus.scl_i):
                        m.next = "START-SCL-L"
                with m.Elif(self.stop):
                    with m.If(self.bus.scl_i & ~self.bus.sda_o):
                        m.next = "STOP-SDA-H"
                    with m.Elif(~self.bus.scl_i):
                        m.next = "STOP-SCL-H"
                    with m.Elif(self.bus.scl_i):
                        m.next = "STOP-SCL-L"
                with m.Elif(self.write):
                    m.d.sync += w_shreg.eq(self.data_i)
                    m.next = "WRITE-DATA-SCL-L"
                with m.Elif(self.read):
                    m.d.sync += r_ack.eq(self.ack_i)
                    m.next = "READ-DATA-SCL-L"
                with m.Else():
                    m.d.sync += self.busy.eq(0)

            # start
            scl_l("START-SCL-L", "START-SDA-H")
            stb_x("START-SDA-H", "START-SCL-H",
                self.bus.sda_o.eq(1)
            )
            scl_h("START-SCL-H", "START-SDA-L")
            stb_x("START-SDA-L", "IDLE",
                self.bus.sda_o.eq(0)
            )
            # stop
            scl_l("STOP-SCL-L",  "STOP-SDA-L")
            stb_x("STOP-SDA-L",  "STOP-SCL-H",
                self.bus.sda_o.eq(0)
            )
            scl_h("STOP-SCL-H",  "STOP-SDA-H")
            stb_x("STOP-SDA-H",  "IDLE",
                self.bus.sda_o.eq(1)
            )
            # write data
            scl_l("WRITE-DATA-SCL-L", "WRITE-DATA-SDA-X")
            stb_x("WRITE-DATA-SDA-X", "WRITE-DATA-SCL-H",
                self.bus.sda_o.eq(w_shreg[7])
            )
            scl_h("WRITE-DATA-SCL-H", "WRITE-DATA-SDA-N",
                w_shreg.eq(Cat(C(0, 1), w_shreg[0:7]))
            )
            stb_x("WRITE-DATA-SDA-N", "WRITE-DATA-SCL-L",
                bitno.eq(bitno + 1),
                bit7_next_state="WRITE-ACK-SCL-L"
            )
            # write ack
            scl_l("WRITE-ACK-SCL-L", "WRITE-ACK-SDA-H")
            stb_x("WRITE-ACK-SDA-H", "WRITE-ACK-SCL-H",
                self.bus.sda_o.eq(1)
            )
            scl_h("WRITE-ACK-SCL-H", "WRITE-ACK-SDA-N",
                self.ack_o.eq(~self.bus.sda_i)
            )
            stb_x("WRITE-ACK-SDA-N", "IDLE")
            # read data
            scl_l("READ-DATA-SCL-L", "READ-DATA-SDA-H")
            stb_x("READ-DATA-SDA-H", "READ-DATA-SCL-H",
                self.bus.sda_o.eq(1)
            )
            scl_h("READ-DATA-SCL-H", "READ-DATA-SDA-N",
                r_shreg.eq(Cat(self.bus.sda_i, r_shreg[0:7]))
            )
            stb_x("READ-DATA-SDA-N", "READ-DATA-SCL-L",
                bitno.eq(bitno + 1),
                bit7_next_state="READ-ACK-SCL-L"
            )
            # read ack
            scl_l("READ-ACK-SCL-L", "READ-ACK-SDA-X")
            stb_x("READ-ACK-SDA-X", "READ-ACK-SCL-H",
                self.bus.sda_o.eq(~r_ack)
            )
            scl_h("READ-ACK-SCL-H", "READ-ACK-SDA-N",
                self.data_o.eq(r_shreg)
            )
            stb_x("READ-ACK-SDA-N", "IDLE")

        return m


class I2CTarget(Elaboratable):
    """
    Simple I2C target.

    Clock stretching is not supported.
    Builtin responses (identification, general call, etc.) are not provided.

    Note that the start, stop, and restart strobes are transaction delimiters rather than direct
    indicators of bus conditions. A transaction always starts with a start strobe and ends with
    either a stop or a restart strobe. That is, a restart strobe, similarly to a stop strobe, may
    be only followed by another start strobe (or no strobe at all if the device is not addressed
    again).

    :attr address:
        The 7-bit address the target will respond to.
    :attr start:
        Start strobe. Active for one cycle immediately after acknowledging address.
    :attr stop:
        Stop stobe. Active for one cycle immediately after a stop condition that terminates
        a transaction that addressed this device.
    :attr restart:
        Repeated start strobe. Active for one cycle immediately after a repeated start condition
        that terminates a transaction that addressed this device.
    :attr write:
        Write strobe. Active for one cycle immediately after receiving a data octet.
    :attr data_i:
        Data octet received from the initiator. Valid when ``write`` is high.
    :attr ack_o:
        Acknowledge strobe. If active for at least one cycle during the acknowledge bit
        setup period (one half-period after write strobe is asserted), acknowledge is asserted.
        Otherwise, no acknowledge is asserted. May use combinatorial feedback from ``write``.
    :attr read:
        Read strobe. Active for one cycle immediately before latching ``data_o``.
    :attr data_o:
        Data octet to be transmitted to the initiator. Latched immediately after receiving
        a read command.
    """
    def __init__(self, pads):
        self.address = Signal(7)
        self.busy    = Signal() # clock stretching request (experimental, undocumented)
        self.start   = Signal()
        self.stop    = Signal()
        self.restart = Signal()
        self.write   = Signal()
        self.data_i  = Signal(8)
        self.ack_o   = Signal()
        self.read    = Signal()
        self.data_o  = Signal(8)
        self.ack_i   = Signal()

        self.bus = I2CBus(pads)

    def elaborate(self, platform):
        m = Module()

        m.submodules.bus = self.bus

        bitno   = Signal(range(8))
        shreg_i = Signal(8)
        shreg_o = Signal(8)

        with m.FSM() as fsm:
            self._fsm = fsm
            with m.State("IDLE"):
                with m.If(self.bus.start):
                    m.next = "START"
            with m.State("START"):
                with m.If(self.bus.stop):
                    # According to the spec, technically illegal, "but many devices handle
                    # this anyway". Can Philips, like, decide on whether they want it or not??
                    m.next = "IDLE"
                with m.Elif(self.bus.setup):
                    m.d.sync += bitno.eq(0)
                    m.next = "ADDR-SHIFT"
            with m.State("ADDR-SHIFT"):
                with m.If(self.bus.stop):
                    m.next = "IDLE"
                with m.Elif(self.bus.start):
                    m.next = "START"
                with m.Elif(self.bus.sample):
                    m.d.sync += shreg_i.eq((shreg_i << 1) | self.bus.sda_i)
                with m.Elif(self.bus.setup):
                    m.d.sync += bitno.eq(bitno + 1)
                    with m.If(bitno == 7):
                        with m.If(shreg_i[1:] == self.address):
                            m.d.comb += self.start.eq(1)
                            m.d.sync += self.bus.sda_o.eq(0)
                            m.next = "ADDR-ACK"
                        with m.Else():
                            m.next = "IDLE"
            with m.State("ADDR-ACK"):
                with m.If(self.bus.stop):
                    m.d.comb += self.stop.eq(1)
                    m.next = "IDLE"
                with m.Elif(self.bus.start):
                    m.d.comb += self.restart.eq(1)
                    m.next = "START"
                with m.Elif(self.bus.setup):
                    with m.If(~shreg_i[0]):
                        m.d.sync += self.bus.sda_o.eq(1)
                        m.next = "WRITE-SHIFT"
                with m.Elif(self.bus.sample):
                    with m.If(shreg_i[0]):
                        m.d.sync += shreg_o.eq(self.data_o)
                        m.d.comb += self.read.eq(1)
                        m.next = "READ-STRETCH"
            with m.State("WRITE-SHIFT"):
                with m.If(self.bus.stop):
                    m.d.comb += self.stop.eq(1)
                    m.next = "IDLE"
                with m.Elif(self.bus.start):
                    m.d.comb += self.restart.eq(1)
                    m.next = "START"
                with m.Elif(self.bus.sample):
                    m.d.sync += shreg_i.eq((shreg_i << 1) | self.bus.sda_i)
                with m.Elif(self.bus.setup):
                    m.d.sync += bitno.eq(bitno + 1)
                    with m.If(bitno == 7):
                        m.d.sync += self.data_i.eq(shreg_i)
                        m.d.sync += self.write.eq(1)
                        m.next = "WRITE-ACK"
            with m.State("WRITE-ACK"):
                m.d.sync += self.write.eq(0)
                with m.If(self.bus.stop):
                    m.d.comb += self.stop.eq(1)
                    m.next = "IDLE"
                with m.Elif(self.bus.start):
                    m.d.comb += self.restart.eq(1)
                    m.next = "START"
                with m.Elif(self.bus.setup):
                    m.d.sync += self.bus.sda_o.eq(1)
                    m.next = "WRITE-SHIFT"
                with m.Elif(~self.bus.scl_i):
                    m.d.sync += self.bus.scl_o.eq(~self.busy)
                    with m.If(self.ack_o):
                        m.d.sync += self.bus.sda_o.eq(0)
            with m.State("READ-STRETCH"):
                with m.If(self.busy):
                    m.d.sync += shreg_o.eq(self.data_o)
                with m.If(self.bus.stop):
                    m.d.comb += self.stop.eq(1)
                    m.next = "IDLE"
                with m.Elif(self.bus.start):
                    m.next = "START"
                with m.Elif(self.busy):
                    with m.If(~self.bus.scl_i):
                        m.d.sync += self.bus.scl_o.eq(0)
                with m.Else():
                    with m.If(~self.bus.scl_i):
                        m.d.sync += self.bus.sda_o.eq(shreg_o[7])
                    m.d.sync += self.bus.scl_o.eq(1)
                    m.next = "READ-SHIFT"
            with m.State("READ-SHIFT"):
                with m.If(self.bus.stop):
                    m.d.comb += self.stop.eq(1)
                    m.next = "IDLE"
                with m.Elif(self.bus.start):
                    m.d.comb += self.restart.eq(1)
                    m.next = "START"
                with m.Elif(self.bus.setup):
                    m.d.sync += self.bus.sda_o.eq(shreg_o[7])
                with m.Elif(self.bus.sample):
                    m.d.sync += shreg_o.eq(shreg_o << 1)
                    m.d.sync += bitno.eq(bitno + 1)
                    with m.If(bitno == 7):
                        m.next = "READ-ACK"
            with m.State("READ-ACK"):
                with m.If(self.bus.stop):
                    m.d.comb += self.stop.eq(1)
                    m.next = "IDLE"
                with m.Elif(self.bus.start):
                    m.d.comb += self.restart.eq(1)
                    m.next = "START"
                with m.Elif(self.bus.setup):
                    m.d.sync += self.bus.sda_o.eq(1)
                with m.Elif(self.bus.sample):
                    with m.If(~self.bus.sda_i):
                        m.d.sync += shreg_o.eq(self.data_o)
                        m.d.comb += self.read.eq(1)
                        m.next = "READ-STRETCH"
                    with m.Else():
                        m.d.comb += self.stop.eq(1)
                        m.next = "IDLE"

        return m

# -------------------------------------------------------------------------------------------------

import unittest

from . import simulation_test


class I2CTestbench(Elaboratable):
    def __init__(self):
        self.scl_t = Pin(width=1, dir='io')
        self.sda_t = Pin(width=1, dir='io')

        self.scl_i = self.scl_t.i
        self.scl_o = Signal(reset=1)
        self.sda_i = self.sda_t.i
        self.sda_o = Signal(reset=1)

        self.period_cyc = 16

    def elaborate(self, platform):
        m = Module()

        m.submodules.dut = self.dut

        m.d.comb += [
            self.scl_t.i.eq((self.scl_t.o | ~self.scl_t.oe) & self.scl_o),
            self.sda_t.i.eq((self.sda_t.o | ~self.sda_t.oe) & self.sda_o),
        ]

        return m

    def dut_state(self):
        return self.dut._fsm.decoding[(yield self.dut._fsm.state)]

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


class I2CInitiatorTestbench(I2CTestbench):
    def __init__(self):
        super().__init__()

        self.dut = I2CInitiator(pads=self, period_cyc=self.period_cyc)
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


class I2CInitiatorTestCase(I2CTestCase):
    def setUp(self):
        self.tb = I2CInitiatorTestbench()

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
        for n, bit in enumerate(bits):
            yield
            yield
            yield from self.assertState(tb, "WRITE-DATA-SCL-L" if n == 0 else "WRITE-DATA-SDA-N")
            yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 0)
            yield from self.assertState(tb, "WRITE-DATA-SDA-X")
            yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 1)
            self.assertEqual((yield tb.sda_i), bit)
            yield
        yield from self.tb.half_period()
        yield
        yield
        yield from self.assertState(tb, "WRITE-ACK-SCL-L")
        yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 0)
        yield tb.sda_o.eq(not ack)
        yield from self.assertState(tb, "WRITE-ACK-SDA-H")
        yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 1)
        yield tb.sda_o.eq(1)
        self.assertEqual((yield tb.dut.busy), 1)
        yield from self.tb.half_period()
        yield
        yield
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
        for n, bit in enumerate(bits):
            yield
            yield
            yield from self.assertState(tb, "READ-DATA-SCL-L" if n == 0 else "READ-DATA-SDA-N")
            yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 0)
            yield tb.sda_o.eq(bit)
            yield from self.assertState(tb, "READ-DATA-SDA-H")
            yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 1)
            yield
        yield tb.sda_o.eq(1)
        yield from tb.half_period()
        yield
        yield
        yield from self.assertState(tb, "READ-ACK-SCL-L")
        yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 0)
        yield from self.assertState(tb, "READ-ACK-SDA-X")
        yield from self.assertCondition(tb, lambda: (yield tb.scl_i) == 1)
        self.assertEqual((yield tb.sda_i), not ack)
        self.assertEqual((yield tb.dut.busy), 1)
        yield from self.tb.half_period()
        yield
        yield
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
        yield from self.assertCondition(tb, lambda: (yield tb.dut.start))
        yield
        yield from self.assertState(tb, "ADDR-ACK")
        self.assertEqual((yield tb.sda_i), 0)
        yield tb.scl_o.eq(1)
        yield from tb.half_period()
        yield from self.assertState(tb, "READ-SHIFT")

    @simulation_test
    def test_addr_w_ack(self, tb):
        yield from tb.start()
        yield from tb.write_octet(0b01010000)
        yield tb.scl_o.eq(0)
        yield from self.assertCondition(tb, lambda: (yield tb.dut.start))
        yield
        yield from self.assertState(tb, "ADDR-ACK")
        self.assertEqual((yield tb.sda_i), 0)
        yield tb.scl_o.eq(1)
        yield from tb.half_period()
        yield tb.scl_o.eq(0)
        yield from tb.half_period()
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
        yield tb.dut.data_o.eq(0b10101010)
        yield from self.start_addr(tb, read=True)
        self.assertEqual((yield from tb.read_octet()), 0b10101010)
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

    @simulation_test
    def test_read_ack_read(self, tb):
        yield tb.dut.data_o.eq(0b10100101)
        yield from self.start_addr(tb, read=True)
        self.assertEqual((yield from tb.read_octet()), 0b10100101)
        yield tb.dut.data_o.eq(0b00110011)
        yield from tb.write_bit(0)
        self.assertEqual((yield from tb.read_octet()), 0b00110011)
        yield from tb.write_bit(0)
        yield from self.assertState(tb, "READ-SHIFT")
