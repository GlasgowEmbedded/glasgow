# Ref: https://www.skyworksinc.com/-/media/Skyworks/SL/documents/public/data-sheets/Si5351-B.pdf
# Accession: G00102

# Ref: https://www.skyworksinc.com/-/media/Skyworks/SL/documents/public/application-notes/AN619.pdf
# Document Number: AN619
# Accession: G00103

import asyncio
import enum
import logging
import math
import struct
import time

from amaranth import *
from amaranth.lib import wiring, stream
from amaranth.lib.wiring import In, Out

from glasgow.gateware.i2c import I2CInitiator
from glasgow.gateware.ports import PortGroup
from glasgow.abstract import AbstractAssembly, GlasgowPin
from glasgow.applet.interface.i2c_controller import I2CNotAcknowledged, I2CControllerInterface
from glasgow.applet import GlasgowAppletError, GlasgowAppletTool, GlasgowAppletV2


__all__ = ["Si5351AError", "Si5351AInterface", "I2CNotAcknowledged"]


# ---------------------------------------------------------------------------
# I2C Sequencer gateware
# ---------------------------------------------------------------------------
#
# I2CSequencerComponent is a self-contained hardware-timed I2C write sequencer.
# It shares an I2CInitiator with the normal command/response path via a mode mux.
#
# The combined Si5351AControllerComponent exposes:
#   - cmd_i_stream / cmd_o_stream : same protocol as I2CControllerComponent
#                                   (used by I2CControllerInterface for set-freq, etc.)
#   - seq_i_stream / seq_o_stream : sequencer pipe (used for sweep-hw)
#   - divisor                     : shared SCL clock divisor
#
# Sequencer packet format (seq_i_stream, host -> device):
#   [0..1]  count[15:0]        big-endian number of transactions that follow
#   per transaction:
#     [0..3]  delay[31:0]      big-endian delay in SCL quarter-period ticks before START
#                              (1 tick ≈ 625 ns @ 400 kHz; 32-bit → max ~2684 s)
#                              WSPR symbol: 683 ms ≈ 1,093,000 ticks
#                              FT8 symbol:  160 ms ≈   256,000 ticks
#     [4]     i2c_addr_w       (i2c_addr << 1) | 0
#     [5]     data_len         number of data bytes (1..16)
#     [6..]   data[data_len]
#
# Response (seq_o_stream, device -> host):
#   0x01 byte on completion of all transactions.
#
# While the sequencer is running, the command path is blocked (mode=SEQ).
# When the sequencer finishes, mode returns to CMD automatically.

from glasgow.applet.interface.i2c_controller import _Command as _I2CCommand  # noqa: E402


class Si5351AControllerComponent(wiring.Component):
    """Combined I2C controller + hardware sequencer for Si5351A.

    Instantiates a single I2CInitiator and time-multiplexes it between a
    standard command/response pipe (for interactive control) and a
    sequencer pipe (for hardware-timed sweeps).
    """

    # Normal command/response pipe (same protocol as I2CControllerComponent)
    cmd_i_stream: In(stream.Signature(8))
    cmd_o_stream: Out(stream.Signature(8))

    # Sequencer pipe
    seq_i_stream: In(stream.Signature(8))
    seq_o_stream: Out(stream.Signature(8))

    divisor: In(16)

    def __init__(self, ports):
        self._ports = ports
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.ctrl = ctrl = I2CInitiator(self._ports, 0)
        m.d.comb += ctrl.divisor.eq(self.divisor)

        # seq_active: 1 while the sequencer FSM owns the I2C initiator
        seq_active = Signal()

        # Separate ctrl signal sets for each FSM, muxed into the initiator
        cmd_start  = Signal(); cmd_stop  = Signal()
        cmd_write  = Signal(); cmd_read  = Signal()
        cmd_data_i = Signal(8); cmd_ack_i = Signal()

        seq_start  = Signal(); seq_stop  = Signal()
        seq_write  = Signal()
        seq_data_i = Signal(8)

        # Mux: sequencer wins when seq_active
        with m.If(seq_active):
            m.d.comb += [
                ctrl.start.eq(seq_start),
                ctrl.stop.eq(seq_stop),
                ctrl.write.eq(seq_write),
                ctrl.data_i.eq(seq_data_i),
            ]
        with m.Else():
            m.d.comb += [
                ctrl.start.eq(cmd_start),
                ctrl.stop.eq(cmd_stop),
                ctrl.write.eq(cmd_write),
                ctrl.read.eq(cmd_read),
                ctrl.data_i.eq(cmd_data_i),
                ctrl.ack_i.eq(cmd_ack_i),
            ]

        # --- Command FSM (I2CControllerComponent protocol) ---
        cmd   = Signal(_I2CCommand)
        count = Signal(16)

        with m.FSM(name="cmd_fsm"):
            with m.State("IDLE"):
                m.d.sync += cmd.eq(self.cmd_i_stream.payload)
                with m.If(self.cmd_i_stream.valid & ~ctrl.busy & ~seq_active):
                    m.d.comb += self.cmd_i_stream.ready.eq(1)
                    m.next = "COMMAND"

            with m.State("COMMAND"):
                with m.Switch(cmd):
                    with m.Case(_I2CCommand.Start):
                        m.d.comb += cmd_start.eq(1)
                        m.next = "SYNC"
                    with m.Case(_I2CCommand.Stop):
                        m.d.comb += cmd_stop.eq(1)
                        m.next = "SYNC"
                    with m.Case(_I2CCommand.Write, _I2CCommand.Read):
                        m.next = "COUNT"

            with m.State("SYNC"):
                with m.If(~ctrl.busy):
                    m.d.comb += self.cmd_o_stream.valid.eq(1)
                    with m.If(self.cmd_o_stream.ready):
                        m.next = "IDLE"

            with m.State("COUNT"):
                word = Signal(range(2))
                m.d.comb += self.cmd_i_stream.ready.eq(1)
                with m.If(self.cmd_i_stream.valid):
                    m.d.sync += count.word_select(word, 8).eq(self.cmd_i_stream.payload)
                    m.d.sync += word.eq(word + 1)
                    with m.If(word == 1):
                        with m.Switch(cmd):
                            with m.Case(_I2CCommand.Write):
                                m.next = "WRITE-FIRST"
                            with m.Case(_I2CCommand.Read):
                                m.next = "READ-FIRST"

            with m.State("WRITE-FIRST"):
                with m.If(self.cmd_i_stream.valid):
                    m.d.comb += self.cmd_i_stream.ready.eq(1)
                    m.d.comb += cmd_data_i.eq(self.cmd_i_stream.payload)
                    m.d.comb += cmd_write.eq(1)
                    m.next = "WRITE-ACK"

            with m.State("WRITE-ACK"):
                with m.If(~ctrl.busy):
                    with m.If(ctrl.ack_o):
                        m.d.sync += count.eq(count - 1)
                    m.next = "WRITE"

            with m.State("WRITE"):
                with m.If((count == 0) | ~ctrl.ack_o):
                    m.next = "REPORT"
                with m.Elif(self.cmd_i_stream.valid):
                    m.d.comb += self.cmd_i_stream.ready.eq(1)
                    m.d.comb += cmd_data_i.eq(self.cmd_i_stream.payload)
                    m.d.comb += cmd_write.eq(1)
                    m.next = "WRITE-ACK"

            with m.State("REPORT"):
                word = Signal(range(2))
                m.d.comb += self.cmd_o_stream.valid.eq(1)
                with m.If(self.cmd_o_stream.ready):
                    m.d.comb += self.cmd_o_stream.payload.eq(count.word_select(word, 8))
                    m.d.sync += word.eq(word + 1)
                    with m.If(word == 1):
                        m.d.sync += count.eq(0)
                        m.next = "IDLE"

            with m.State("READ-FIRST"):
                m.d.comb += cmd_ack_i.eq(count != 1)
                m.d.comb += cmd_read.eq(1)
                m.d.sync += count.eq(count - 1)
                m.next = "READ"

            with m.State("READ"):
                with m.If(~ctrl.busy):
                    m.d.comb += self.cmd_o_stream.valid.eq(1)
                    m.d.comb += self.cmd_o_stream.payload.eq(ctrl.data_o)
                    with m.If(self.cmd_o_stream.ready):
                        with m.If(count == 0):
                            m.next = "IDLE"
                        with m.Else():
                            m.d.comb += cmd_ack_i.eq(count != 1)
                            m.d.comb += cmd_read.eq(1)
                            m.d.sync += count.eq(count - 1)

        # --- Freerunning 64-bit tick counter (increments every sync cycle = 1/48 MHz) ---
        # Split into two 32-bit halves to avoid a 64-bit carry chain that would violate
        # timing at 30+ MHz.  The carry from the low half is registered one cycle, so
        # the high half lags by exactly one cycle on rollover (~89 s at 48 MHz) — negligible.
        tick_lo    = Signal(32)
        tick_hi    = Signal(32)
        tick_carry = Signal()
        m.d.sync  += tick_lo.eq(tick_lo + 1)
        m.d.sync  += tick_carry.eq(tick_lo == 0xFFFFFFFF)
        m.d.sync  += tick_hi.eq(tick_hi + tick_carry)
        tick_ctr   = Cat(tick_lo, tick_hi)   # read-only concatenation for snapshot

        # --- Sequencer FSM ---
        txn_count  = Signal(16)
        delay_rem  = Signal(32)
        delay_tick = Signal(16)
        data_len   = Signal(8)
        s_addr     = Signal(8)   # latched I2C address+W byte
        s_data     = Signal(8)   # latched data byte

        # Snapshot buffer for sending 64-bit counter values byte-by-byte.
        # snap_buf is shifted left 8 bits after each byte sent; MSB goes first.
        snap_buf   = Signal(64)
        snap_bytes = Signal(range(8))   # remaining bytes to send (0 means just sent last)
        snap_next  = Signal()    # which state to go to after sending snapshot

        with m.FSM(name="seq_fsm"):
            with m.State("IDLE"):
                # Wait for the host to send the first byte (count-hi)
                m.d.sync += seq_active.eq(0)
                with m.If(self.seq_i_stream.valid):
                    m.d.sync += txn_count[8:].eq(self.seq_i_stream.payload)
                    m.d.comb += self.seq_i_stream.ready.eq(1)
                    m.next = "COUNT-LO"

            with m.State("COUNT-LO"):
                with m.If(self.seq_i_stream.valid):
                    m.d.sync += txn_count[:8].eq(self.seq_i_stream.payload)
                    m.d.comb += self.seq_i_stream.ready.eq(1)
                    m.next = "CHECK-DONE"

            with m.State("CHECK-DONE"):
                with m.If(txn_count == 0):
                    m.next = "DONE"
                with m.Else():
                    m.d.sync += seq_active.eq(1)
                    # Latch start snapshot and send 0x02 ack before first transaction
                    m.d.sync += snap_buf.eq(tick_ctr)
                    m.d.sync += snap_bytes.eq(7)
                    m.d.sync += snap_next.eq(0)  # 0 = go to DELAY-B3 after snap
                    m.next = "SNAP-ACK"

            # Send an ack byte (0x02 for start, 0x01 for done) followed by 8 bytes
            # of snap_buf (big-endian).  snap_next selects the continuation state.
            with m.State("SNAP-ACK"):
                ack_byte = Mux(snap_next, 0x01, 0x02)
                m.d.comb += self.seq_o_stream.valid.eq(1)
                m.d.comb += self.seq_o_stream.payload.eq(ack_byte)
                with m.If(self.seq_o_stream.ready):
                    m.next = "SNAP-SEND"

            with m.State("SNAP-SEND"):
                # Always send the MSB (bits [63:56]); shift left after each accepted byte.
                m.d.comb += self.seq_o_stream.valid.eq(1)
                m.d.comb += self.seq_o_stream.payload.eq(snap_buf[56:64])
                with m.If(self.seq_o_stream.ready):
                    m.d.sync += snap_buf.eq(snap_buf << 8)
                    with m.If(snap_bytes == 0):
                        with m.If(snap_next):
                            m.next = "IDLE"
                        with m.Else():
                            m.next = "DELAY-B3"
                    with m.Else():
                        m.d.sync += snap_bytes.eq(snap_bytes - 1)

            with m.State("DELAY-B3"):
                with m.If(self.seq_i_stream.valid):
                    m.d.sync += delay_rem[24:].eq(self.seq_i_stream.payload)
                    m.d.comb += self.seq_i_stream.ready.eq(1)
                    m.next = "DELAY-B2"

            with m.State("DELAY-B2"):
                with m.If(self.seq_i_stream.valid):
                    m.d.sync += delay_rem[16:24].eq(self.seq_i_stream.payload)
                    m.d.comb += self.seq_i_stream.ready.eq(1)
                    m.next = "DELAY-B1"

            with m.State("DELAY-B1"):
                with m.If(self.seq_i_stream.valid):
                    m.d.sync += delay_rem[8:16].eq(self.seq_i_stream.payload)
                    m.d.comb += self.seq_i_stream.ready.eq(1)
                    m.next = "DELAY-B0"

            with m.State("DELAY-B0"):
                with m.If(self.seq_i_stream.valid):
                    m.d.sync += delay_rem[:8].eq(self.seq_i_stream.payload)
                    m.d.sync += delay_tick.eq(self.divisor)
                    m.d.comb += self.seq_i_stream.ready.eq(1)
                    m.next = "DELAY-WAIT"

            with m.State("DELAY-WAIT"):
                with m.If(delay_rem == 0):
                    m.next = "S-ADDR"
                with m.Else():
                    with m.If(delay_tick == 0):
                        m.d.sync += delay_rem.eq(delay_rem - 1)
                        m.d.sync += delay_tick.eq(self.divisor)
                    with m.Else():
                        m.d.sync += delay_tick.eq(delay_tick - 1)

            with m.State("S-ADDR"):
                with m.If(self.seq_i_stream.valid):
                    m.d.sync += s_addr.eq(self.seq_i_stream.payload)
                    m.d.comb += self.seq_i_stream.ready.eq(1)
                    m.next = "S-START"

            with m.State("S-START"):
                with m.If(~ctrl.busy):
                    m.d.comb += seq_start.eq(1)
                    m.next = "S-ADDR-WRITE"

            with m.State("S-ADDR-WRITE"):
                with m.If(~ctrl.busy):
                    m.d.comb += seq_data_i.eq(s_addr)
                    m.d.comb += seq_write.eq(1)
                    m.next = "S-ADDR-ACK"

            with m.State("S-ADDR-ACK"):
                with m.If(~ctrl.busy):
                    m.next = "S-LEN"

            with m.State("S-LEN"):
                with m.If(self.seq_i_stream.valid):
                    m.d.sync += data_len.eq(self.seq_i_stream.payload)
                    m.d.comb += self.seq_i_stream.ready.eq(1)
                    m.next = "S-DATA"

            with m.State("S-DATA"):
                with m.If(data_len == 0):
                    m.next = "S-STOP"
                with m.Elif(~ctrl.busy & self.seq_i_stream.valid):
                    m.d.sync += s_data.eq(self.seq_i_stream.payload)
                    m.d.comb += self.seq_i_stream.ready.eq(1)
                    m.next = "S-DATA-WRITE"

            with m.State("S-DATA-WRITE"):
                m.d.comb += seq_data_i.eq(s_data)
                m.d.comb += seq_write.eq(1)
                m.next = "S-DATA-ACK"

            with m.State("S-DATA-ACK"):
                with m.If(~ctrl.busy):
                    m.d.sync += data_len.eq(data_len - 1)
                    m.next = "S-DATA"

            with m.State("S-STOP"):
                with m.If(~ctrl.busy):
                    m.d.comb += seq_stop.eq(1)
                    m.next = "S-STOP-WAIT"

            with m.State("S-STOP-WAIT"):
                with m.If(~ctrl.busy):
                    m.d.sync += txn_count.eq(txn_count - 1)
                    with m.If(txn_count == 1):
                        m.next = "DONE"
                    with m.Else():
                        m.next = "DELAY-B3"

            with m.State("DONE"):
                m.d.sync += seq_active.eq(0)
                m.d.sync += snap_buf.eq(tick_ctr)
                m.d.sync += snap_bytes.eq(7)
                m.d.sync += snap_next.eq(1)  # 1 = go to IDLE after snap
                m.next = "SNAP-ACK"

        return m


