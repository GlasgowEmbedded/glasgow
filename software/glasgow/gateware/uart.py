from nmigen.compat import *
from nmigen.compat.genlib.cdc import MultiReg


__all__ = ["UART"]


class UARTBus(Module):
    """
    UART bus.

    Provides synchronization.
    """
    def __init__(self, pads, invert_rx, invert_tx):
        self.has_rx = hasattr(pads, "rx_t")
        if self.has_rx:
            self.rx_t = pads.rx_t
            self.rx_i = Signal()

        self.has_tx = hasattr(pads, "tx_t")
        if self.has_tx:
            self.tx_t = pads.tx_t
            self.tx_o = Signal(reset=1)

        ###

        if self.has_tx:
            self.comb += self.tx_t.oe.eq(1)
            if invert_tx:
                self.comb += self.tx_t.o.eq(~self.tx_o)
            else:
                self.comb += self.tx_t.o.eq(self.tx_o)

        if self.has_rx:
            if invert_rx:
                self.specials += MultiReg(~self.rx_t.i, self.rx_i, reset=1)
            else:
                self.specials += MultiReg(self.rx_t.i, self.rx_i, reset=1)


class UART(Module):
    """
    Asynchronous serial receiver-transmitter.

    Any number of data bits, any parity, and 1 stop bit are supported. Baud rate may be changed
    at runtime.

    :type bit_cyc: int
    :param bit_cyc:
        Initial value for bit time, expressed as a multiple of system clock periods.
    :type data_bits: int
    :param data_bits:
        Data bit count.
    :type parity: str
    :param parity:
        Parity, one of ``"none"`` (default), ``"zero"``, ``"one"``, ``"even"``, ``"odd"``.
    :type max_bit_cyc: int
    :param max_bit_cyc:
        Maximum possible value for ``bit_cyc`` that can be configured at runtime.
    :type invert_rx: bool
    :param invert_rx:
        Invert the line signal (=idle low) for RX
    :type invert_tx: bool
    :param invert_tx:
        Invert the line signal (=idle low) for TX

    :attr bit_cyc:
        Register with the current value for bit time, minus one.

    :attr rx_data:
        Received data. Valid when ``rx_rdy`` is active.
    :attr rx_rdy:
        Receive ready flag. Becomes active after a stop bit of a valid frame is received.
    :attr rx_ack:
        Receive acknowledgement. If active when ``rx_rdy`` is active, ``rx_rdy`` is reset,
        and the receive state machine becomes ready for another frame.
    :attr rx_ferr:
        Receive frame error flag. Active for one cycle when a frame error is detected.
    :attr rx_perr:
        Receive parity error flag. Active for one cycle when a parity error is detected.
    :attr rx_ovf:
        Receive overflow flag. Active for one cycle when a new frame is started while ``rx_rdy``
        is still active. Afterwards, the receive state machine is reset and starts receiving
        the new frame.
    :attr rx_err:
        Receive error flag. Logical OR of all other error flags.

    :attr tx_data:
        Data to transmit. Sampled when ``tx_rdy`` is active.
    :attr tx_rdy:
        Transmit ready flag. Active while the transmit state machine is idle, and can accept
        data to transmit.
    :attr tx_ack:
        Transmit acknowledgement. If active when ``tx_rdy`` is active, ``tx_rdy`` is reset,
        ``tx_data`` is sampled, and the transmit state machine starts transmitting a frame.
    """
    def __init__(self, pads, bit_cyc, data_bits=8, parity="none", max_bit_cyc=None,
                 invert_rx=False, invert_tx=False):
        if max_bit_cyc is None:
            max_bit_cyc = bit_cyc
        self.bit_cyc = Signal(reset=bit_cyc, max=max_bit_cyc + 1)

        self.rx_data = Signal(data_bits)
        self.rx_rdy  = Signal()
        self.rx_ack  = Signal()
        self.rx_ferr = Signal()
        self.rx_perr = Signal()
        self.rx_ovf  = Signal()
        self.rx_err  = Signal()

        self.tx_data = Signal(data_bits)
        self.tx_rdy  = Signal()
        self.tx_ack  = Signal()

        self.submodules.bus = bus = UARTBus(pads, invert_rx=invert_rx, invert_tx=invert_tx)

        ###

        def calc_parity(sig, kind):
            if kind in ("zero", "none"):
                return C(0, 1)
            elif kind == "one":
                return C(1, 1)
            else:
                bits, _ = value_bits_sign(sig)
                even_parity = sum([sig[b] for b in range(bits)]) & 1
                if kind == "odd":
                    return ~even_parity
                elif kind == "even":
                    return even_parity
                else:
                    assert False

        if bus.has_rx:
            rx_start = Signal()
            rx_timer = Signal(max=max_bit_cyc)
            rx_stb   = Signal()
            rx_shreg = Signal(data_bits)
            rx_bitno = Signal(max=rx_shreg.nbits)

            self.comb += self.rx_err.eq(self.rx_ferr | self.rx_ovf | self.rx_perr)

            self.sync += [
                If(rx_start,
                    rx_timer.eq(self.bit_cyc >> 1),
                ).Elif(rx_timer == 0,
                    rx_timer.eq(self.bit_cyc - 1)
                ).Else(
                    rx_timer.eq(rx_timer - 1)
                )
            ]
            self.comb += rx_stb.eq(rx_timer == 0)

            self.submodules.rx_fsm = FSM(reset_state="IDLE")
            self.rx_fsm.act("IDLE",
                NextValue(self.rx_rdy, 0),
                If(~bus.rx_i,
                    rx_start.eq(1),
                    NextState("START")
                )
            )
            self.rx_fsm.act("START",
                If(rx_stb,
                    NextState("DATA")
                )
            )
            self.rx_fsm.act("DATA",
                If(rx_stb,
                    NextValue(rx_shreg, Cat(rx_shreg[1:8], bus.rx_i)),
                    NextValue(rx_bitno, rx_bitno + 1),
                    If(rx_bitno == rx_shreg.nbits - 1,
                        If(parity == "none",
                            NextState("STOP")
                        ).Else(
                            NextState("PARITY")
                        )
                    )
                )
            )
            self.rx_fsm.act("PARITY",
                If(rx_stb,
                    If(bus.rx_i == calc_parity(rx_shreg, parity),
                        NextState("STOP")
                    ).Else(
                        self.rx_perr.eq(1),
                        NextState("IDLE")
                    )
                )
            )
            self.rx_fsm.act("STOP",
                If(rx_stb,
                    If(~bus.rx_i,
                        self.rx_ferr.eq(1),
                        NextState("IDLE")
                    ).Else(
                        NextValue(self.rx_data, rx_shreg),
                        NextState("READY")
                    )
                )
            )
            self.rx_fsm.act("READY",
                NextValue(self.rx_rdy, 1),
                If(self.rx_ack,
                    NextState("IDLE")
                ).Elif(~bus.rx_i,
                    self.rx_ovf.eq(1),
                    NextState("IDLE")
                )
            )

        ###

        if bus.has_tx:
            tx_start  = Signal()
            tx_timer  = Signal(max=max_bit_cyc)
            tx_stb    = Signal()
            tx_shreg  = Signal(data_bits)
            tx_bitno  = Signal(max=tx_shreg.nbits)
            tx_parity = Signal()

            self.sync += [
                If(tx_start | (tx_timer == 0),
                    tx_timer.eq(self.bit_cyc - 1)
                ).Else(
                    tx_timer.eq(tx_timer - 1)
                )
            ]
            self.comb += tx_stb.eq(tx_timer == 0)

            self.submodules.tx_fsm = FSM(reset_state="IDLE")
            self.tx_fsm.act("IDLE",
                self.tx_rdy.eq(1),
                If(self.tx_ack,
                    tx_start.eq(1),
                    NextValue(tx_shreg, self.tx_data),
                    If(parity != "none",
                        NextValue(tx_parity, calc_parity(self.tx_data, parity))
                    ),
                    NextValue(bus.tx_o, 0),
                    NextState("START")
                ).Else(
                    NextValue(bus.tx_o, 1)
                )
            )
            self.tx_fsm.act("START",
                If(tx_stb,
                    NextValue(bus.tx_o, tx_shreg[0]),
                    NextValue(tx_shreg, Cat(tx_shreg[1:8], 0)),
                    NextState("DATA")
                )
            )
            self.tx_fsm.act("DATA",
                If(tx_stb,
                    NextValue(tx_bitno, tx_bitno + 1),
                    If(tx_bitno != tx_shreg.nbits - 1,
                        NextValue(bus.tx_o, tx_shreg[0]),
                        NextValue(tx_shreg, Cat(tx_shreg[1:8], 0)),
                    ).Else(
                        If(parity == "none",
                            NextValue(bus.tx_o, 1),
                            NextState("STOP")
                        ).Else(
                            NextValue(bus.tx_o, tx_parity),
                            NextState("PARITY")
                        )
                    )
                )
            )
            self.tx_fsm.act("PARITY",
                If(tx_stb,
                    NextValue(bus.tx_o, 1),
                    NextState("STOP")
                )
            )
            self.tx_fsm.act("STOP",
                If(tx_stb,
                    NextState("IDLE")
                )
            )

