import argparse
import logging
import math
import asyncio
from amaranth import *
from amaranth.lib import io, cdc, enum, data
from ... import *

MAX_SEND_BITS = 2**16
assert MAX_SEND_BITS <= 2**16, "must update state machine to be able to send more"

ZERO_BITS_AFTER_POLL = 40
# Number of zero bits defined in ISSP programming specification differs.
# revK says 40 zero bits
# revI says 30 zero bits
# Applying more zero bits then necessary is fine. (The spec explicity says that 0 padding after any 22-bit mnemonic is permitted)

class _Command(data.Struct):
    class Kind(enum.Enum):
        ASSERT_RESET   = 0x1
        DEASSERT_RESET = 0x2
        FLOAT_RESET    = 0x3
        SEND_BITS      = 0x4
        READ_BYTE      = 0x5
        WAIT_PENDING   = 0x6
        FLOAT_SCLK     = 0x7
        LOW_SCLK       = 0x8

    kind: Kind
    params: data.UnionLayout({
        "send_bits": data.StructLayout({
            "do_poll": unsigned(1),
            "needs_single_clock_pulse_for_poll": unsigned(1),
            "needs_arbitrary_clocks_for_poll": unsigned(1),
        }),
        "read_byte": data.StructLayout({
            "reg_not_mem": unsigned(1),
        }),
    })

assert _Command.as_shape().size <= 8, "Command must fit in a byte"

class PinDriver():
    def __init__(self, m, ports, name, synchronize_input=False, edge_detect_input=False):
        self._name = name
        self.m = m
        self.buffer = io.FFBuffer("io", ports[name])
        m.submodules[name] = self.buffer
        self.o = Signal(name=name + "_o")
        self.o_nxt = Signal(name=name + "_o_nxt")
        self.oe = Signal(name=name + "_oe")
        self.oe_nxt = Signal(name=name + "_oe_nxt")

        # Here are the flipflops that mirror the state of what's in the IO buffer:
        m.d.sync += (self.o.eq(self.o_nxt),
                     self.oe.eq(self.oe_nxt))

        # This is the deafult case, the pin will always keep it's previous state, unless modified
        m.d.comb += (self.o_nxt.eq(self.o),
                     self.oe_nxt.eq(self.oe))

        # Here we connect up to the buffer:
        m.d.comb += self.buffer.oe.eq(self.oe_nxt)
        m.d.comb += self.buffer.o.eq(self.o_nxt)

        if synchronize_input:
            self.i_sync = Signal(name=name + "_i_sync")
            synchronizer = cdc.FFSynchronizer(self.buffer.i, self.i_sync)
            m.submodules[name + "_synchronizer"] = synchronizer

            if edge_detect_input:
                self.i_sync_ff = Signal(name=name + "i_sync_ff")
                m.d.sync += self.i_sync_ff.eq(self.i_sync)


    def negedge(self):
        return (self.i_sync == 0) & (self.i_sync_ff == 1)

    def posedge(self):
        return (self.i_sync == 1) & (self.i_sync_ff == 0)

    def drive(self, value):
        self.m.d.comb += (self.o_nxt.eq(value),
                          self.oe_nxt.eq(1))

    def release(self):
        self.m.d.comb += self.oe_nxt.eq(0)