class _CmdPipeI2CInterface(I2CControllerInterface):
    """Thin wrapper that makes a raw cmd pipe behave like I2CControllerInterface.

    Bypasses the I2CControllerInterface constructor (which would create a new
    port group and submodule) and instead uses an already-created pipe.
    """

    def __new__(cls, logger, ctrl_iface):
        # Bypass __init__ chain; manually populate the required attributes
        obj = object.__new__(cls)
        obj._logger = logger
        obj._level  = logging.DEBUG if logger.name == __name__ else logging.TRACE
        obj._pipe   = ctrl_iface.cmd_pipe
        obj._multi  = False
        obj._busy   = False
        return obj

    def __init__(self, logger, ctrl_iface):
        pass  # all setup done in __new__


class Si5351AControllerInterface:
    """Combined host interface: normal I2C command/response + hardware sequencer.

    Wires the Si5351AControllerComponent to two pipes and exposes:
    - ``i2c``:  an I2CControllerInterface-compatible object (command/response)
    - ``seq``:  an I2CSequencerInterface object (hardware sweep)
    - ``clock``: shared SCL clock divisor
    """

    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly,
                 *, scl: GlasgowPin, sda: GlasgowPin):
        from glasgow.abstract import PullState  # local import to avoid circular
        assembly.use_pulls({scl: "high", sda: "high"})
        ports = assembly.add_port_group(scl=scl, sda=sda)
        component = assembly.add_submodule(Si5351AControllerComponent(ports))

        # Command/response pipe (reuse I2CControllerInterface internals via same wire protocol)
        self._cmd_pipe = assembly.add_inout_pipe(
            component.cmd_o_stream, component.cmd_i_stream)
        # Sequencer pipe
        self._seq_pipe = assembly.add_inout_pipe(
            component.seq_o_stream, component.seq_i_stream)
        # Shared clock divisor
        self.clock = assembly.add_clock_divisor(
            component.divisor, ref_period=assembly.sys_clk_period * 4, name="scl")
        self.sys_clk_freq = 1.0 / assembly.sys_clk_period

    @property
    def cmd_pipe(self):
        return self._cmd_pipe

    @property
    def seq_pipe(self):
        return self._seq_pipe