# -------------------------------------------------------------------------------------------------

import unittest

from . import simulation_test


class UARTTestbench(Module):
    def __init__(self):
        self.rx_t = TSTriple(reset_i=1)
        self.rx_i = self.rx_t.i

        self.tx_t = TSTriple()
        self.tx_o = self.tx_t.o

        self.bit_cyc = 4
        self.submodules.dut = UART(pads=self, bit_cyc=self.bit_cyc)


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
        yield tb.rx_i.eq(bit)
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
        yield tb.rx_i.eq(0)
        yield # CDC latency
        yield from self.cyc(tb, err=tb.dut.rx_ferr)

    @simulation_test
    def test_rx_ovf(self, tb):
        yield from self.byte(tb, [1, 0, 1, 0, 0, 1, 0, 1])
        yield tb.rx_i.eq(0)
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
        self.assertEqual((yield tb.tx_o), bit)

    def start(self, tb, data):
        self.assertEqual((yield tb.tx_o), 1)
        self.assertEqual((yield tb.dut.tx_rdy), 1)
        yield tb.dut.tx_data.eq(data)
        yield tb.dut.tx_ack.eq(1)
        yield
        yield tb.dut.tx_ack.eq(0)
        yield
        self.assertEqual((yield tb.dut.tx_rdy), 0)
        self.assertEqual((yield tb.tx_o), 0)
        yield from self.half_cyc(tb)
        self.assertEqual((yield tb.tx_o), 0)

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