class ISSPHostSubtarget(Elaboratable):
    def __init__(self, ports, out_fifo, in_fifo, period_cyc, io_decay_wait_cyc, after_reset_wait_cyc, sample_before_falling_edge_cyc=1):
        """
            sample_before_falling_edge_cyc: Specifies how many system clock cycles before the falling edge
            we should be sampling the data signal at. (as seen from outside of the FPGA).
            If you set it to 3, while running at 8MHz, the signal will be sampled at exactly the rising
            edge, like the ISSP spec specifies. Setting it to a lower number we can further optimize timing.
        """
        self._ports      = ports
        self._out_fifo   = out_fifo
        self._in_fifo    = in_fifo
        self._period_cyc = period_cyc
        self._clock_high_cyc = period_cyc // 2
        self._clock_low_cyc = period_cyc - self._clock_high_cyc
        self._io_decay_plus_sample_wait_cyc = io_decay_wait_cyc + 3
        self._after_reset_wait_cyc = after_reset_wait_cyc
        self._timer_max_cyc = max(self._clock_high_cyc, self._clock_low_cyc, self._io_decay_plus_sample_wait_cyc)
        assert sample_before_falling_edge_cyc <= 3
        self._sample_data_delayed = 3 - sample_before_falling_edge_cyc
        assert self._sample_data_delayed < self._period_cyc + self._clock_low_cyc

    def elaborate(self, platform):
        m = Module()

        i_fifo = self._in_fifo.stream
        o_fifo = self._out_fifo.stream

        total_bits_counter = Signal(range(max(MAX_SEND_BITS, 8)))

        sclk = PinDriver(m, self._ports, "sclk")
        sdata = PinDriver(m, self._ports, "sdata", synchronize_input=True, edge_detect_input=True)

        sdata_negedge_seen = Signal()
        m.d.sync += sdata_negedge_seen.eq(sdata_negedge_seen | sdata.negedge())

        xres_pin_exists = self._ports.xres is not None
        if xres_pin_exists:
            xres = PinDriver(m, self._ports, "xres", synchronize_input=True)
        else:
            may_be_after_power_cycle = Signal(init=1)

        # Use a single timer for various waits
        timer = Signal(range(self._timer_max_cyc))
        timer_running = Signal()
        timer_mode_clock = Signal()
        timer_done_oneshot = Signal()
        timer_done = Signal()
        m.d.comb += timer_done.eq(timer_done_oneshot | ~timer_running)

        with m.If(timer_running):
            with m.If(timer == 0):
                with m.If(sclk.o & timer_mode_clock):
                    m.d.sync += timer.eq(self._clock_low_cyc - 1)
                    sclk.drive(0)
                with m.Else():
                    m.d.sync += timer_running.eq(0)
                    m.d.comb += timer_done_oneshot.eq(1)
            with m.Else():
                m.d.sync += timer.eq(timer - 1)

        def start_clock_cycle():
            """
            This will start an sclk clock cycle, first a rising edge is sent,
            then, when the timer runs out, it will send a falling edge and it
            will auto-restart itself. When the clock cycle is complete timer_done
            will go high
            """
            m.d.sync += timer.eq(self._clock_high_cyc - 1)
            m.d.sync += timer_running.eq(1)
            m.d.sync += timer_mode_clock.eq(1)
            sclk.drive(1)

        def start_simple_timer(cycles):
            """
            This is used to just implement delays without any action being taken.
            When the timer expires, it won't restart, and timer_done will go high.
            """
            assert cycles >= 1
            assert cycles - 1 < self._timer_max_cyc
            m.d.sync += timer.eq(cycles - 1)
            m.d.sync += timer_running.eq(1)
            m.d.sync += timer_mode_clock.eq(0)

        cmd = Signal(_Command)
        byte = Signal(8)
        bit_in_byte_counter = Signal(3)

        do_sample_data = Signal()
        do_sample_data_delayed = do_sample_data
        for i in range(self._sample_data_delayed):
            do_sample_data_delayed_new = Signal(name=f"do_sample_data_delayed_{i}")
            m.d.sync += do_sample_data_delayed_new.eq(do_sample_data_delayed)
            do_sample_data_delayed = do_sample_data_delayed_new
        with m.If(do_sample_data_delayed):
            m.d.sync += byte.eq((byte << 1) | sdata.i_sync)

        with m.FSM():
            with m.State("IDLE"):
                m.d.comb += o_fifo.ready.eq(1)
                with m.If(o_fifo.valid):
                    m.d.sync += cmd.eq(o_fifo.payload)
                    m.next = "COMMAND"
            with m.State("COMMAND"):
                with m.Switch(cmd.kind):
                    with m.Case(_Command.Kind.ASSERT_RESET):
                        if xres_pin_exists:
                            xres.drive(1)
                        else:
                            m.d.sync += may_be_after_power_cycle.eq(1)
                        m.next = "IDLE"
                    with m.Case(_Command.Kind.DEASSERT_RESET):
                        if xres_pin_exists:
                            xres.drive(0)
                        m.next = "IDLE"
                    with m.Case(_Command.Kind.FLOAT_RESET):
                        if xres_pin_exists:
                            xres.release()
                        m.next = "IDLE"
                    with m.Case(_Command.Kind.SEND_BITS):
                        m.d.comb += o_fifo.ready.eq(1)
                        with m.If(o_fifo.valid):
                            m.d.sync += total_bits_counter[8:].eq(o_fifo.payload)
                            m.next = "SEND_BITS_WAIT_CNT_LSB"
                    with m.Case(_Command.Kind.READ_BYTE):
                        m.d.comb += o_fifo.ready.eq(1)
                        with m.If(o_fifo.valid):
                            m.d.sync += byte.eq(o_fifo.payload)
                            sdata.drive(1)
                            start_clock_cycle()
                            m.next = "READ_BYTE_SEND_CMD_BIT_0"
                    with m.Case(_Command.Kind.WAIT_PENDING):
                        m.d.comb += i_fifo.payload.eq(0)
                        m.d.comb += i_fifo.valid.eq(1)
                        with m.If(i_fifo.ready):
                            m.next = "IDLE"
                    with m.Case(_Command.Kind.FLOAT_SCLK):
                        sclk.release()
                        m.next = "IDLE"
                    with m.Case(_Command.Kind.LOW_SCLK):
                        sclk.drive(0)
                        m.next = "IDLE"
                    with m.Default():
                        m.next = "IDLE"
            with m.State("SEND_BITS_WAIT_CNT_LSB"):
                m.d.comb += o_fifo.ready.eq(1)
                with m.If(o_fifo.valid):
                    m.d.sync += total_bits_counter[:8].eq(o_fifo.payload)

                    if xres_pin_exists:
                        xres.drive(0)

                        with m.If(((xres.oe == 1) & (xres.o == 1)) |
                                  ((xres.oe == 0) & (xres.i_sync == 1))):
                            start_simple_timer(self._after_reset_wait_cyc - 1)
                            # ^^ - 1 to account for the additional cycle to remove the first data byte from the FIFO
                            m.next = "SEND_BITS_WAIT_AFTER_RESET"
                        with m.Else():
                            m.next = "SEND_BITS_WAIT_DATA"
                    else:
                        # LIMITED support for power-cycle mode:
                        with m.If(may_be_after_power_cycle & sdata_sync):
                            m.d.sync += may_be_after_power_cycle.eq(0)
                            start_simple_timer(self._after_reset_wait_cyc - 1)
                            m.next = "PWR_CYCLE_MODE_WAIT_SDATA_LOW_PLUS_TIME"
                        with m.Else():
                            m.next = "SEND_BITS_WAIT_DATA"
            with m.State("PWR_CYCLE_MODE_WAIT_SDATA_LOW_PLUS_TIME"):
                with m.If(sdata.i_sync):
                    start_simple_timer(self._after_reset_wait_cyc - 1)
                with m.Else():
                    with m.If(timer_done):
                        m.next = "SEND_BITS_WAIT_DATA"
            with m.State("SEND_BITS_WAIT_AFTER_RESET"):
                with m.If(timer_done_oneshot):
                    m.next = "SEND_BITS_WAIT_DATA"
            with m.State("SEND_BITS_WAIT_DATA"):
                m.d.comb += o_fifo.ready.eq(1)
                with m.If(o_fifo.valid):
                    m.d.sync += bit_in_byte_counter.eq(7)
                    m.d.sync += byte.eq(o_fifo.payload[:7])
                    sdata.drive(o_fifo.payload[7])
                    start_clock_cycle()
                    m.next = "SEND_BITS_SHIFT"
            with m.State("SEND_BITS_SHIFT"):
                with m.If(timer_done_oneshot):
                    m.d.sync += byte.eq(byte << 1)
                    sdata.drive(byte[6])
                    m.d.sync += bit_in_byte_counter.eq(bit_in_byte_counter - 1)
                    m.d.sync += total_bits_counter.eq(total_bits_counter - 1)

                    with m.If(total_bits_counter == 0):
                        sdata.release()
                        with m.If(cmd.params.send_bits.do_poll):
                            start_simple_timer(self._io_decay_plus_sample_wait_cyc)
                            m.next = "SEND_BITS_WAIT_IO_DECAY"
                        with m.Else():
                            m.next = "IDLE"
                    with m.Elif(bit_in_byte_counter == 0):
                        m.d.comb += o_fifo.ready.eq(1)
                        with m.If(o_fifo.valid):
                            m.d.sync += byte.eq(o_fifo.payload[:7])
                            sdata.drive(o_fifo.payload[7])
                            start_clock_cycle()
                        with m.Else():
                            m.next = "SEND_BITS_WAIT_DATA"
                    with m.Else():
                        start_clock_cycle()
            with m.State("SEND_BITS_WAIT_IO_DECAY"):
                with m.If(timer_done_oneshot):
                    with m.If(cmd.params.send_bits.needs_single_clock_pulse_for_poll):
                        start_clock_cycle()
                    m.d.sync += sdata_negedge_seen.eq(0)
                    m.next = "SEND_BITS_WAIT_POLL"
            with m.State("SEND_BITS_WAIT_POLL"):
                # Some versions of the ISSP spec say that the chip can be in this
                # state with SDATA high for 100ms, other versions say 200ms, For
                # now we don't implement a time-out.
                with m.If(sdata_negedge_seen & ~sdata.i_sync & ~timer_running):
                    m.next = "IDLE"
                with m.Elif(cmd.params.send_bits.needs_arbitrary_clocks_for_poll & ~sdata_negedge_seen & ~sdata.i_sync & timer_done):
                    start_clock_cycle()
            with m.State("SEND_BITS_ZERO_AFTER_POLL"):
                with m.If(timer_done_oneshot):
                    m.d.sync += total_bits_counter.eq(total_bits_counter - 1)
                    with m.If(total_bits_counter == 0):
                        sdata.release()
                        m.next = "IDLE"
                    with m.Else():
                        start_clock_cycle()
            with m.State("READ_BYTE_SEND_CMD_BIT_0"):
                with m.If(timer_done_oneshot):
                    sdata.drive(cmd.params.read_byte.reg_not_mem)
                    start_clock_cycle()
                    m.next = "READ_BYTE_SEND_CMD_BIT_1"
            with m.State("READ_BYTE_SEND_CMD_BIT_1"):
                with m.If(timer_done_oneshot):
                    sdata.drive(1)
                    start_clock_cycle()
                    m.next = "READ_BYTE_SEND_CMD_BIT_2"
            with m.State("READ_BYTE_SEND_CMD_BIT_2"):
                with m.If(timer_done_oneshot):
                    sdata.drive(byte[7])
                    m.d.sync += bit_in_byte_counter.eq(7)
                    start_clock_cycle()
                    m.next = "READ_BYTE_SHIFT_ADDRESS"
            with m.State("READ_BYTE_SHIFT_ADDRESS"):
                with m.If(timer_done_oneshot):
                    sdata.drive(byte[6])
                    m.d.sync += byte.eq(byte << 1)
                    m.d.sync += bit_in_byte_counter.eq(bit_in_byte_counter - 1)
                    start_clock_cycle()
                    with m.If(bit_in_byte_counter == 0):
                        sdata.release()
                        m.next = "READ_BYTE_WAIT_TURNAROUND_1"
            with m.State("READ_BYTE_WAIT_TURNAROUND_1"):
                with m.If(timer_done_oneshot):
                    start_clock_cycle()
                    m.d.sync += bit_in_byte_counter.eq(7)
                    m.next = "READ_BYTE_SHIFT"
            with m.State("READ_BYTE_SHIFT"):
                with m.If((timer == 0) & (sclk.o) & (bit_in_byte_counter != 7)):
                    m.d.comb += do_sample_data.eq(1)
                with m.If(timer_done_oneshot):
                    start_clock_cycle()
                    m.d.sync += bit_in_byte_counter.eq(bit_in_byte_counter - 1)
                    with m.If(bit_in_byte_counter == 0):
                        start_clock_cycle()
                        m.next = "READ_BYTE_WAIT_TURNAROUND_2"
            with m.State("READ_BYTE_WAIT_TURNAROUND_2"):
                with m.If((timer == 0) & (sclk.o)):
                    m.d.comb += do_sample_data.eq(1)
                with m.If(timer_done_oneshot):
                    sdata.drive(1)
                    # Note: comparing to the ISSP specification it might seem that
                    # we are missing a high-z clock cycle here, however this is
                    # documented incorrectly: final bus turnaround happens between
                    # falling-edge and rising-edge, there's only half a cycle for bus
                    # turnaround, rather then the full 1.5 cycles shown on the example
                    # waveform.
                    start_clock_cycle()
                    m.next = "READ_BYTE_WAIT_TURNAROUND_3"
            with m.State("READ_BYTE_WAIT_TURNAROUND_3"):
                with m.If(timer_done):
                    m.d.comb += i_fifo.payload.eq(byte)
                    m.d.comb += i_fifo.valid.eq(1)
                    sdata.release()
                    with m.If(i_fifo.ready):
                        m.next = "IDLE"

        return m