class I2CSequencerInterface:
    """Host interface for the hardware I2C sequencer pipe.

    Encodes pre-computed sweep steps as packed sequencer records and streams
    them to the FPGA for hardware-timed execution.
    """

    _MAX_DATA = 16  # max bytes per transaction (register addr + 8 data)

    def __init__(self, logger: logging.Logger, pipe, i2c_address: int = 0x60,
                 sys_clk_freq: float = 48e6):
        self._logger      = logger
        self._level       = logging.DEBUG if logger.name == __name__ else logging.TRACE
        self._pipe        = pipe
        self._i2c_address = i2c_address
        self._sys_clk_freq = sys_clk_freq

    def _log(self, message, *args):
        self._logger.log(self._level, "I2CSeq: " + message, *args)

    def _encode_transaction(self, delay_ticks: int, reg_addr: int, data: bytes) -> bytes:
        addr_byte = (self._i2c_address << 1) & 0xFE
        payload   = bytes([reg_addr]) + bytes(data)
        assert 1 <= len(payload) <= self._MAX_DATA
        return struct.pack(">IBB", min(delay_ticks, 0xFFFFFFFF), addr_byte, len(payload)) + payload

    async def run_sequence(self, transactions: list[tuple[int, int, bytes]]) -> tuple[float, float]:
        """Stream transactions to hardware sequencer and await completion.

        Parameters
        ----------
        transactions
            List of ``(delay_ticks, reg_addr, data)`` tuples.

        Returns
        -------
        (started_at_s, elapsed_hw_s)
            ``started_at_s`` is the wall-clock time (``time.monotonic()``) at which
            the "started" ack was received from the FPGA — i.e. the moment the first
            I²C transaction was about to begin.  ``elapsed_hw_s`` is the hardware-
            measured duration of the sequence in seconds, derived from the 64-bit
            freerunning counter snapshots sent by the FPGA.
        """
        if not transactions:
            return (time.monotonic(), 0.0)
        self._log("streaming %d transactions", len(transactions))
        await self._pipe.send(struct.pack(">H", len(transactions)))
        for delay_ticks, reg_addr, data in transactions:
            await self._pipe.send(self._encode_transaction(delay_ticks, reg_addr, data))

        # Flush in the background: the FPGA's FIFO may be smaller than the full
        # sequence payload, so flush() can block for seconds as the sequencer
        # slowly drains the buffer.  The IN and OUT pipes are independent — the
        # FPGA sends 0x02 as soon as it latches the 2-byte count, long before
        # flush() completes.  Running flush concurrently lets us timestamp the
        # true startup moment without waiting for backpressure to clear.
        flush_task = asyncio.create_task(self._pipe.flush())

        # "Started" ack: 0x02 + 8-byte big-endian counter snapshot.
        # Arrives ~1 USB round-trip after the count bytes reach the FPGA.
        started_hdr = await self._pipe.recv(1)
        if started_hdr[0] != 0x02:
            raise Si5351AError(f"sequencer start ack expected 0x02, got {started_hdr[0]:#04x}")
        start_snap = int.from_bytes(await self._pipe.recv(8), "big")
        started_at_s = time.monotonic()

        # Ensure all data has been handed off to the OS before waiting for done.
        await flush_task

        # "Done" ack: 0x01 + 8-byte big-endian counter snapshot
        done_hdr = await self._pipe.recv(1)
        if done_hdr[0] != 0x01:
            raise Si5351AError(f"sequencer done ack expected 0x01, got {done_hdr[0]:#04x}")
        done_snap = int.from_bytes(await self._pipe.recv(8), "big")

        elapsed_hw_s = (done_snap - start_snap) / self._sys_clk_freq
        self._log("sequence complete, hw elapsed %.3f s", elapsed_hw_s)
        return (started_at_s, elapsed_hw_s)


def encode_sweep(sweep_plan: list[dict], step_interval_ticks: int,
                 i2c_address: int, pll: "PLL",
                 clk: int) -> list[tuple[int, int, bytes]]:
    """Convert a sweep plan (from :func:`plan_sweep`) into sequencer transaction tuples.

    Each frequency step becomes either one transaction (PLL-only, click-free) or two
    transactions (PLL + output multisynth, click boundary), with a delay of
    ``step_interval_ticks`` ticks before the PLL write.

    Parameters
    ----------
    sweep_plan
        Output of :func:`plan_sweep`.
    step_interval_ticks
        Number of sequencer ticks between frequency steps.
    i2c_address
        I2C address of the Si5351A.
    pll
        PLL assignment for this clock output.
    clk
        Clock output index (0–2).

    Returns
    -------
    list of ``(delay_ticks, reg_addr, data)`` tuples.
    """
    pll_base = _REG_MSNA_PARAMS if pll == PLL.PLLA else _REG_MSNB_PARAMS
    ms_base  = _REG_MS0_PARAMS + (clk * 8)
    clk_ctrl_addr = _REG_CLK0_CONTROL + clk

    transactions = []
    prev_out_div = None
    prev_r_div   = None

    for i, step in enumerate(sweep_plan):
        divider_changed = (prev_out_div != step["out_div"] or
                           prev_r_div   != step["r_div"])

        delay = step_interval_ticks if i > 0 else 0

        if divider_changed or i == 0:
            # Full update: CLK control + output multisynth + PLL + reset
            # CLK control register (integer mode, PLL source, drive)
            drive_bits = DriveStrength.DRIVE_8MA & 0x03
            pll_bit    = 0x20 if pll == PLL.PLLB else 0x00
            clk_ctrl   = 0x40 | pll_bit | 0x0C | drive_bits  # MS_INT | CLK_SRC=MS

            # Pack as three back-to-back transactions with zero inter-delay
            # (1) CLK control register
            transactions.append((delay, clk_ctrl_addr, bytes([clk_ctrl])))
            # (2) Output multisynth (8 bytes)
            transactions.append((0, ms_base, step["ms_regs"]))
            # (3) PLL multisynth (8 bytes) + reset
            transactions.append((0, pll_base, step["pll_regs"]))
            # (4) PLL reset
            reset_mask = 0x20 if pll == PLL.PLLA else 0x80
            transactions.append((0, _REG_PLL_RESET, bytes([reset_mask])))
        else:
            # Click-free: PLL only
            transactions.append((delay, pll_base, step["pll_regs"]))

        prev_out_div = step["out_div"]
        prev_r_div   = step["r_div"]

    return transactions


