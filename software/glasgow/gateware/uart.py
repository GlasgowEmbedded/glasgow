from amaranth import *
from amaranth.lib import io
from amaranth.lib.cdc import FFSynchronizer


__all__ = ["UART"]


class UARTBus(Elaboratable):
    """
    UART bus.

    Provides synchronization.
    """
    def __init__(self, ports):
        self.ports = ports
        
        self.has_rx = self.has_tx = False
        if hasattr(ports, "rx"):
            if ports.rx is not None:
                self.has_rx = True
                self.rx_i = Signal()
        
        if hasattr(ports, "tx"):
            if ports.tx is not None:
                self.has_tx = True
                self.tx_o = Signal(init=1)

    def elaborate(self, platform):
        m = Module()

        if self.has_tx:
            m.submodules.tx_buffer = tx_buffer = io.Buffer("o", self.ports.tx)
            m.d.comb += tx_buffer.o.eq(self.tx_o)

        if self.has_rx:
            m.submodules.rx_buffer = rx_buffer = io.Buffer("i", self.ports.rx)
            m.submodules += FFSynchronizer(rx_buffer.i, self.rx_i, init=1)

        return m


class UART(Elaboratable):
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
    def __init__(self, ports, bit_cyc, data_bits=8, parity="none", max_bit_cyc=None):
        if max_bit_cyc is not None:
            self.max_bit_cyc = max_bit_cyc
        else:
            self.max_bit_cyc = bit_cyc

        self.data_bits = data_bits
        self.parity = parity

        self.bit_cyc = Signal(range(self.max_bit_cyc + 1), init=bit_cyc)

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

        self.bus = UARTBus(ports)

    def elaborate(self, platform):
        m = Module()

        m.submodules.bus = self.bus

        def calc_parity(sig, kind):
            if kind in ("zero", "none"):
                return C(0, 1)
            elif kind == "one":
                return C(1, 1)
            else:
                bits, _ = sig.shape()
                even_parity = sum([sig[b] for b in range(bits)]) & 1
                if kind == "odd":
                    return ~even_parity
                elif kind == "even":
                    return even_parity
                else:
                    assert False

        if self.bus.has_rx:
            rx_start = Signal()
            rx_timer = Signal(range(self.max_bit_cyc))
            rx_stb   = Signal()
            rx_shreg = Signal(self.data_bits)
            rx_bitno = Signal(range(len(rx_shreg)))

            m.d.comb += self.rx_err.eq(self.rx_ferr | self.rx_ovf | self.rx_perr)

            with m.If(rx_start):
                m.d.sync += rx_timer.eq(self.bit_cyc >> 1)
            with m.Elif(rx_timer == 0):
                m.d.sync += rx_timer.eq(self.bit_cyc - 1)
            with m.Else():
                m.d.sync += rx_timer.eq(rx_timer - 1)
            m.d.comb += rx_stb.eq(rx_timer == 0)

            with m.FSM():
                with m.State("IDLE"):
                    m.d.sync += self.rx_rdy.eq(0),
                    with m.If(~self.bus.rx_i):
                        m.d.comb += rx_start.eq(1)
                        m.next = "START"
                with m.State("START"):
                    with m.If(rx_stb):
                        m.next = "DATA"
                with m.State("DATA"):
                    with m.If(rx_stb):
                        m.d.sync += [
                            rx_shreg.eq(Cat(rx_shreg[1:], self.bus.rx_i)),
                            rx_bitno.eq(rx_bitno + 1),
                        ]
                        with m.If(rx_bitno == len(rx_shreg) - 1):
                            if self.parity == "none":
                                m.next = "STOP"
                            else:
                                m.next = "PARITY"
                with m.State("PARITY"):
                    with m.If(rx_stb):
                        with m.If(self.bus.rx_i == calc_parity(rx_shreg, self.parity)):
                            m.next = "STOP"
                        with m.Else():
                            m.d.comb += self.rx_perr.eq(1)
                            m.next = "IDLE"

                with m.State("STOP"):
                    with m.If(rx_stb):
                        with m.If(~self.bus.rx_i):
                            m.d.comb += self.rx_ferr.eq(1)
                            m.next = "IDLE"
                        with m.Else():
                            m.d.sync += self.rx_data.eq(rx_shreg)
                            m.next = "READY"
                with m.State("READY"):
                    m.d.sync += self.rx_rdy.eq(1)
                    with m.If(self.rx_ack):
                        m.next = "IDLE"
                    with m.Elif(~self.bus.rx_i):
                        m.d.comb += self.rx_ovf.eq(1)
                        m.next = "IDLE"

        ###

        if self.bus.has_tx:
            tx_start  = Signal()
            tx_timer  = Signal(range(self.max_bit_cyc))
            tx_stb    = Signal()
            tx_shreg  = Signal(self.data_bits)
            tx_bitno  = Signal(range(len(tx_shreg)))
            tx_parity = Signal()

            with m.If(tx_start | (tx_timer == 0)):
                m.d.sync += tx_timer.eq(self.bit_cyc - 1)
            with m.Else():
                m.d.sync += tx_timer.eq(tx_timer - 1)
            m.d.comb += tx_stb.eq(tx_timer == 0)

            with m.FSM():
                with m.State("IDLE"):
                    m.d.comb += self.tx_rdy.eq(1)
                    with m.If(self.tx_ack):
                        m.d.comb += tx_start.eq(1)
                        m.d.sync += [
                            tx_shreg.eq(self.tx_data),
                            self.bus.tx_o.eq(0),
                        ]
                        if self.parity != "none":
                            m.d.sync += tx_parity.eq(calc_parity(self.tx_data, self.parity))
                        m.next = "START"
                    with m.Else():
                        m.d.sync += self.bus.tx_o.eq(1)
                with m.State("START"):
                    with m.If(tx_stb):
                        m.d.sync += [
                            self.bus.tx_o.eq(tx_shreg[0]),
                            tx_shreg.eq(Cat(tx_shreg[1:], C(0,1))),
                        ]
                        m.next = "DATA"
                with m.State("DATA"):
                    with m.If(tx_stb):
                        m.d.sync += tx_bitno.eq(tx_bitno + 1)
                        with m.If(tx_bitno != len(tx_shreg) - 1):
                            m.d.sync += [
                                self.bus.tx_o.eq(tx_shreg[0]),
                                tx_shreg.eq(Cat(tx_shreg[1:], C(0,1))),
                            ]
                        with m.Else():
                            if self.parity == "none":
                                m.d.sync += self.bus.tx_o.eq(1)
                                m.next = "STOP"
                            else:
                                m.d.sync += self.bus.tx_o.eq(tx_parity)
                                m.next = "PARITY"
                with m.State("PARITY"):
                    with m.If(tx_stb):
                        m.d.sync += self.bus.tx_o.eq(1),
                        m.next = "STOP"
                with m.State("STOP"):
                    with m.If(tx_stb):
                        m.next = "IDLE"

        return m