assert Const({"kind": 1}, _Command).as_value().value == 1, "Code below assumes the command kind is at offset zero"

DO_POLL_OFFSET = 4
NEEDS_SINGLE_CLOCK_PULSE_FOR_POLL_OFFSET = 5
NEEDS_ARBITRARY_CLOCKS_FOR_POLL_OFFSET = 6
REG_NOT_MEM_OFFSET = 4

assert Const({"params": {"send_bits": {"do_poll": 1}}}, _Command).as_value().value == 1 << DO_POLL_OFFSET, "Please update the above constants"
assert Const({"params": {"send_bits": {"needs_single_clock_pulse_for_poll": 1}}}, _Command).as_value().value == 1 << NEEDS_SINGLE_CLOCK_PULSE_FOR_POLL_OFFSET, "Please update the above constants"
assert Const({"params": {"send_bits": {"needs_arbitrary_clocks_for_poll": 1}}}, _Command).as_value().value == 1 << NEEDS_ARBITRARY_CLOCKS_FOR_POLL_OFFSET, "Please update the above constants"
assert Const({"params": {"read_byte": {"reg_not_mem": 1}}}, _Command).as_value().value == 1 << REG_NOT_MEM_OFFSET, "Please update the above constants"

class ISSPHostInterface:
    def __init__(self, iface, logger):
        self.lower = iface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    async def wait_pending(self):
        """
        Make sure that pending commands are completed.

        This command causes a "0" byte to be returned to the USB host,
        and we wait to receive that byte. After we've received it, we know
        that all state-machine commands sent before have finished.
        """
        await self.lower.write([_Command.Kind.WAIT_PENDING.value])
        await self.lower.flush()
        assert 0 == (await self.lower.read(1))[0]

    async def assert_xres(self):
        """
        Assert xres (set to 1)  (Also, in case we're in power-cycle mode, tell the state machine that we're about to power-cycle)
        """
        await self.lower.write([_Command.Kind.ASSERT_RESET.value])
        await self.wait_pending()

    async def deassert_xres(self):
        """
        Deassert xres (set to 0)
        """
        await self.lower.write([_Command.Kind.DEASSERT_RESET.value])
        await self.wait_pending()

    async def float_xres(self):
        """
        Float xres if it was previously driven
        """
        await self.lower.write([_Command.Kind.FLOAT_RESET.value])
        await self.wait_pending()

    async def float_sclk(self):
        """
        Float sclk if it was previously driven
        """
        await self.lower.write([_Command.Kind.FLOAT_SCLK.value])

    async def low_sclk(self):
        """
        Drive sclk with a strong low value
        """
        await self.lower.write([_Command.Kind.LOW_SCLK.value])

    async def _send_zero_bits(self, cnt_bits = ZERO_BITS_AFTER_POLL):
        cnt_enc = cnt_bits - 1
        cnt_bytes = (cnt_bits + 7)//8
        zero_blist = [0] * cnt_bytes
        await self.lower.write([
            _Command.Kind.SEND_BITS.value, cnt_enc >> 8, cnt_enc & 0xff, *zero_blist])

    async def send_bits(self, cnt_bits, value, do_poll=1, do_zero_bits=1, needs_single_clock_pulse_for_poll=1, needs_arbitrary_clocks_for_poll=0):
        """
        Send a vector of up to MAX_SEND_BITS bits, while also optionally performing
        "Wait and Poll", and optionally send the 40 terminating zero-bits.

        The bits are specified as an integer, and number of bits to send.
        The value is sent MSB-first.
        """
        assert cnt_bits <= MAX_SEND_BITS
        assert (value >> cnt_bits) == 0
        cnt_enc = cnt_bits - 1
        cnt_enc_msb = cnt_enc >> 8
        cnt_enc_lsb = cnt_enc & 0xff
        bits_left = cnt_bits
        blist = []
        while bits_left > 0:
            blist.append(((value << 8) >> bits_left) & 0xff)
            bits_left -= 8
        await self.lower.write([
            (_Command.Kind.SEND_BITS.value |
             (do_poll << DO_POLL_OFFSET) |
             (needs_single_clock_pulse_for_poll << NEEDS_SINGLE_CLOCK_PULSE_FOR_POLL_OFFSET) |
             (needs_arbitrary_clocks_for_poll << NEEDS_ARBITRARY_CLOCKS_FOR_POLL_OFFSET)
            ), cnt_enc_msb, cnt_enc_lsb, *blist])
        if do_zero_bits:
            await self._send_zero_bits()

    async def send_bitstring(self, bitstring, do_poll=1, do_zero_bits=1, needs_single_clock_pulse_for_poll=1, needs_arbitrary_clocks_for_poll=0):
        """
        Send a vector of up to MAX_SEND_BITS bits, while also optionally performing
        "Wait and Poll", and optionally send the 40 terminating zero-bits.

        The bits are specified as a string of "1" and "0", and the bits are sent in the specified order.
        """
        cnt_enc = len(bitstring) - 1
        cnt_enc_msb = cnt_enc >> 8
        cnt_enc_lsb = cnt_enc & 0xff
        blist = []
        for index in range(0, len(bitstring), 8):
            piece = bitstring[index:index+8]
            if len(piece) < 8:
                piece = piece + ("0" * (8 - len(piece)))
            blist.append(int(piece, 2))
        await self.lower.write([
            (_Command.Kind.SEND_BITS.value |
             (do_poll << DO_POLL_OFFSET) |
             (needs_single_clock_pulse_for_poll << NEEDS_SINGLE_CLOCK_PULSE_FOR_POLL_OFFSET) |
             (needs_arbitrary_clocks_for_poll << NEEDS_ARBITRARY_CLOCKS_FOR_POLL_OFFSET)
            ), cnt_enc_msb, cnt_enc_lsb, *blist])
        if do_zero_bits:
            await self._send_zero_bits()

    async def read_bytes(self, address, cnt_bytes=1, reg_not_mem=0):
        """
        Executes one or more READ-BYTE sequences, as per ISSP sepcification.
        Can be used for "Verify Silicon ID Procedure", and for "Verify Procedure".
        Note that we deviate from the specification, which incorrectly shows
        1.5 cycles of bus turnaround time in the waveforms, when going from the target
        driving the data line to the host driving the data line. Real chips have half
        a cycle of turnaround time instead, and inserting the extra clock cycles causes
        a lock-up. (The first bus turnaround between address and data bits of 1.5 cycles
        is correctly described)
        """
        send_bytes = []
        for offset in range(cnt_bytes):
            send_bytes.append(_Command.Kind.READ_BYTE.value | (reg_not_mem << REG_NOT_MEM_OFFSET))
            send_bytes.append(address + offset)
        await self.lower.write(send_bytes)
        return list(await self.lower.read(cnt_bytes))

    async def write_bytes(self, address, bytes, reg_not_mem=0):
        """
        Executes one or more WRITE-BYTE sequences, as per ISSP specification.
        """
        for byte in bytes:
            if reg_not_mem:
                first_three_bits = 0b110
            else:
                first_three_bits = 0b100
            encoded_bits = (((((first_three_bits << 8) | address) << 8) | byte) << 3) | 0b111
            encoded_bits_count = 3 + 8 + 8 + 3
            await self.send_bits(encoded_bits_count, encoded_bits, do_poll=0, do_zero_bits=0)
            address += 1

