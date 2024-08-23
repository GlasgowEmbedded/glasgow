import argparse
import logging
import math
import asyncio
from amaranth import *
from amaranth.lib import io, cdc
from ... import *

MAX_SEND_BITS = 2**16
assert MAX_SEND_BITS <= 2**16, "must update state machine to be able to send more"

ZERO_BITS_AFTER_POLL = 40
# Number of zero bits defined in ISSP programming specification differs.
# revK says 40 zero bits
# revH/I says 30 zero bits
# Applying more zero bits then necessary is fine. (The spec explicity says that 0 padding after any 22-bit mnemonic is permitted)

CMD_ASSERT_RESET   = 0x01
CMD_DEASSERT_RESET = 0x02
CMD_FLOAT_RESET    = 0x03
CMD_SEND_BITS      = 0x04
CMD_READ_BYTE      = 0x05
CMD_WAIT_PENDING   = 0x06
CMD_FLOAT_SCLK     = 0x07
CMD_LOW_SCLK       = 0x08

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

        total_bits_counter = Signal(range(max(MAX_SEND_BITS, 8)))
        # The 8 in the above max() expression is for the following optimization:
        # This is an optimization to overlay the read_address register with total_bits_counter.
        # total_bits_counter is only used for sending bit vectors (i.e. writes)
        # read_address is only ever used when performing reads. So these are never ever used
        # at the same time, so putting them in the same flipflops saves some logic cells
        read_address = total_bits_counter[:8]        #read_address = Signal(8)

        m.submodules.sclk = sclk_buffer = io.FFBuffer("io", self._ports.sclk)
        sclk_o, sclk_o_nxt = Signal(), Signal()
        sclk_oe, sclk_oe_nxt = Signal(), Signal()
        m.d.sync += (sclk_o.eq(sclk_o_nxt),
                     sclk_oe.eq(sclk_oe_nxt))
        m.d.comb += (sclk_o_nxt.eq(sclk_o),
                     sclk_oe_nxt.eq(sclk_oe))
        m.d.comb += sclk_buffer.oe.eq(sclk_oe_nxt)
        m.d.comb += sclk_buffer.o.eq(sclk_o_nxt)

        m.submodules.sdata = sdata_buffer = io.FFBuffer("io", self._ports.sdata)

        sdata_sync, sdata_sync_ff, sdata_negedge, sdata_negedge_seen = Signal(), Signal(), Signal(), Signal()
        m.submodules += cdc.FFSynchronizer(sdata_buffer.i, sdata_sync)
        m.d.sync += sdata_sync_ff.eq(sdata_sync)
        m.d.comb += sdata_negedge.eq((sdata_sync == 0) & (sdata_sync_ff == 1))
        m.d.sync += sdata_negedge_seen.eq(sdata_negedge_seen | sdata_negedge)
        sdata_o, sdata_o_nxt = Signal(), Signal()
        sdata_oe, sdata_oe_nxt = Signal(), Signal()
        m.d.sync += (sdata_o.eq(sdata_o_nxt),
                     sdata_oe.eq(sdata_oe_nxt))
        m.d.comb += (sdata_o_nxt.eq(sdata_o),
                     sdata_oe_nxt.eq(sdata_oe))
        m.d.comb += (sdata_buffer.o.eq(sdata_o_nxt),
                     sdata_buffer.oe.eq(sdata_oe_nxt))
        xres_i_sync = Signal()
        xres_o, xres_o_nxt = Signal(), Signal()
        xres_oe, xres_oe_nxt = Signal(), Signal()
        m.d.sync += (xres_o.eq(xres_o_nxt),
                     xres_oe.eq(xres_oe_nxt))
        m.d.comb += (xres_o_nxt.eq(xres_o),
                     xres_oe_nxt.eq(xres_oe))
        if self._ports.xres is not None:
            m.submodules.xres = xres_buffer = io.FFBuffer("io", self._ports.xres)
            m.d.comb += xres_buffer.oe.eq(xres_oe_nxt)
            m.d.comb += xres_buffer.o.eq(xres_o_nxt)
            m.submodules += cdc.FFSynchronizer(xres_buffer.i, xres_i_sync)
        else:
            xres_i_sync = Const(0)

        # Use a single timer for various waits
        timer = Signal(range(self._timer_max_cyc))
        timer_running = Signal()
        timer_mode_clock = Signal()
        timer_done_oneshot = Signal()
        timer_done = Signal()
        m.d.comb += timer_done.eq(timer_done_oneshot | ~timer_running)

        with m.If(timer_running):
            with m.If(timer == 0):
                with m.If(sclk_o & timer_mode_clock):
                    m.d.sync += timer.eq(self._clock_low_cyc - 1)
                    m.d.comb += sclk_o_nxt.eq(0)
                with m.Else():
                    m.d.sync += timer_running.eq(0)
                    m.d.comb += timer_done_oneshot.eq(1)
            with m.Else():
                m.d.sync += timer.eq(timer - 1)

        def start_clock_cycle():
            m.d.sync += timer.eq(self._clock_high_cyc - 1)
            m.d.sync += timer_running.eq(1)
            m.d.sync += timer_mode_clock.eq(1)
            m.d.comb += sclk_o_nxt.eq(1)

        def start_simple_timer(cycles):
            assert cycles >= 1
            assert cycles - 1 < self._timer_max_cyc
            m.d.sync += timer.eq(cycles - 1)
            m.d.sync += timer_running.eq(1)
            m.d.sync += timer_mode_clock.eq(0)

        cmd = Signal(4)
        do_poll = Signal()
        reg_not_mem = do_poll # same bit of the command byte as do_poll,
                              # but do_poll applies during CMD_SEND_BITS
                              # while reg_not_mem applies during CMD_READ_BYTE
        needs_single_clock_pulse_for_poll = Signal()
        needs_arbitrary_clocks_for_poll = Signal()
        byte = Signal(8)
        bit_in_byte_counter = Signal(3)

        do_sample_data = Signal()
        do_sample_data_delayed = do_sample_data
        for i in range(self._sample_data_delayed):
            do_sample_data_delayed_new = Signal(name=f"do_sample_data_delayed_{i}")
            m.d.sync += do_sample_data_delayed_new.eq(do_sample_data_delayed)
            do_sample_data_delayed = do_sample_data_delayed_new
        with m.If(do_sample_data_delayed):
            m.d.sync += byte.eq((byte << 1) | sdata_sync)

        with m.FSM():
            with m.State("IDLE"):
                with m.If(self._out_fifo.r_rdy):
                    m.d.comb += self._out_fifo.r_en.eq(1)
                    m.d.sync += (
                        cmd.eq(self._out_fifo.r_data),
                        do_poll.eq(self._out_fifo.r_data[7]),
                        needs_single_clock_pulse_for_poll.eq(self._out_fifo.r_data[6]),
                        needs_arbitrary_clocks_for_poll.eq(self._out_fifo.r_data[5]))
                    m.next = "COMMAND"
            with m.State("COMMAND"):
                with m.If(cmd == CMD_ASSERT_RESET):
                    m.d.comb += xres_o_nxt.eq(1)
                    m.d.comb += xres_oe_nxt.eq(1)
                    m.next = "IDLE"
                with m.Elif(cmd == CMD_DEASSERT_RESET):
                    m.d.comb += xres_o_nxt.eq(0)
                    m.d.comb += xres_oe_nxt.eq(1)
                    m.next = "IDLE"
                with m.Elif(cmd == CMD_FLOAT_RESET):
                    m.d.comb += xres_o_nxt.eq(0)
                    m.d.comb += xres_oe_nxt.eq(0)
                    m.next = "IDLE"
                with m.Elif((cmd & 0x7f) == CMD_SEND_BITS):
                    with m.If(self._out_fifo.r_rdy):
                        m.d.comb += self._out_fifo.r_en.eq(1)
                        m.d.sync += total_bits_counter[8:].eq(self._out_fifo.r_data)
                        m.next = "SEND_BITS_WAIT_CNT_LSB"
                with m.Elif(cmd == CMD_READ_BYTE):
                    with m.If(self._out_fifo.r_rdy):
                        m.d.comb += self._out_fifo.r_en.eq(1)
                        m.d.sync += read_address.eq(self._out_fifo.r_data)
                        m.d.comb += sdata_o_nxt.eq(1)
                        m.d.comb += sdata_oe_nxt.eq(1)
                        start_clock_cycle()
                        m.next = "READ_BYTE_SEND_CMD_BIT_0"
                with m.Elif(cmd == CMD_WAIT_PENDING):
                    with m.If(self._in_fifo.w_rdy):
                        m.d.comb += self._in_fifo.w_data.eq(0)
                        m.d.comb += self._in_fifo.w_en.eq(1)
                        m.next = "IDLE"
                with m.Elif(cmd == CMD_FLOAT_SCLK):
                    m.d.comb += sclk_o_nxt.eq(0)
                    m.d.comb += sclk_oe_nxt.eq(0)
                    m.next = "IDLE"
                with m.Elif(cmd == CMD_LOW_SCLK):
                    m.d.comb += sclk_o_nxt.eq(0)
                    m.d.comb += sclk_oe_nxt.eq(1)
                    m.next = "IDLE"
                with m.Else():
                    m.next = "IDLE"
            with m.State("SEND_BITS_WAIT_CNT_LSB"):
                with m.If(self._out_fifo.r_rdy):
                    m.d.sync += total_bits_counter[:8].eq(self._out_fifo.r_data)

                    if self._ports.xres is not None:
                        m.d.comb += self._out_fifo.r_en.eq(1)
                        m.d.comb += xres_o_nxt.eq(0)
                        m.d.comb += xres_oe_nxt.eq(1)

                        with m.If(((xres_oe == 1) & (xres_o == 1)) |
                                  ((xres_oe == 0) & (xres_i_sync == 1))):
                            start_simple_timer(self._after_reset_wait_cyc - 1)
                            # ^^ - 1 to account for the additional cycle to remove the first data byte from the FIFO
                            m.next = "SEND_BITS_WAIT_AFTER_RESET"
                        with m.Else():
                            m.next = "SEND_BITS_WAIT_DATA"
                    else:
                        # LIMITED support for power-cycle mode:
                        with m.If(sdata_sync):
                            start_simple_timer(self._after_reset_wait_cyc - 1)
                        with m.Else():
                            with m.If(timer_done):
                                m.d.comb += self._out_fifo.r_en.eq(1)
                                m.next = "SEND_BITS_WAIT_DATA"
            with m.State("SEND_BITS_WAIT_AFTER_RESET"):
                with m.If(timer_done_oneshot):
                    m.next = "SEND_BITS_WAIT_DATA"
            with m.State("SEND_BITS_WAIT_DATA"):
                with m.If(self._out_fifo.r_rdy):
                    m.d.comb += self._out_fifo.r_en.eq(1)
                    m.d.sync += bit_in_byte_counter.eq(7)
                    m.d.sync += byte.eq(self._out_fifo.r_data[:7])
                    m.d.comb += sdata_o_nxt.eq(self._out_fifo.r_data[7])
                    m.d.comb += sdata_oe_nxt.eq(1)
                    start_clock_cycle()
                    m.next = "SEND_BITS_SHIFT"
            with m.State("SEND_BITS_SHIFT"):
                with m.If(timer_done_oneshot):
                    m.d.sync += byte.eq(byte << 1)
                    m.d.comb += sdata_o_nxt.eq(byte[6])
                    m.d.sync += bit_in_byte_counter.eq(bit_in_byte_counter - 1)
                    m.d.sync += total_bits_counter.eq(total_bits_counter - 1)

                    with m.If(total_bits_counter == 0):
                        with m.If(do_poll):
                            m.d.comb += sdata_oe_nxt.eq(0)
                            m.next = "SEND_BITS_WAIT_IO_DECAY"
                            start_simple_timer(self._io_decay_plus_sample_wait_cyc)
                        with m.Else():
                            m.d.comb += sdata_oe_nxt.eq(0)
                            m.next = "IDLE"
                    with m.Elif(bit_in_byte_counter == 0):
                        with m.If(self._out_fifo.r_rdy):
                            m.d.comb += self._out_fifo.r_en.eq(1)
                            m.d.sync += byte.eq(self._out_fifo.r_data[:7])
                            m.d.comb += sdata_o_nxt.eq(self._out_fifo.r_data[7])
                            start_clock_cycle()
                        with m.Else():
                            m.next = "SEND_BITS_WAIT_DATA"
                    with m.Else():
                        start_clock_cycle()
            with m.State("SEND_BITS_WAIT_IO_DECAY"):
                with m.If(timer_done_oneshot):
                    with m.If(needs_single_clock_pulse_for_poll):
                        start_clock_cycle()
                    m.d.sync += sdata_negedge_seen.eq(0)
                    m.next = "SEND_BITS_WAIT_POLL"
            with m.State("SEND_BITS_WAIT_POLL"):
                # Some versions of the ISSP spec say that the chip can be in this
                # state with SDATA high for 100ms, other versions say 200ms, For
                # now we don't implement a time-out.
                with m.If(sdata_negedge_seen & ~sdata_sync & ~timer_running):
                    m.next = "IDLE"
                with m.Elif(needs_arbitrary_clocks_for_poll & ~sdata_negedge_seen & ~sdata_sync & timer_done):
                    start_clock_cycle()
            with m.State("SEND_BITS_ZERO_AFTER_POLL"):
                with m.If(timer_done_oneshot):
                    m.d.sync += total_bits_counter.eq(total_bits_counter - 1)
                    with m.If(total_bits_counter == 0):
                        m.d.comb += sdata_oe_nxt.eq(0)
                        m.next = "IDLE"
                    with m.Else():
                        start_clock_cycle()
            with m.State("READ_BYTE_SEND_CMD_BIT_0"):
                with m.If(timer_done_oneshot):
                    m.d.comb += sdata_o_nxt.eq(reg_not_mem)
                    start_clock_cycle()
                    m.next = "READ_BYTE_SEND_CMD_BIT_1"
            with m.State("READ_BYTE_SEND_CMD_BIT_1"):
                with m.If(timer_done_oneshot):
                    m.d.comb += sdata_o_nxt.eq(1)
                    start_clock_cycle()
                    m.next = "READ_BYTE_SEND_CMD_BIT_2"
            with m.State("READ_BYTE_SEND_CMD_BIT_2"):
                with m.If(timer_done_oneshot):
                    m.d.comb += sdata_o_nxt.eq(read_address[7])
                    m.d.sync += bit_in_byte_counter.eq(7)
                    m.d.sync += byte.eq(read_address[:7])
                    start_clock_cycle()
                    m.next = "READ_BYTE_SHIFT_ADDRESS"
            with m.State("READ_BYTE_SHIFT_ADDRESS"):
                with m.If(timer_done_oneshot):
                    m.d.comb += sdata_o_nxt.eq(byte[6])
                    m.d.sync += byte.eq(byte << 1)
                    m.d.sync += bit_in_byte_counter.eq(bit_in_byte_counter - 1)
                    start_clock_cycle()
                    with m.If(bit_in_byte_counter == 0):
                        m.d.comb += sdata_oe_nxt.eq(0)
                        m.next = "READ_BYTE_WAIT_TURNAROUND_1"
            with m.State("READ_BYTE_WAIT_TURNAROUND_1"):
                with m.If(timer_done_oneshot):
                    start_clock_cycle()
                    m.d.sync += bit_in_byte_counter.eq(7)
                    m.next = "READ_BYTE_SHIFT"
            with m.State("READ_BYTE_SHIFT"):
                with m.If((timer == 0) & (sclk_o) & (bit_in_byte_counter != 7)):
                    m.d.comb += do_sample_data.eq(1)
                with m.If(timer_done_oneshot):
                    start_clock_cycle()
                    m.d.sync += bit_in_byte_counter.eq(bit_in_byte_counter - 1)
                    with m.If(bit_in_byte_counter == 0):
                        start_clock_cycle()
                        m.next = "READ_BYTE_WAIT_TURNAROUND_2"
            with m.State("READ_BYTE_WAIT_TURNAROUND_2"):
                with m.If((timer == 0) & (sclk_o)):
                    m.d.comb += do_sample_data.eq(1)
                with m.If(timer_done_oneshot):
                    m.d.comb += sdata_o_nxt.eq(1)
                    m.d.comb += sdata_oe_nxt.eq(1)
                    # Note: comparing to the ISSP specification it might seem that
                    # we are missing a high-z clock cycle here, however this is
                    # documented incorrectly: final bus turnaround happens between
                    # falling-edge and rising-edge, there's only half a cycle for bus
                    # turnaround, rather then the full 1.5 cycles shown on the example
                    # waveform.
                    start_clock_cycle()
                    m.next = "READ_BYTE_WAIT_TURNAROUND_3"
            with m.State("READ_BYTE_WAIT_TURNAROUND_3"):
                with m.If(timer_done & self._in_fifo.w_rdy):
                    m.d.comb += self._in_fifo.w_data.eq(byte)
                    m.d.comb += self._in_fifo.w_en.eq(1)

                    m.d.comb += sdata_oe_nxt.eq(0)
                    m.next = "IDLE"

        return m

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
        await self.lower.write([CMD_WAIT_PENDING])
        await self.lower.flush()
        assert 0 == (await self.lower.read(1))[0]

    async def assert_xres(self):
        """
        Assert xres (set to 1)
        """
        await self.lower.write([CMD_ASSERT_RESET])
        await self.wait_pending()

    async def deassert_xres(self):
        """
        Deassert xres (set to 0)
        """
        await self.lower.write([CMD_DEASSERT_RESET])
        await self.wait_pending()

    async def float_xres(self):
        """
        Float xres if it was previously driven
        """
        await self.lower.write([CMD_FLOAT_RESET])
        await self.wait_pending()

    async def float_sclk(self):
        """
        Float sclk if it was previously driven
        """
        await self.lower.write([CMD_FLOAT_SCLK])

    async def low_sclk(self):
        """
        Drive sclk with a strong low value
        """
        await self.lower.write([CMD_LOW_SCLK])

    async def _send_zero_bits(self, cnt_bits = ZERO_BITS_AFTER_POLL):
        cnt_enc = cnt_bits - 1
        cnt_bytes = (cnt_bits + 7)//8
        zero_blist = [0] * cnt_bytes
        await self.lower.write([
            CMD_SEND_BITS, cnt_enc >> 8, cnt_enc & 0xff, *zero_blist])

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
            (CMD_SEND_BITS |
             (do_poll << 7) |
             (needs_single_clock_pulse_for_poll << 6) |
             (needs_arbitrary_clocks_for_poll << 5)
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
            (CMD_SEND_BITS |
             (do_poll << 7) |
             (needs_single_clock_pulse_for_poll << 6) |
             (needs_arbitrary_clocks_for_poll << 5)
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
            send_bytes.append(CMD_READ_BYTE | (reg_not_mem << 7))
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