def _parse_sequence_csv(fileobj) -> list[tuple[int, float]]:
    """Parse a ``(frequency_hz, duration_ms)`` CSV file.

    Lines beginning with ``#`` and blank lines are ignored.

    Parameters
    ----------
    fileobj
        Readable text file object (or ``sys.stdin``).

    Returns
    -------
    list of ``(freq_hz, duration_ms)`` tuples.

    Raises
    ------
    Si5351AError
        If any line cannot be parsed.
    """
    symbols = []
    for lineno, raw in enumerate(fileobj, 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(",")
        if len(parts) != 2:
            raise Si5351AError(
                f"sequence CSV line {lineno}: expected 'freq_hz,duration_ms', got {line!r}")
        try:
            freq_hz     = float(parts[0].strip())
            duration_ms = float(parts[1].strip())
        except ValueError as e:
            raise Si5351AError(f"sequence CSV line {lineno}: {e}") from e
        if freq_hz <= 0:
            raise Si5351AError(f"sequence CSV line {lineno}: frequency must be positive")
        if duration_ms <= 0:
            raise Si5351AError(f"sequence CSV line {lineno}: duration must be positive")
        symbols.append((freq_hz, duration_ms))
    if not symbols:
        raise Si5351AError("sequence CSV contains no symbols")
    return symbols


def encode_sequence(symbols: list[tuple[int, float]], xtal_freq: int,
                    clk: int, pll: "PLL", tick_period_s: float,
                    i2c_address: int, *,
                    enable_output: bool = False,
                    vco_max: int | None = None) -> list[tuple[int, int, bytes]]:
    """Convert a symbol list into hardware sequencer transaction tuples.

    Each symbol becomes one or four I²C transactions depending on whether
    the output divider changes (click boundary). The final entry is a
    hardware-timed output-disable transaction appended after the last
    symbol's duration, so the output goes dark at FPGA precision.

    Parameters
    ----------
    symbols
        List of ``(freq_hz, duration_ms)`` pairs from :func:`_parse_sequence_csv`.
    xtal_freq
        Reference oscillator frequency in Hz.
    clk
        Clock output index (0–2).
    pll
        PLL assignment.
    tick_period_s
        Duration of one sequencer delay tick in seconds (= 1 / (4 * scl_freq)).
    i2c_address
        I²C address of the Si5351A.

    Returns
    -------
    list of ``(delay_ticks, reg_addr, data)`` tuples, with a final
    output-disable transaction appended.
    """
    if vco_max is None:
        vco_max = _VCO_MAX
    pll_base      = _REG_MSNA_PARAMS if pll == PLL.PLLA else _REG_MSNB_PARAMS
    ms_base       = _REG_MS0_PARAMS + (clk * 8)
    clk_ctrl_addr = _REG_CLK0_CONTROL + clk

    drive_bits = DriveStrength.DRIVE_8MA & 0x03
    pll_bit    = 0x20 if pll == PLL.PLLB else 0x00
    clk_ctrl   = 0x40 | pll_bit | 0x0C | drive_bits

    # Cache plan_frequency() results — digital modes reuse a small set of tones
    plan_cache: dict[int, dict] = {}

    def plan(freq_hz: int) -> dict:
        if freq_hz not in plan_cache:
            plan_cache[freq_hz] = plan_frequency(freq_hz, xtal_freq, vco_max=vco_max)
        return plan_cache[freq_hz]

    transactions = []
    prev_out_div = None
    prev_r_div   = None

    # Prepend setup transactions so the entire sequence is self-contained and
    # no command-pipe round-trips are needed before run_sequence().
    # REG_OUTPUT_ENABLE is active-low: after power-on all bits are 1 (all off).
    # Clear only our clock's bit to enable it; leave others undisturbed.
    if enable_output:
        transactions.append((0, _REG_OUTPUT_ENABLE, bytes([0xFF & ~(1 << clk)])))

    for i, (freq_hz, duration_ms) in enumerate(symbols):
        p = plan(freq_hz)
        divider_changed = (prev_out_div != p["out_div"] or prev_r_div != p["r_div"])

        # Delay for this symbol = previous symbol's duration (symbol[0] fires immediately)
        delay_ticks = round(symbols[i - 1][1] * 1e-3 / tick_period_s) if i > 0 else 0
        delay_ticks = max(0, min(delay_ticks, 0xFFFFFFFF))

        if divider_changed or i == 0:
            transactions.append((delay_ticks, clk_ctrl_addr, bytes([clk_ctrl])))
            transactions.append((0, ms_base, p["ms_regs"]))
            transactions.append((0, pll_base, p["pll_regs"]))
            reset_mask = 0x20 if pll == PLL.PLLA else 0x80
            transactions.append((0, _REG_PLL_RESET, bytes([reset_mask])))
        else:
            transactions.append((delay_ticks, pll_base, p["pll_regs"]))

        prev_out_div = p["out_div"]
        prev_r_div   = p["r_div"]

    # Final hardware-timed output disable: fires after the last symbol's duration
    last_duration_ms = symbols[-1][1]
    disable_delay    = round(last_duration_ms * 1e-3 / tick_period_s)
    disable_delay    = max(0, min(disable_delay, 0xFFFFFFFF))
    # Disable this clock output by setting its bit in REG_OUTPUT_ENABLE (active-low enable)
    # We write a single-byte transaction to REG_OUTPUT_ENABLE with bit clk set.
    # Because we don't know the current state of other outputs, we only set this clock's bit.
    # The sequencer doesn't support read-modify-write, so we write a safe all-outputs-off value.
    transactions.append((disable_delay, _REG_OUTPUT_ENABLE, bytes([0xFF])))

    return transactions


# --- Register addresses ---

_REG_DEVICE_STATUS      = 0
_REG_OUTPUT_ENABLE      = 3
_REG_OEB_PIN_MASK       = 9
_REG_PLL_INPUT_SOURCE   = 15
_REG_CLK0_CONTROL       = 16  # through 23 for CLK0-CLK7
_REG_CLK3_0_DISABLE     = 24
_REG_CLK7_4_DISABLE     = 25
_REG_MSNA_PARAMS        = 26  # 8 bytes (26-33)
_REG_MSNB_PARAMS        = 34  # 8 bytes (34-41)
_REG_MS0_PARAMS         = 42  # 8 bytes each, MS0 at 42, MS1 at 50, MS2 at 58
_REG_MS6_PARAMS         = 90  # 1 byte each for MS6 (90) and MS7 (91)
_REG_SPREAD_SPECTRUM     = 149
_REG_VCXO_PARAMS        = 162  # 3 bytes (162-164)
_REG_CLK0_PHASE         = 165  # through 170 for CLK0-CLK5
_REG_PLL_RESET          = 177
_REG_CRYSTAL_LOAD       = 183
_REG_FANOUT_ENABLE      = 187

# VCO range per datasheet
_VCO_MIN = 600_000_000
_VCO_MAX = 900_000_000

# Multisynth output divider range
_MS_DIV_MIN = 4
_MS_DIV_MAX = 2048

# PLL feedback divider range (a in a + b/c)
_PLL_A_MIN = 15
_PLL_A_MAX = 90

# R divider options
_R_DIVIDERS = [1, 2, 4, 8, 16, 32, 64, 128]

# Maximum value for b/c denominator (20-bit)
_DENOM_MAX = 0xFFFFF  # 1_048_575


class DriveStrength(enum.IntEnum):
    """Output drive strength levels."""

    DRIVE_2MA = 0
    DRIVE_4MA = 1
    DRIVE_6MA = 2
    DRIVE_8MA = 3


class PLL(enum.IntEnum):
    """PLL selection."""

    PLLA = 0
    PLLB = 1


class Si5351AError(GlasgowAppletError):
    pass


# --- Pure computation (no I/O) ---

def _compute_pll_params(xtal_freq: int, vco_freq: int | float) -> tuple[int, int, int]:
    """Compute PLL feedback multisynth parameters ``(a, b, c)``.

    Computes values such that ``vco_freq = xtal_freq * (a + b/c)``.
    Uses integer-only math. The denominator c is chosen as ``xtal_freq >> 5``
    to stay within the 20-bit limit while preserving maximum resolution.

    Returns
    -------
    tuple[int, int, int]
        PLL feedback parameters (a, b, c).
    """
    a = int(vco_freq // xtal_freq)
    remainder = vco_freq - a * xtal_freq

    # Use the maximum allowed denominator for finest resolution.
    # xtal >> 5 (e.g. 781250 for 25 MHz) was previously used but gives coarse
    # steps at high frequencies — e.g. 5.33 Hz/step at 144 MHz with out_div=6,
    # which cannot represent 6.25 Hz FT8 tone spacing accurately.
    # _DENOM_MAX = 1_048_575 gives the finest possible fractional step.
    c = _DENOM_MAX
    b = int(round(remainder * c / xtal_freq))

    assert _PLL_A_MIN <= a <= _PLL_A_MAX, f"PLL a={a} out of range [{_PLL_A_MIN}, {_PLL_A_MAX}]"
    assert 0 <= b < c
    assert c <= _DENOM_MAX

    return (a, b, c)


def _multisynth_p1p2p3(a: int, b: int, c: int) -> tuple[int, int, int]:
    """Convert (a, b/c) rational divider to Si5351 register parameters P1, P2, P3.

    From AN619::

        f = floor(128 * b / c)
        P1 = 128 * a + f - 512
        P2 = 128 * b - c * f
        P3 = c
    """
    f = (128 * b) // c if c > 0 else 0
    p1 = 128 * a + f - 512
    p2 = 128 * b - c * f
    p3 = c
    return (p1, p2, p3)


def _pack_multisynth_regs(p1: int, p2: int, p3: int) -> bytes:
    """Pack P1, P2, P3 into 8 register bytes for a multisynth bank.

    Byte layout (from datasheet)::

        [0] P3[15:8]
        [1] P3[7:0]
        [2] 0 | R_DIV[2:0] | DIVBY4[1:0] | P1[17:16]
        [3] P1[15:8]
        [4] P1[7:0]
        [5] P3[19:16] | P2[19:16]
        [6] P2[15:8]
        [7] P2[7:0]
    """
    return bytes([
        (p3 >> 8) & 0xFF,
        (p3 >> 0) & 0xFF,
        (p1 >> 16) & 0x03,
        (p1 >> 8) & 0xFF,
        (p1 >> 0) & 0xFF,
        ((p3 >> 12) & 0xF0) | ((p2 >> 16) & 0x0F),
        (p2 >> 8) & 0xFF,
        (p2 >> 0) & 0xFF,
    ])


def _r_divider_bits(r_div: int) -> int:
    """Convert R divider value (1, 2, 4, ..., 128) to the 3-bit register encoding.

    The R divider bits go into byte[2] bits [6:4] of the output multisynth register bank.
    """
    if r_div == 1:
        return 0
    return int(math.log2(r_div)) << 4


def plan_frequency(freq_hz: int | float, xtal_freq: int = 25_000_000, *,
                   vco_max: int | None = None) -> dict:
    """Plan register values for a target output frequency.

    Strategy (from pavelmc/Si5351mcu, optimized for phase noise):
    1. Compute smallest even output divider that keeps VCO <= 900 MHz.
    2. Use integer-only output divider (b=0, c=1) for lowest jitter.
    3. Push all fractional adjustment into the PLL feedback multisynth.
    4. Maximize VCO frequency (use highest possible VCO for best phase noise).

    Parameters
    ----------
    freq_hz
        Target output frequency in Hz.
    xtal_freq
        Crystal/TCXO reference frequency in Hz.

    Returns
    -------
    dict with keys:
        freq_actual : int
            Actual output frequency achievable (may differ slightly from target).
        vco_freq : int
            VCO frequency.
        out_div : int
            Output multisynth integer divider.
        r_div : int
            Output R divider (1, 2, 4, ..., 128).
        pll_a, pll_b, pll_c : int
            PLL feedback multisynth parameters.
        pll_regs : bytes
            8 bytes for PLL multisynth register bank.
        ms_regs : bytes
            8 bytes for output multisynth register bank.
        divby4 : bool
            True if divide-by-4 mode is active.
    """
    if vco_max is None:
        vco_max = _VCO_MAX
    if freq_hz <= 0:
        raise Si5351AError(f"frequency must be positive, got {freq_hz}")

    # Compute output divider and R divider (integer arithmetic for divider selection)
    r_div = 1
    out_div = int(vco_max // freq_hz)
    if out_div < _MS_DIV_MIN:
        raise Si5351AError(
            f"frequency {freq_hz} Hz too high; max is {vco_max // _MS_DIV_MIN} Hz")

    # For very low frequencies, engage R divider
    while out_div > _MS_DIV_MAX:
        r_div *= 2
        out_div = int(vco_max // (freq_hz * r_div))
        if r_div > 128:
            raise Si5351AError(
                f"frequency {freq_hz} Hz too low; min is ~{_VCO_MIN // (_MS_DIV_MAX * 128)} Hz")

    # Force even divider for lower phase noise.
    # When overclocking (vco_max > _VCO_MAX), allow odd dividers — the extra
    # VCO headroom may produce a better-dividing odd value (e.g. out_div=7 at
    # 144 MHz with 1 GHz VCO gives more uniform 6.25 Hz FT8 tone spacing).
    if out_div % 2 != 0 and vco_max <= _VCO_MAX:
        out_div -= 1

    # Clamp to minimum
    if out_div < _MS_DIV_MIN:
        out_div = _MS_DIV_MIN

    # VCO target: use float to preserve sub-Hz precision for fractional frequencies
    vco_freq = out_div * r_div * freq_hz

    # If VCO is out of range, adjust
    if vco_freq > vco_max:
        out_div -= 2
        if out_div < _MS_DIV_MIN:
            out_div = _MS_DIV_MIN
        vco_freq = out_div * r_div * freq_hz

    if vco_freq < _VCO_MIN:
        # Try increasing divider
        out_div += 2
        vco_freq = out_div * r_div * freq_hz

    if not (_VCO_MIN <= vco_freq <= vco_max):
        raise Si5351AError(
            f"cannot plan frequency {freq_hz} Hz: VCO {vco_freq} Hz out of range "
            f"[{_VCO_MIN}, {vco_max}]")

    # PLL multisynth parameters
    pll_a, pll_b, pll_c = _compute_pll_params(xtal_freq, vco_freq)
    pll_p1, pll_p2, pll_p3 = _multisynth_p1p2p3(pll_a, pll_b, pll_c)
    pll_regs = _pack_multisynth_regs(pll_p1, pll_p2, pll_p3)

    # Output multisynth parameters: integer-only (b=0, c=1)
    divby4 = (out_div == 4)
    if divby4:
        # Special divide-by-4 mode: P1=0, P2=0, P3=1, DIVBY4 bits set
        ms_p1, ms_p2, ms_p3 = 0, 0, 1
    else:
        ms_p1, ms_p2, ms_p3 = _multisynth_p1p2p3(out_div, 0, 1)

    ms_regs_raw = _pack_multisynth_regs(ms_p1, ms_p2, ms_p3)
    # Set R divider and DIVBY4 bits in byte[2]
    ms_byte2 = (ms_regs_raw[2] & 0x03) | _r_divider_bits(r_div)
    if divby4:
        ms_byte2 |= 0x0C  # Set DIVBY4 bits [3:2]
    ms_regs = bytes([ms_regs_raw[0], ms_regs_raw[1], ms_byte2,
                     *ms_regs_raw[3:]])

    # Compute actual frequency from the integer math
    actual_vco = xtal_freq * (pll_a + pll_b / pll_c) if pll_c else xtal_freq * pll_a
    freq_actual = actual_vco / (out_div * r_div)

    return {
        "freq_actual": freq_actual,
        "vco_freq": vco_freq,
        "out_div": out_div,
        "r_div": r_div,
        "pll_a": pll_a,
        "pll_b": pll_b,
        "pll_c": pll_c,
        "pll_regs": pll_regs,
        "ms_regs": ms_regs,
        "divby4": divby4,
    }


def plan_sweep(start_hz: int, stop_hz: int, steps: int,
               xtal_freq: int = 25_000_000, *,
               vco_max: int | None = None) -> list[dict]:
    """Plan a frequency sweep, annotating click-free segments.

    Each step is a dict from :func:`plan_frequency` with additional keys:

    - ``click``: True if this step requires a PLL reset (output divider changed).
    - ``segment``: integer segment index (increments at each click boundary).

    Returns a list of step dicts.
    """
    if vco_max is None:
        vco_max = _VCO_MAX
    if steps < 2:
        raise Si5351AError("sweep requires at least 2 steps")

    result = []
    segment = 0
    prev_out_div = None
    prev_r_div = None

    for i in range(steps):
        freq = start_hz + (stop_hz - start_hz) * i // (steps - 1)
        plan = plan_frequency(freq, xtal_freq, vco_max=vco_max)

        click = (prev_out_div is not None and
                 (plan["out_div"] != prev_out_div or plan["r_div"] != prev_r_div))
        if click:
            segment += 1

        plan["click"] = click
        plan["segment"] = segment
        result.append(plan)

        prev_out_div = plan["out_div"]
        prev_r_div = plan["r_div"]

    return result


# --- Hardware interface ---

class Si5351AInterface:
    """High-level interface for Si5351A programmable clock generator.

    Provides direct frequency setting, drive strength control, output enable/disable,
    and click-noise-free frequency changes.
    """

    def __init__(self, logger: logging.Logger, i2c_iface: I2CControllerInterface,
                 i2c_address: int = 0x60, xtal_freq: int = 25_000_000,
                 vco_max: int | None = None):
        self._logger      = logger
        self._level       = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._i2c_iface   = i2c_iface
        self._i2c_address = i2c_address
        self._xtal_freq   = xtal_freq
        self._vco_max     = vco_max if vco_max is not None else _VCO_MAX

        # Cached state for click-free operation
        self._clk_out_div = {}   # clk -> output divider
        self._clk_r_div   = {}   # clk -> R divider
        self._clk_pll     = {}   # clk -> PLL assignment (0=A, 1=B)
        self._clk_drive   = {}   # clk -> DriveStrength
        self._clk_enabled = {}   # clk -> bool

    def _log(self, message, *args):
        self._logger.log(self._level, "Si5351A: " + message, *args)

    async def read(self, address: int, count: int | None = None) -> int | bytes:
        """Read register(s). Returns int if count is None, bytes otherwise."""
        async with self._i2c_iface.transaction():
            await self._i2c_iface.write(self._i2c_address, [address])
            values = await self._i2c_iface.read(self._i2c_address, 1 if count is None else count)
        self._log("read reg=%#04x values=<%s>", address, values.hex())
        return values[0] if count is None else values

    async def write(self, address: int, *values: int):
        """Write register(s) at consecutive addresses (burst write)."""
        values = bytes(values)
        self._log("write reg=%#04x values=<%s>", address, values.hex())
        await self._i2c_iface.write(self._i2c_address, [address, *values])

    async def init(self):
        """Initialize the Si5351A. Disables all outputs, powers down drivers,
        disables spread spectrum.
        """
        # Disable all outputs
        await self.write(_REG_OUTPUT_ENABLE, 0xFF)
        # Power down all output drivers
        for clk in range(8):
            await self.write(_REG_CLK0_CONTROL + clk, 0x80)
        # Disable spread spectrum
        ss_reg = await self.read(_REG_SPREAD_SPECTRUM)
        await self.write(_REG_SPREAD_SPECTRUM, ss_reg & 0x7F)
        self._log("initialized")

    async def status(self) -> dict:
        """Read device status register.

        Returns dict with keys: sys_init, lol_a, lol_b, los, revid.
        """
        reg = await self.read(_REG_DEVICE_STATUS)
        return {
            "sys_init": bool(reg & 0x80),
            "lol_a":    bool(reg & 0x20),
            "lol_b":    bool(reg & 0x10),
            "los":      bool(reg & 0x08),  # CLKIN loss of signal
            "revid":    reg & 0x03,
        }

    def _clk_control_byte(self, clk: int, *, power_down: bool = False) -> int:
        """Build the CLKn_CONTROL register value."""
        if power_down:
            return 0x80

        pll = self._clk_pll.get(clk, PLL.PLLA if clk == 0 else PLL.PLLB)
        drive = self._clk_drive.get(clk, DriveStrength.DRIVE_2MA)
        out_div = self._clk_out_div.get(clk, 0)

        # Bit 7: CLK_PDN = 0 (powered up)
        # Bit 6: MS_INT = 1 if integer mode (always, since we use integer output dividers)
        # Bit 5: MS_SRC = 0 for PLLA, 1 for PLLB
        # Bit 4: CLK_INV = 0
        # Bit 3:2: CLK_SRC = 11 (multisynth N)
        # Bit 1:0: CLK_IDRV = drive strength
        byte = 0x00
        byte |= 0x40  # MS_INT: integer mode for best jitter
        if pll == PLL.PLLB:
            byte |= 0x20
        byte |= 0x0C  # CLK_SRC = multisynth
        byte |= (drive & 0x03)
        return byte

    async def set_drive(self, clk: int, drive: DriveStrength):
        """Set drive strength for a clock output.

        Parameters
        ----------
        clk
            Clock output index (0-7).
        drive
            Drive strength (2, 4, 6, or 8 mA).
        """
        if clk not in range(8):
            raise Si5351AError(f"invalid clock output {clk}")
        self._clk_drive[clk] = drive
        ctrl = self._clk_control_byte(clk)
        await self.write(_REG_CLK0_CONTROL + clk, ctrl)
        self._log("clk%d drive=%s", clk, drive.name)

    async def enable(self, clk: int):
        """Enable a clock output."""
        if clk not in range(8):
            raise Si5351AError(f"invalid clock output {clk}")
        reg = await self.read(_REG_OUTPUT_ENABLE)
        await self.write(_REG_OUTPUT_ENABLE, reg & ~(1 << clk))
        # Also ensure the driver is powered up
        ctrl = self._clk_control_byte(clk)
        await self.write(_REG_CLK0_CONTROL + clk, ctrl)
        self._clk_enabled[clk] = True
        self._log("clk%d enabled", clk)

    async def disable(self, clk: int):
        """Disable a clock output."""
        if clk not in range(8):
            raise Si5351AError(f"invalid clock output {clk}")
        reg = await self.read(_REG_OUTPUT_ENABLE)
        await self.write(_REG_OUTPUT_ENABLE, reg | (1 << clk))
        # Power down the driver
        await self.write(_REG_CLK0_CONTROL + clk, 0x80)
        self._clk_enabled[clk] = False
        self._log("clk%d disabled", clk)

    async def set_freq(self, clk: int, freq_hz: int, *,
                       pll: PLL | None = None,
                       force_reset: bool = False) -> dict:
        """Set clock output frequency.

        Uses click-noise-free technique: only rewrites PLL registers when the
        output multisynth divider hasn't changed. A PLL reset is only performed
        when the output divider changes.

        Parameters
        ----------
        clk
            Clock output index (0-2 for full multisynth, 6-7 for integer-only).
        freq_hz
            Target frequency in Hz.
        pll
            PLL to use. Default: PLLA for CLK0, PLLB for CLK1/CLK2.
        force_reset
            Force a PLL reset even if the output divider hasn't changed.

        Returns
        -------
        dict
            Frequency plan including actual frequency achieved.
        """
        if clk not in range(3):  # CLK0-CLK2 for now (full multisynth)
            raise Si5351AError(f"set_freq currently supports CLK0-CLK2, got CLK{clk}")

        if pll is None:
            pll = PLL.PLLA if clk == 0 else PLL.PLLB

        plan = plan_frequency(freq_hz, self._xtal_freq, vco_max=self._vco_max)

        # Determine if output divider changed
        prev_out_div = self._clk_out_div.get(clk)
        prev_r_div = self._clk_r_div.get(clk)
        divider_changed = (prev_out_div != plan["out_div"] or
                           prev_r_div != plan["r_div"] or
                           force_reset)

        # Update cached state
        self._clk_out_div[clk] = plan["out_div"]
        self._clk_r_div[clk] = plan["r_div"]
        self._clk_pll[clk] = pll

        # PLL register bank base address
        pll_base = _REG_MSNA_PARAMS if pll == PLL.PLLA else _REG_MSNB_PARAMS
        # Output multisynth register bank base address
        ms_base = _REG_MS0_PARAMS + (clk * 8)

        if divider_changed:
            # Full update: write output multisynth, PLL, CLK control, then reset
            self._log("clk%d freq=%d out_div=%d r_div=%d (divider changed, resetting)",
                      clk, freq_hz, plan["out_div"], plan["r_div"])

            # Write CLK control register (PLL source, integer mode, drive)
            ctrl = self._clk_control_byte(clk)
            await self.write(_REG_CLK0_CONTROL + clk, ctrl)

            # Write output multisynth registers (8 bytes burst)
            await self.write(ms_base, *plan["ms_regs"])

            # Write PLL multisynth registers (8 bytes burst)
            await self.write(pll_base, *plan["pll_regs"])

            # Reset PLL
            reset_mask = 0x20 if pll == PLL.PLLA else 0x80
            await self.write(_REG_PLL_RESET, reset_mask)
        else:
            # Click-free update: only rewrite PLL registers
            self._log("clk%d freq=%d (PLL-only update, click-free)", clk, freq_hz)
            await self.write(pll_base, *plan["pll_regs"])

        return plan

    async def sweep(self, clk: int, start_hz: int, stop_hz: int, steps: int,
                    duration_s: float, *, pll: PLL | None = None) -> dict:
        """Perform a host-driven frequency sweep.

        Pre-computes all register values, then executes the sweep with
        best-effort timing. Reports click boundaries and actual performance.

        Parameters
        ----------
        clk
            Clock output index (0-2).
        start_hz, stop_hz
            Sweep frequency range in Hz.
        steps
            Number of frequency steps.
        duration_s
            Target sweep duration in seconds.
        pll
            PLL to use. Default: PLLA for CLK0, PLLB for CLK1/CLK2.

        Returns
        -------
        dict with sweep statistics.
        """
        if pll is None:
            pll = PLL.PLLA if clk == 0 else PLL.PLLB

        self._log("sweep clk%d %d-%d Hz, %d steps over %.1fs",
                  clk, start_hz, stop_hz, steps, duration_s)

        # Pre-compute all steps
        sweep_plan = plan_sweep(start_hz, stop_hz, steps, self._xtal_freq,
                                vco_max=self._vco_max)
        click_count = sum(1 for s in sweep_plan if s["click"])
        segments = sweep_plan[-1]["segment"] + 1

        self._log("sweep planned: %d steps, %d clicks, %d click-free segments",
                  steps, click_count, segments)

        step_interval = duration_s / steps

        # Execute sweep
        t_start = time.monotonic()
        for i, plan in enumerate(sweep_plan):
            await self.set_freq(clk, plan["freq_actual"], pll=pll)

            # Best-effort timing
            elapsed = time.monotonic() - t_start
            target = (i + 1) * step_interval
            if target > elapsed:
                await asyncio.sleep(target - elapsed)

        t_end = time.monotonic()
        actual_duration = t_end - t_start

        return {
            "steps": steps,
            "clicks": click_count,
            "segments": segments,
            "target_duration_s": duration_s,
            "actual_duration_s": actual_duration,
            "avg_step_rate_hz": steps / actual_duration if actual_duration > 0 else 0,
        }


# --- CLI Applet ---

class ControlSi5351ANextApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "control Si5351A programmable clock generator"
    description = """
    Control a Si5351A programmable clock generator with direct frequency setting,
    drive strength control, and click-noise-free operation.

    This applet computes PLL and multisynth divider parameters on the host and
    writes them to the device over I²C. It uses integer-only output dividers and
    maximizes VCO frequency for best phase noise.

    Frequency range: ~8 kHz to 225 MHz (output dependent).

    For raw register access or ClockBuilder Pro CSV loading, use the ``control-si535x``
    applet instead.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "scl", default=True, required=True)
        access.add_pins_argument(parser, "sda", default=True, required=True)

        def i2c_address(arg):
            return int(arg, 0)
        parser.add_argument(
            "--i2c-address", type=i2c_address, metavar="ADDR", default=0x60,
            help="I2C address of the Si5351A (default: %(default)#04x)")
        parser.add_argument(
            "--xtal-freq", type=int, metavar="HZ", default=25_000_000,
            help="crystal/TCXO reference frequency in Hz (default: %(default)d)")
        parser.add_argument(
            "--ppb", type=float, metavar="PPB", default=0.0,
            help="TCXO frequency correction in parts-per-billion; positive = TCXO runs fast "
                 "(output will be too high), negative = runs slow (default: %(default)g)")
        parser.add_argument(
            "--vco-max", type=int, metavar="HZ", default=900_000_000,
            help="maximum VCO frequency in Hz; values above 900 MHz overclock the Si5351 "
                 "allowing out_div=6 at >150 MHz but with degraded phase noise "
                 "(default: %(default)d, safe overclock limit: ~1_000_000_000)")
        parser.add_argument(
            "--clock-ppm", type=float, metavar="PPM", default=0.0,
            help="FPGA oscillator error in parts-per-million; positive = FPGA clock runs fast "
                 "(ticks are shorter than nominal, symbols finish early), negative = runs slow; "
                 "corrects hardware-timed symbol durations for sweep-hw and sequence "
                 "(default: %(default)g)")
    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            # Combined I2C controller + hardware sequencer (single I2CInitiator, shared pins)
            self._ctrl_iface = Si5351AControllerInterface(self.logger, self.assembly,
                scl=args.scl, sda=args.sda)
            # Wrap the command pipe in a compatible I2CControllerInterface protocol object
            self.i2c_iface = _CmdPipeI2CInterface(self.logger, self._ctrl_iface)
            corrected_xtal = round(args.xtal_freq * (1 + args.ppb / 1e9))
            self.si5351a_iface = Si5351AInterface(self.logger, self.i2c_iface,
                args.i2c_address, corrected_xtal, args.vco_max)
            # Hardware sequencer interface
            self.seq_iface = I2CSequencerInterface(self.logger, self._ctrl_iface.seq_pipe,
                args.i2c_address, self._ctrl_iface.sys_clk_freq)

    async def setup(self, args):
        await self._ctrl_iface.clock.set_frequency(400e3)
        # init() powers down all CLK outputs and disables spread spectrum.
        # Skip it for 'sequence' — the sequence is fully self-contained and
        # init()'s 35 I2C round-trips (~3 s) dominate startup latency.
        if args.operation != "sequence":
            await self.si5351a_iface.init()

    @classmethod
    def add_run_arguments(cls, parser):
        def frequency(arg):
            return int(float(arg))
        def outputs(arg):
            return [int(x) for x in arg.split(",")]

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        # --- set-freq ---
        p_set_freq = p_operation.add_parser(
            "set-freq", help="set output frequency")
        p_set_freq.add_argument(
            "--clk", type=int, metavar="N", default=0,
            help="clock output (0-2, default: 0)")
        p_set_freq.add_argument(
            "--drive", type=str, metavar="STRENGTH",
            choices=["2mA", "4mA", "6mA", "8mA"], default="8mA",
            help="drive strength (default: 8mA)")
        p_set_freq.add_argument(
            "--pll", type=str, metavar="PLL", choices=["A", "B"], default=None,
            help="PLL to use (default: A for CLK0, B for CLK1/CLK2)")
        p_set_freq.add_argument(
            "freq", metavar="FREQ", type=frequency,
            help="target frequency in Hz (supports scientific notation, e.g. 10e6)")

        # --- enable ---
        p_enable = p_operation.add_parser(
            "enable", help="enable clock output(s)")
        p_enable.add_argument(
            "outputs", metavar="OUTPUTS", type=outputs,
            help="comma-separated list of clock outputs to enable (e.g. 0,1)")

        # --- disable ---
        p_disable = p_operation.add_parser(
            "disable", help="disable clock output(s)")
        p_disable.add_argument(
            "outputs", metavar="OUTPUTS", type=outputs,
            help="comma-separated list of clock outputs to disable (e.g. 0,1)")

        # --- status ---
        p_operation.add_parser(
            "status", help="read device status")

        # --- sweep ---
        p_sweep = p_operation.add_parser(
            "sweep", help="sweep frequency range")
        p_sweep.add_argument(
            "--clk", type=int, metavar="N", default=0,
            help="clock output (0-2, default: 0)")
        p_sweep.add_argument(
            "--steps", type=int, metavar="N", default=1000,
            help="number of frequency steps (default: 1000)")
        p_sweep.add_argument(
            "--duration", type=float, metavar="SECS", default=10.0,
            help="sweep duration in seconds (default: 10)")
        p_sweep.add_argument(
            "--pll", type=str, metavar="PLL", choices=["A", "B"], default=None,
            help="PLL to use (default: A for CLK0, B for CLK1/CLK2)")
        p_sweep.add_argument(
            "start", metavar="START", type=frequency,
            help="start frequency in Hz")
        p_sweep.add_argument(
            "stop", metavar="STOP", type=frequency,
            help="stop frequency in Hz")

        # --- sweep-hw ---
        p_sweep_hw = p_operation.add_parser(
            "sweep-hw", help="hardware-timed frequency sweep (FPGA-precision timing)")
        p_sweep_hw.add_argument(
            "--clk", type=int, metavar="N", default=0,
            help="clock output (0-2, default: 0)")
        p_sweep_hw.add_argument(
            "--steps", type=int, metavar="N", default=1000,
            help="number of frequency steps (default: 1000)")
        p_sweep_hw.add_argument(
            "--step-interval", type=float, metavar="MS", default=1.0,
            help="time between steps in milliseconds (default: 1.0)")
        p_sweep_hw.add_argument(
            "--pll", type=str, metavar="PLL", choices=["A", "B"], default=None,
            help="PLL to use (default: A for CLK0, B for CLK1/CLK2)")
        p_sweep_hw.add_argument(
            "start", metavar="START", type=frequency,
            help="start frequency in Hz")
        p_sweep_hw.add_argument(
            "stop", metavar="STOP", type=frequency,
            help="stop frequency in Hz")

        # --- sequence ---
        p_sequence = p_operation.add_parser(
            "sequence",
            help="hardware-timed symbol sequence from CSV (freq_hz,duration_ms)")
        p_sequence.add_argument(
            "--clk", type=int, metavar="N", default=0,
            help="clock output (0-2, default: 0)")
        p_sequence.add_argument(
            "--pll", type=str, metavar="PLL", choices=["A", "B"], default=None,
            help="PLL to use (default: A for CLK0, B for CLK1/CLK2)")
        p_sequence.add_argument(
            "--quiet", action="store_true",
            help="suppress pre-flight summary")
        p_sequence.add_argument(
            "file", metavar="FILE",
            type=lambda p: open(p) if p != "-" else __import__("sys").stdin,
            help="CSV file of freq_hz,duration_ms pairs, or - for stdin")

        # --- plan ---
        p_plan = p_operation.add_parser(
            "plan", help="show frequency plan without writing to hardware")
        p_plan.add_argument(
            "freq", metavar="FREQ", type=frequency,
            help="target frequency in Hz")

        # --- sweep-plan ---
        p_sweep_plan = p_operation.add_parser(
            "sweep-plan", help="show sweep plan with click boundaries")
        p_sweep_plan.add_argument(
            "--steps", type=int, metavar="N", default=100,
            help="number of frequency steps (default: 100)")
        p_sweep_plan.add_argument(
            "start", metavar="START", type=frequency,
            help="start frequency in Hz")
        p_sweep_plan.add_argument(
            "stop", metavar="STOP", type=frequency,
            help="stop frequency in Hz")

    async def run(self, args):
        drive_map = {
            "2mA": DriveStrength.DRIVE_2MA,
            "4mA": DriveStrength.DRIVE_4MA,
            "6mA": DriveStrength.DRIVE_6MA,
            "8mA": DriveStrength.DRIVE_8MA,
        }

        if args.operation == "set-freq":
            pll = None
            if args.pll:
                pll = PLL.PLLA if args.pll == "A" else PLL.PLLB

            await self.si5351a_iface.set_drive(
                args.clk, drive_map[args.drive])
            plan = await self.si5351a_iface.set_freq(
                args.clk, args.freq, pll=pll)
            await self.si5351a_iface.enable(args.clk)

            freq_err = plan["freq_actual"] - args.freq
            self.logger.info(
                "CLK%d: requested=%d Hz, actual=%d Hz "
                "(error=%+d Hz)",
                args.clk, args.freq,
                plan["freq_actual"], freq_err)
            self.logger.info(
                "  VCO=%d Hz, out_div=%d, r_div=%d, "
                "divby4=%s",
                plan["vco_freq"], plan["out_div"],
                plan["r_div"], plan["divby4"])

        elif args.operation == "enable":
            for clk in args.outputs:
                await self.si5351a_iface.enable(clk)
                self.logger.info("CLK%d enabled", clk)

        elif args.operation == "disable":
            for clk in args.outputs:
                await self.si5351a_iface.disable(clk)
                self.logger.info("CLK%d disabled", clk)

        elif args.operation == "status":
            st = await self.si5351a_iface.status()
            self.logger.info(
                "SYS_INIT=%s LOL_A=%s LOL_B=%s "
                "LOS=%s REVID=%d",
                st["sys_init"], st["lol_a"],
                st["lol_b"], st["los"], st["revid"])

        elif args.operation == "sweep":
            pll = None
            if args.pll:
                pll = PLL.PLLA if args.pll == "A" else PLL.PLLB

            await self.si5351a_iface.set_drive(
                args.clk, DriveStrength.DRIVE_2MA)
            await self.si5351a_iface.set_freq(
                args.clk, args.start, pll=pll)
            await self.si5351a_iface.enable(args.clk)

            result = await self.si5351a_iface.sweep(
                args.clk, args.start, args.stop,
                args.steps, args.duration, pll=pll)

            self.logger.info(
                "sweep complete: %d steps, %d clicks, "
                "%d segments",
                result["steps"], result["clicks"],
                result["segments"])
            self.logger.info(
                "  duration: %.2fs (target: %.2fs), "
                "avg rate: %.1f steps/s",
                result["actual_duration_s"],
                result["target_duration_s"],
                result["avg_step_rate_hz"])

        elif args.operation == "sweep-hw":
            pll = None
            if args.pll:
                pll = PLL.PLLA if args.pll == "A" else PLL.PLLB
            if pll is None:
                pll = PLL.PLLA if args.clk == 0 else PLL.PLLB

            # Convert step interval (ms) to sequencer delay ticks.
            # One delay tick = one SCL quarter-period = 1 / (4 * scl_freq).
            # At 400 kHz: tick_period = 625 ns.
            # --clock-ppm corrects for FPGA oscillator error: if the FPGA runs fast
            # by N ppm, real ticks are shorter so we need more of them; dividing
            # tick_period_s by (1 + ppm/1e6) inflates the tick count accordingly.
            scl_freq = await self._ctrl_iface.clock.get_frequency()
            tick_period_s = 1.0 / (4 * scl_freq) / (1 + args.clock_ppm / 1e6)
            step_interval_ticks = max(1, round(args.step_interval * 1e-3 / tick_period_s))
            step_interval_ticks = min(step_interval_ticks, 0xFFFFFFFF)

            xtal = self.si5351a_iface._xtal_freq
            sweep_plan_data = plan_sweep(args.start, args.stop, args.steps, xtal,
                                         vco_max=self.si5351a_iface._vco_max)
            transactions = encode_sweep(
                sweep_plan_data, step_interval_ticks,
                self.si5351a_iface._i2c_address, pll, args.clk)

            click_count = sum(1 for s in sweep_plan_data if s["click"])
            segments    = sweep_plan_data[-1]["segment"] + 1
            total_time  = args.steps * args.step_interval / 1000.0

            self.logger.info(
                "sweep-hw CLK%d %d->%d Hz, %d steps, "
                "%d clicks, %.1f ms/step, ~%.1fs",
                args.clk, args.start, args.stop, args.steps,
                click_count, args.step_interval, total_time)
            self.logger.info(
                "  %d sequencer transactions, step_interval=%d ticks",
                len(transactions), step_interval_ticks)

            # Configure drive and enable output first via normal I2C path
            await self.si5351a_iface.set_drive(args.clk, DriveStrength.DRIVE_2MA)
            await self.si5351a_iface.set_freq(args.clk, args.start, pll=pll)
            await self.si5351a_iface.enable(args.clk)

            t_invoke = time.monotonic()
            started_at_s, elapsed_hw_s = await self.seq_iface.run_sequence(transactions)
            startup_ms = (started_at_s - t_invoke) * 1000.0

            self.logger.info(
                "sweep-hw complete: hw elapsed %.3f s, startup %.1f ms (%d clicks, %d segments)",
                elapsed_hw_s, startup_ms, click_count, segments)

        elif args.operation == "sequence":
            pll = None
            if args.pll:
                pll = PLL.PLLA if args.pll == "A" else PLL.PLLB
            if pll is None:
                pll = PLL.PLLA if args.clk == 0 else PLL.PLLB

            symbols = _parse_sequence_csv(args.file)

            scl_freq      = await self._ctrl_iface.clock.get_frequency()
            tick_period_s = 1.0 / (4 * scl_freq) / (1 + args.clock_ppm / 1e6)
            xtal          = self.si5351a_iface._xtal_freq

            transactions = encode_sequence(
                symbols, xtal, args.clk, pll, tick_period_s,
                self.si5351a_iface._i2c_address, enable_output=True,
                vco_max=self.si5351a_iface._vco_max)

            # Pre-flight summary
            if not args.quiet:
                unique_freqs  = sorted({f for f, _ in symbols})
                total_s       = sum(d for _, d in symbols) / 1000.0
                # Count click boundaries (out_div changes between consecutive symbols)
                plan_cache = {}
                def _plan(f):
                    if f not in plan_cache:
                        plan_cache[f] = plan_frequency(f, xtal,
                                                        vco_max=self.si5351a_iface._vco_max)
                    return plan_cache[f]
                clicks = 0
                prev_div = prev_r = None
                for freq_hz, _ in symbols:
                    p = _plan(freq_hz)
                    if prev_div is not None and (p["out_div"] != prev_div or p["r_div"] != prev_r):
                        clicks += 1
                    prev_div, prev_r = p["out_div"], p["r_div"]
                errors = [_plan(f)["freq_actual"] - f for f in unique_freqs]
                max_err = max(abs(e) for e in errors)
                err_str = (f"max error {max_err:+.3f} Hz" if max_err >= 0.001
                           else "error <1 mHz")
                print(f"Sequence: {len(symbols)} symbols, {total_s:.3f} s nominal")
                print(f"  Frequencies: {len(unique_freqs)} unique "
                      f"({min(unique_freqs):,} – {max(unique_freqs):,} Hz), {err_str}")
                print(f"  Click boundaries: {clicks}"
                      f"{'  (fully click-free)' if clicks == 0 else ''}")
                print(f"  Transactions: {len(transactions)} "
                      f"(1 enable + {'PLL-only' if clicks == 0 else 'mixed'} + 1 disable)")
                print(f"  Timing resolution: ±{tick_period_s*1e9:.0f} ns/symbol boundary")

            t_invoke = time.monotonic()
            started_at_s, elapsed_hw_s = await self.seq_iface.run_sequence(transactions)
            startup_ms = (started_at_s - t_invoke) * 1000.0
            nominal_s  = sum(dur_ms for _, dur_ms in symbols) / 1000.0
            drift_ms   = (elapsed_hw_s - nominal_s) * 1000.0

            self.logger.info("sequence: started %.1f ms after invocation", startup_ms)
            self.logger.info("sequence: complete, %.3f s hw elapsed (nominal %.3f s, drift %+.1f ms)",
                             elapsed_hw_s, nominal_s, drift_ms)
            # Output already disabled by the final hardware transaction

        elif args.operation == "plan":
            xtal = self.si5351a_iface._xtal_freq
            plan = plan_frequency(args.freq, xtal, vco_max=self.si5351a_iface._vco_max)
            freq_err = plan["freq_actual"] - args.freq
            print(f"Target:   {args.freq} Hz")
            print(f"Actual:   {plan['freq_actual']:.4f} Hz "
                  f"(error: {freq_err:+.4f} Hz)")
            print(f"VCO:      {plan['vco_freq']} Hz")
            print(f"Out div:  {plan['out_div']} "
                  f"(even, integer-only)")
            print(f"R div:    {plan['r_div']}")
            print(f"PLL:      a={plan['pll_a']}, "
                  f"b={plan['pll_b']}, c={plan['pll_c']}")
            print(f"Div-by-4: {plan['divby4']}")
            print(f"PLL regs: {plan['pll_regs'].hex()}")
            print(f"MS regs:  {plan['ms_regs'].hex()}")

        elif args.operation == "sweep-plan":
            xtal = self.si5351a_iface._xtal_freq
            sweep = plan_sweep(
                args.start, args.stop, args.steps, xtal,
                vco_max=self.si5351a_iface._vco_max)
            click_count = sum(
                1 for s in sweep if s["click"])
            segments = sweep[-1]["segment"] + 1

            print(f"Sweep: {args.start} -> {args.stop} Hz, "
                  f"{args.steps} steps")
            print(f"Click-free segments: {segments} "
                  f"({click_count} clicks)")
            print()

            current_segment = 0
            seg_start_freq = sweep[0]["freq_actual"]
            for i, step in enumerate(sweep):
                changed = step["segment"] != current_segment
                is_last = i == len(sweep) - 1
                if changed:
                    prev = sweep[i - 1]
                    print(
                        f"  Segment {current_segment}: "
                        f"{seg_start_freq:>12,} - "
                        f"{prev['freq_actual']:>12,} Hz "
                        f"(out_div={prev['out_div']}, "
                        f"r_div={prev['r_div']})")
                    current_segment = step["segment"]
                    seg_start_freq = step["freq_actual"]
                if is_last:
                    print(
                        f"  Segment {current_segment}: "
                        f"{seg_start_freq:>12,} - "
                        f"{step['freq_actual']:>12,} Hz "
                        f"(out_div={step['out_div']}, "
                        f"r_div={step['r_div']})")

    @classmethod
    def tests(cls):
        from . import test
        return test.ControlSi5351ANextAppletTestCase


class ControlSi5351ANextAppletTool(GlasgowAppletTool, applet=ControlSi5351ANextApplet):
    help = "analyse Si5351A symbol sequences without hardware"
    description = """
    Offline analysis of hardware-timed symbol sequences (CSV of freq_hz,duration_ms).

    Reports per-symbol frequency error (SI5351 fractional PLL quantisation) and
    timing quantisation error (duration rounding to FPGA tick boundaries), both of
    which contribute to decoding difficulty in weak-signal modes such as FT8 and WSPR.
    """

    @classmethod
    def add_arguments(cls, parser):
        parser.add_argument(
            "--xtal-freq", type=int, metavar="HZ", default=25_000_000,
            help="crystal/TCXO reference frequency in Hz (default: %(default)d)")
        parser.add_argument(
            "--ppb", type=float, metavar="PPB", default=0.0,
            help="TCXO frequency correction in parts-per-billion (default: %(default)g)")
        parser.add_argument(
            "--vco-max", type=int, metavar="HZ", default=900_000_000,
            help="maximum VCO frequency in Hz (default: %(default)d)")
        parser.add_argument(
            "--scl-freq", type=float, metavar="HZ", default=400e3,
            help="assumed SCL frequency for tick period calculation (default: %(default)g)")
        parser.add_argument(
            "--clock-ppm", type=float, metavar="PPM", default=0.0,
            help="FPGA oscillator error in PPM; positive = FPGA runs fast (default: %(default)g)")

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_analyze = p_operation.add_parser(
            "analyze-sequence",
            help="report frequency and timing errors for a symbol sequence CSV")
        p_analyze.add_argument(
            "file", metavar="FILE",
            type=lambda p: open(p) if p != "-" else __import__("sys").stdin,
            help="CSV file of freq_hz,duration_ms pairs, or - for stdin")

    async def run(self, args):
        if args.operation == "analyze-sequence":
            xtal          = round(args.xtal_freq * (1 + args.ppb / 1e9))
            tick_period_s = 1.0 / (4 * args.scl_freq) / (1 + args.clock_ppm / 1e6)

            symbols = _parse_sequence_csv(args.file)

            plan_cache = {}
            def _plan(f):
                if f not in plan_cache:
                    plan_cache[f] = plan_frequency(f, xtal, vco_max=args.vco_max)
                return plan_cache[f]

            unique_freqs = sorted({f for f, _ in symbols})
            total_s      = sum(d for _, d in symbols) / 1000.0

            clicks = 0
            prev_div = prev_r = None
            for freq_hz, _ in symbols:
                p = _plan(freq_hz)
                if prev_div is not None and (p["out_div"] != prev_div or p["r_div"] != prev_r):
                    clicks += 1
                prev_div, prev_r = p["out_div"], p["r_div"]

            freq_errors   = [_plan(f)["freq_actual"] - f for f in unique_freqs]
            max_freq_err  = max(abs(e) for e in freq_errors)
            freq_err_str  = (f"max {max_freq_err:+.3f} Hz" if max_freq_err >= 0.001
                             else "<1 mHz")

            print(f"Sequence: {len(symbols)} symbols, {total_s:.3f} s nominal")
            print(f"  xtal={xtal:,} Hz, scl={args.scl_freq/1e3:.0f} kHz "
                  f"(tick={tick_period_s*1e9:.0f} ns), clock_ppm={args.clock_ppm:+g}")
            print(f"  Frequencies: {len(unique_freqs)} unique "
                  f"({min(unique_freqs):,} – {max(unique_freqs):,} Hz), freq error {freq_err_str}")
            print(f"  Click boundaries: {clicks}"
                  f"{'  (fully click-free)' if clicks == 0 else ''}")
            print()
            print(f"  {'#':>4}  {'Target Hz':>12}  {'Actual Hz':>14}  "
                  f"{'Freq err Hz':>12}  {'Dur ms':>9}  {'Ticks':>10}  {'Timing err ms':>14}")
            tick_errs = []
            for i, (freq_hz, dur_ms) in enumerate(symbols):
                p = _plan(freq_hz)
                freq_err     = p["freq_actual"] - freq_hz
                delay_ticks  = round(dur_ms * 1e-3 / tick_period_s) if i > 0 else 0
                actual_dur_ms = delay_ticks * tick_period_s * 1e3
                timing_err_ms = actual_dur_ms - dur_ms if i > 0 else 0.0
                tick_errs.append(timing_err_ms)
                print(f"  {i:>4}  {freq_hz:>12,}  {p['freq_actual']:>14,.4f}  "
                      f"{freq_err:>+12.4f}  {dur_ms:>9.3f}  {delay_ticks:>10,}  "
                      f"{timing_err_ms:>+14.4f}")
            print()
            total_timing_err_ms = sum(tick_errs)
            max_timing_err_ms   = max(abs(e) for e in tick_errs) if tick_errs else 0.0
            print(f"  Timing quantisation: max ±{max_timing_err_ms:.4f} ms/symbol, "
                  f"cumulative {total_timing_err_ms:+.4f} ms over sequence")