class ISSPHostApplet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "initiate ISSP transactions"
    description = """
    Initiate ISSP transactions.

    ISSP stands for In-system serial programming protocol,
    used for programming Cypress PSoC 1 devices.
    """
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_argument(parser, "sclk", default=True)
        access.add_pin_argument(parser, "sdata", default=True)
        access.add_pin_argument(parser, "xres")

        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=float, default=1000,
            help="set SCLK frequency to FREQ kHz (default: %(default)s)")

        parser.add_argument(
            "--io-decay-wait-time", metavar="IODECAY", type=float, default=1000,
            help="specify the time it takes for sdata to settle to 0 through " +
                 "the weak pull-down in the target, as IODECAY ns (default: %(default)s)")

        parser.add_argument(
            "--xres-to-sclk-time", metavar="XRESTOSCLK", type=float, default=1000,
            help="specify the minimum time after xres is deasserted until the first " +
                 "sclk rising edge as XRESTOSCLK ns (default: %(default)s)")
        # Note: the above constraint is not specified by Cypress. The author has measured
        # this to be between 312ns and 333 ns on a particular CY8C21434. The default value
        # is a guess.


    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        io_decay_wait_us = 1.0
        if args.frequency > 8000.001:
            self.logger.warn(f"Frequency set to {args.frequency} kHz. According to the ISSP specification this may be too high!")
        period_cyc = math.ceil(target.sys_clk_freq / (args.frequency * 1000))
        after_reset_wait_cyc=math.ceil(target.sys_clk_freq * args.xres_to_sclk_time / 1000_000_000.)
        txresacq_cyc = 98 * target.sys_clk_freq / 1000. / 1000.
        if after_reset_wait_cyc + period_cyc * 8.5 > txresacq_cyc:
            if hasattr(args, "pin_xres") and args.pin_xres is not None:
                self.logger.warn(f"Frequency set to {args.frequency} kHz. This may be too slow to satisfy tXREQACQ/tXRESINI, so it's possible the device might not enter programming mode.")
        iface.add_subtarget(ISSPHostSubtarget(
            ports=iface.get_port_group(
                sclk=args.pin_sclk,
                sdata=args.pin_sdata,
                xres=args.pin_xres,
            ),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(),
            period_cyc=period_cyc,
            io_decay_wait_cyc=math.ceil(target.sys_clk_freq * args.io_decay_wait_time / 1000_000_000.),
            after_reset_wait_cyc=after_reset_wait_cyc,
        ))

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        issp_iface = ISSPHostInterface(iface, self.logger)
        return issp_iface

