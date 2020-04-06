# Chipcon Debug and Programming Interface
#
# Supports all TI/Chipcon embedded 8051 radios:
#    CC1110, CC1111, CC2510, CC2511, CC2430, CC2431, CC2530, CC2531, CC2533, CC2540, CC2541
#
# Base protocol from:
#   "CC1110/CC2430/CC2510 Debug and Programming Interface Specification Rev. 1.2"
#
# Extended protocol from:
#   "CC253x System-on-Chip Solution for 2.4-GHz IEEE 802.15.4 and ZigBee® Applications
#    CC2540/41 System-on-Chip Solution for 2.4-GHz Bluetooth® low energy Applications
#    User's Guide - Literature Number: SWRU191F April 2009–Revised April 2014"
#
import logging
import asyncio
import random
from collections import namedtuple
from enum import IntEnum, IntFlag

from nmigen import *
from ....database.ti.chipcon import *
from ....gateware.clockgen import *
from ... import *
from ....arch.cc8051 import *

class CCDPIError(GlasgowAppletError):
    pass

class CCDPIBus(Elaboratable):
    """Bus interface - word<->serial."""

    def __init__(self, width, pads, period_cyc):
        self.pads = pads
        self.period_cyc = period_cyc
        self.di  = Signal(width)
        self.do  = Signal(width)
        self.bits = Signal(range(width+1))
        self.w   = Signal()
        self.ack = Signal()
        self.rdy = Signal()
        self.reset = Signal()
        self.ddat = Signal()

    def elaborate(self, platform):
        m = Module()
        m.submodules.period = period = ClockGen(self.period_cyc)

        dclk = Signal()
        oe   = Signal()
        o    = Signal()
        m.d.comb += [
            self.pads.dclk_t.oe.eq(1),
            self.pads.dclk_t.o.eq(dclk),
            self.pads.ddat_t.oe.eq(oe),
            self.pads.ddat_t.o.eq(o),
            self.ddat.eq(self.pads.ddat_t.i),
            self.pads.resetn_t.oe.eq(1),
            self.pads.resetn_t.o.eq(~self.reset),
        ]

        d   = Signal(self.di.shape())
        cnt = Signal(self.bits.shape())
        m.d.comb += self.di.eq(d)

        with m.FSM():
            with m.State("READY"):
                m.d.comb += self.rdy.eq(1),
                with m.If(self.ack):
                    m.d.sync += cnt.eq(self.bits)
                    with m.If(self.w):
                        m.d.sync += d.eq(self.do)
                        m.d.sync += oe.eq(1)
                        m.next = "WRITE_RISE"
                    with m.Else():
                        m.d.sync += oe.eq(0)
                        m.next = "READ_RISE"

            with m.State("WRITE_RISE"):
                with m.If(period.stb_r):
                    with m.If(cnt == 0):
                        m.d.sync += oe.eq(0)
                        m.next = "READY"
                    with m.Else():
                        m.d.sync += [
                            dclk.eq(1),
                            o.eq(d[-1]),
                            d[1:].eq(d),
                            cnt.eq(cnt-1),
                        ]
                        m.next = "WRITE_FALL"

            with m.State("WRITE_FALL"):
                with m.If(period.stb_f):
                    m.d.sync += dclk.eq(0)
                    m.next = "WRITE_RISE"

            with m.State("READ_RISE"):
                with m.If(period.stb_r):
                    with m.If(cnt == 0):
                        m.next = "READY"
                    with m.Else():
                        m.d.sync += [
                            dclk.eq(1),
                            cnt.eq(cnt-1),
                        ]
                        m.next = "READ_FALL"

            with m.State("READ_FALL"):
                with m.If(period.stb_f):
                    m.d.sync += [
                        dclk.eq(0),
                        d.eq(Cat(self.ddat, d[0:-1])),
                    ]
                    m.next = "READ_RISE"
        return m

class Cmd(IntEnum):
    CHIP_ERASE    = 0b0001_0100
    WR_CONFIG     = 0b0001_1101
    RD_CONFIG     = 0b0010_0100
    GET_PC        = 0b0010_1000
    READ_STATUS   = 0b0011_0100
    SET_HW_BRKPNT = 0b0011_1111
    HALT          = 0b0100_0100
    RESUME        = 0b0100_1100
    DEBUG_INSTR   = 0b0101_0100
    DEBUG_INSTR1  = 0b0101_0101
    DEBUG_INSTR2  = 0b0101_0110
    DEBUG_INSTR3  = 0b0101_0111
    STEP_INSTR    = 0b0101_1100
    STEP_REPLACE  = 0b0110_0100
    GET_CHIP_ID   = 0b0110_1000

class Config(IntFlag):
    TIMERS_OFF          = 0b0000_1000
    DMA_PAUSE           = 0b0000_0100
    TIMER_SUSPEND       = 0b0000_0010
    SEL_FLASH_INFO_PAGE = 0b0000_0001

class Status(IntFlag):
    CHIP_ERASE_DONE   = 0b1000_0000
    PCON_IDLE         = 0b0100_0000
    CPU_HALTED        = 0b0010_0000
    POWER_MODE_0      = 0b0001_0000
    HALT_STATUS       = 0b0000_1000
    DEBUG_LOCKED      = 0b0000_0100
    OSCILLATOR_STABLE = 0b0000_0010
    STACK_OVERFLOW    = 0b0000_0001

    CHIP_ERASE_BUSY   = 0b1000_0000 # Extended parts invert meaning of this bit!

class Operation(IntEnum):
    COMMAND              = 0
    COMMAND_DISCARD      = 1
    COMMAND_POLL         = 2
    COMMAND_POLL_DISCARD = 3
    RESET_ON             = 4
    RESET_OFF            = 5
    DEBUG_ENTRY          = 6
    DELAY                = 7

class CCDPISubtarget(Elaboratable):
    def __init__(self, pads, out_fifo, in_fifo, period_cyc, delay_cyc):
        self.pads = pads
        self.out_fifo = out_fifo
        self.in_fifo = in_fifo
        self.period_cyc = period_cyc
        self.delay_cyc = delay_cyc

    def elaborate(self, platform):
        m = Module()
        m.submodules.bus = bus = CCDPIBus(8, self.pads, self.period_cyc)
        m.submodules.delay = delay = ClockGen(self.delay_cyc)

        op = Signal(3)
        count_out = Signal(3)
        count_in = Signal(2)

        reset = Signal()
        delay_downcount = Signal(16)
        m.d.comb += bus.reset.eq(reset)

        with m.FSM():
            with m.State("READY"):
                m.d.comb += self.in_fifo.flush.eq(1)
                with m.If(self.out_fifo.readable):
                    m.d.comb += self.out_fifo.re.eq(1)
                    m.d.sync += Cat(count_in, count_out, op).eq(self.out_fifo.dout)
                    m.next = "START"

            with m.State("START"):
                with m.Switch(op):
                    with m.Case(Operation.COMMAND,
                                Operation.COMMAND_DISCARD,
                                Operation.COMMAND_POLL,
                                Operation.COMMAND_POLL_DISCARD):
                        m.next = "OUT"
                    with m.Case(Operation.DEBUG_ENTRY):
                        m.next = "DEBUG"
                    with m.Case(Operation.RESET_ON):
                        m.d.sync += reset.eq(1)
                        m.next = "READY"
                    with m.Case(Operation.RESET_OFF):
                        m.d.sync += reset.eq(0)
                        m.next = "READY"
                    with m.Case(Operation.DELAY):
                        m.next = "DELAY_H"

            with m.State("OUT"):
                with m.If(count_out == 0):
                    m.next = "CHANGE_1"
                with m.Elif(bus.rdy & self.out_fifo.readable):
                    m.d.comb += [
                        self.out_fifo.re.eq(1),
                        bus.do.eq(self.out_fifo.dout),
                        bus.w.eq(1),
                        bus.bits.eq(8),
                        bus.ack.eq(1),
                    ]
                    m.d.sync += count_out.eq(count_out-1)

            with m.State("CHANGE_1"):
                with m.If(delay.stb_r & bus.rdy):
                    m.next = "CHANGE_2"

            with m.State("CHANGE_2"):
                with m.If(delay.stb_r & bus.rdy):
                    with m.If((op == Operation.COMMAND_POLL) |
                              (op == Operation.COMMAND_POLL_DISCARD)):
                        m.next = "POLL"
                    with m.Else():
                        m.next = "IN"

            with m.State("POLL"):
                with m.If(bus.ddat): # Target still busy - clock 8 bits
                    with m.If(bus.rdy):
                        m.d.comb += [
                            bus.w.eq(0),
                            bus.bits.eq(8),
                            bus.ack.eq(1),
                        ]
                with m.Else():
                    m.next = "IN"

            with m.State("IN"):
                with m.If(count_in == 0):
                    m.next = "READY"
                with m.Elif(bus.rdy):
                    m.d.comb += [
                        bus.w.eq(0),
                        bus.bits.eq(8),
                        bus.ack.eq(1),
                    ]
                    m.next = "IN_WRITE"

            with m.State("IN_WRITE"):
                with m.If(bus.rdy & self.in_fifo.writable):
                    m.d.comb += [
                        self.in_fifo.we.eq((op != Operation.COMMAND_DISCARD) &
                                           (op != Operation.COMMAND_POLL_DISCARD)),
                        self.in_fifo.din.eq(bus.di),
                    ]
                    m.d.sync += count_in.eq(count_in-1)
                    m.next = "IN"

            with m.State("DEBUG"):
                with m.If(bus.rdy):
                    m.d.comb += [
                        bus.do.eq(0),
                        bus.w.eq(0),
                        bus.bits.eq(2),
                        bus.ack.eq(1),
                    ]
                    m.next = "READY"

            with m.State("DELAY_H"):
                with m.If(self.out_fifo.readable):
                    m.d.comb += self.out_fifo.re.eq(1),
                    m.d.sync += delay_downcount[8:16].eq(self.out_fifo.dout)
                    m.next = "DELAY_L"

            with m.State("DELAY_L"):
                with m.If(self.out_fifo.readable):
                    m.d.comb += self.out_fifo.re.eq(1),
                    m.d.sync += delay_downcount[0:8].eq(self.out_fifo.dout)
                    m.next = "DELAYING"

            with m.State("DELAYING"):
                with m.If(delay_downcount == 0):
                    m.next = "READY"
                with m.Elif(delay.stb_r & bus.rdy):
                    m.d.sync += delay_downcount.eq(delay_downcount-1)
        return m

class CCDPIInterface:
    # Number of reads ops that are queued up before pulling data from fifo
    READ_BLOCK_SIZE=1024
    # CC8051 uses 32K bank size
    BANK_SIZE=0x8000

    def __init__(self, interface, logger, flash_size):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self.connected = False
        self.chip_id = 0
        self.chip_rev = 0
        self.flash_size = flash_size
        self.device = None
        self.xreg = None

    def _log(self, message, *args):
        self._logger.log(self._level, "CCDPI: " + message, *args)

    async def _send(self, op, out_bytes, num_bytes_in):
        """Send operation code then output bytes to fifo."""
        if not self.connected:
            raise CCDPIError("not connected")
        start_code = (op << 5) + (len(out_bytes) << 2) + num_bytes_in
        await self.lower.write([start_code] + out_bytes)

    async def _flush(self):
        """Flush data down to target."""
        await self.lower.flush()

    async def _recv(self, num_bytes_in):
        """Read back input bytes."""
        if not self.connected:
            raise CCDPIError("not connected")
        return await self.lower.read(num_bytes_in)

    async def _command(self, out_bytes, num_bytes_in, discard=False, defer_read=False):
        """Send a debug command to device."""
        if self.is_extended():
                op = discard and Operation.COMMAND_POLL_DISCARD or Operation.COMMAND_POLL
        else:
                op = discard and Operation.COMMAND_DISCARD or Operation.COMMAND
        await self._send(op, out_bytes, num_bytes_in)
        if not defer_read:
            await self._flush()
            return await self._recv(num_bytes_in)

    async def _delay_us(self, micros):
        # delay clock is *4, and make sure the wait is at least requested time
        delay_count = micros*4+1
        await self._send(Operation.DELAY, [(delay_count >> 8) & 0xff, delay_count & 0xff], 0)

    async def _delay_ms(self, millis):
        while millis > 0:
            msecs = min(10, millis)
            await self._delay_us(msecs * 1000)
            millis -= msecs

    def is_extended(self):
        return self.chip_id in devices_extended

    async def get_chip_id(self):
        id,rev = await self._command([Cmd.GET_CHIP_ID], 2)
        return (id, rev)

    async def get_flash_size(self, default):
        if not self.is_extended():
            return default
        await self.debug_instr16(O.MOV_DPTR_immed, XREGExtended.CHIPINFO0)
        chipinfo0 = await self.debug_instr_a(O.MOVX_A_atDPTR)
        return devices_chipid_flashsize.get((self.chip_id, chipinfo0 >> 4), default)

    async def connect(self):
        """Reset device into debug mode."""
        self.connected = True
        await self.lower.reset()
        # Generate entry signal - two clocks while reset held
        await self._send(Operation.RESET_ON, [], 0)
        await self._delay_us(1)
        await self._send(Operation.DEBUG_ENTRY, [], 0)
        await self._delay_us(1)
        await self._send(Operation.RESET_OFF, [], 0)
        await self.lower.flush()
        # Is there something recognizable attached?
        # NB: It appears that the extended protocol responds to GET_CHIP_ID
        # without requiring a wait, so all cc8051 parts will reply to this
        self.chip_id,self.chip_rev = await self.get_chip_id()
        # Try and read flash size from device
        self.flash_size = await self.get_flash_size(self.flash_size)
        if not self.flash_size:
            raise CCDPIError("flash size must be specified (--flash-size=xxx)")
        self.device = devices.get((self.chip_id, self.flash_size), None)
        if not self.device:
            raise CCDPIError("did not find device: {:02x}:{:02x} {:d}K".format(
                self.chip_id,self.chip_rev, self.flash_size))
        self.xreg = self.device.extended and XREGExtended or XREGBase
        if not await self.get_status() & Status.OSCILLATOR_STABLE:
            raise CCDPIError("oscillator not stable")
        # Leave CPU halted
        await self.halt()

    async def disconnect(self):
        """Reset device into normal operation."""
        await self._send(Operation.RESET_ON, [], 0)
        await self._delay_us(1)
        await self._send(Operation.RESET_OFF, [], 0)
        await self._flush()
        self.connected = False

    async def get_status(self):
        return (await self._command([Cmd.READ_STATUS], 1))[0]

    async def halt(self):
        await self._command([Cmd.HALT], 1)

    async def resume(self):
        await self._command([Cmd.RESUME], 1)

    async def step(self):
        return (await self._command([Cmd.STEP_INSTR], 1))[0]

    async def get_pc(self):
        recv_bytes = await self._command([Cmd.GET_PC], 2)
        return (recv_bytes[0] << 8) + recv_bytes[1]

    async def get_config(self):
        return (await self._command([Cmd.RD_CONFIG], 1))[0]

    async def set_config(self, cfg):
        await self._command([Cmd.WR_CONFIG, cfg], 1)

    async def set_breakpoint(self, bp_number, bank, address, enable=True):
        await self._command([Cmd.SET_HW_BRKPNT,
                             (bp_number << 4)+(0x4 if enable else 0) + bank,
                             (address>>8) & 0xff, address & 0xff], 1)

    async def clear_breakpoint(self, bp):
        await self._command([Cmd.SET_HW_BRKPNT, (bp << 4) + 0x00, 0x00, 0x00], 1)

    async def debug_instr(self, *opcode, discard=True):
        """Execute opcode on target."""
        if not 1 <= len(opcode) <= 3:
            raise CCDPIError("instructions must be 1..3 bytes")
        await self._command([Cmd.DEBUG_INSTR + len(opcode)] + list(opcode), 1, discard=discard, defer_read=True)

    async def debug_instr_a(self, *opcode):
        """Execute opcode on target and return contents of A."""
        if not 1 <= len(opcode) <= 3:
            raise CCDPIError("instructions must be 1..3 bytes")
        return (await self._command([Cmd.DEBUG_INSTR + len(opcode)] + list(opcode), 1))[0]

    async def debug_instr16(self, opcode, immed16):
        """Execute opcode with immed16 on target."""
        return await self.debug_instr(opcode, (immed16 >> 8) &0xff, immed16 & 0xff)

    async def set_pc(self, address):
        await self.debug_instr16(O.LJMP_addr16, address)

    async def read_flash(self, linear_address, count):
        """Read from one bank of CODE address space."""
        if linear_address+count > self.device.flash_size*1024:
            raise CCDPIError("reading beyond end of code")
        if (linear_address // self.BANK_SIZE) != ((linear_address+count-1) // self.BANK_SIZE):
            raise CCDPIError("reading across a bank boundary")
        await self.debug_instr(O.MOV_direct_immed, SFR.MEMCTR, 0x00)
        if self.device.banked:
            # Always read from top code bank
            address = (linear_address % self.BANK_SIZE) + self.BANK_SIZE
            bank = linear_address // self.BANK_SIZE
            await self.debug_instr(O.MOV_direct_immed, SFR.FMAP, bank)
        else:
            address = linear_address
        await self.debug_instr16(O.MOV_DPTR_immed, address)
        # Read in chunk: Send out a burst of read insns, then read back the replies
        recv_bytes = bytearray()
        while count:
            block_size = min(self.READ_BLOCK_SIZE, count)
            count -= block_size
            for _ in range(block_size):
                await self.debug_instr(O.CLR_A)
                await self.debug_instr(O.MOVC_A_atAplusDPTR, discard=False)
                await self.debug_instr(O.INC_DPTR)
            await self._flush()
            recv_bytes += await self._recv(block_size)
        return recv_bytes

    async def read_xdata(self, address, count):
        """Read from XDATA address space."""
        await self.debug_instr16(O.MOV_DPTR_immed, address)
        # Read in chunk - send out a burst of read insns, then read back the replies
        recv_bytes = bytearray()
        while count:
            block_size = min(self.READ_BLOCK_SIZE, count)
            count -= block_size
            for _ in range(block_size):
                await self.debug_instr(O.MOVX_A_atDPTR, discard=False)
                await self.debug_instr(O.INC_DPTR)
            await self._flush()
            recv_bytes += await self._recv(block_size)
        return recv_bytes

    async def write_xdata(self, address, data):
        """Write to XDATA address space."""
        await self.debug_instr16(O.MOV_DPTR_immed, address)
        for byte in data:
            await self.debug_instr(O.MOV_A_immed, byte)
            await self.debug_instr(O.MOVX_atDPTR_A)
            await self.debug_instr(O.INC_DPTR)
        await self._flush()

    async def clock_init(self):
        """Set up high speed clock. """
        await self.debug_instr(O.MOV_direct_immed, SFR.CLKCON, 0x00)
        await self._delay_us(1000)
        await self.debug_instr(O.NOP)
        if not await self.get_status() & Status.OSCILLATOR_STABLE:
            raise CCDPIError("high speed clock not stable")

    async def chip_erase(self):
        await self._command([Cmd.CHIP_ERASE], 1)
        await self._delay_ms(200)
        await self.debug_instr(O.NOP)
        await self._flush()
        if self.device.extended:
            done = not (await self.get_status() & Status.CHIP_ERASE_BUSY)
        else:
            done = (await self.get_status() & Status.CHIP_ERASE_DONE)
        if not done:
            raise CCDPIError("chip erase not done")

    async def erase_flash_page(self, address):
        """Erase one page of flash memory."""
        if (address % self.device.flash_page_size) != 0:
            raise CCDPIError("address is not page aligned")
        word_address = address // self.device.flash_word_size
        # Set up flash controller via XDATA writes
        await self.write_xdata(self.xreg['FADDRL'], [0, (word_address >> 8) & 0xff])
        await self.write_xdata(self.xreg['FCTL'], [0x01]) # ERASE
        await self._delay_ms(30)
        if (await self.read_xdata(self.xreg['FCTL'], 1))[0] & 0x80:
            raise CCDPIError("cannot erase flash page")

    def _pad_to_words(self, chunk):
        """Pads a chunk with 0xFF so that writes can be to byte boundaries."""
        address,data = chunk
        # Word align start and end of data by padding with 0xff
        start_pad = address % self.device.flash_word_size
        if start_pad != 0:
            data = bytes([0xff]*start_pad) + data
            address -= start_pad
        end_pad = len(data) % self.device.flash_word_size
        if end_pad != 0:
            data += bytes([0xff]*(self.device.flash_word_size-end_pad))
        return (address,data)

    async def write_flash(self, address, data):
        """Write a chunk of data to flash memory. """
        address,data = self._pad_to_words((address, data))
        if len(data) == 0:
            return
        if len(data) > self.device.write_block_size:
            raise CCDPIError("Trying to write a block larger than write buffer.")
        # Copy data into SRAM
        await self.write_xdata(self.device.write_xdata_address, data)
        words_per_flash_page = self.device.flash_page_size // self.device.flash_word_size
        word_address = address // self.device.flash_word_size
        word_count = len(data) // self.device.flash_word_size
        # Counters for nested DJNZ loop
        word_count_l = word_count & 0xff
        word_count_h = ((word_count >> 8) & 0xff) + (1 if word_count_l != 0 else 0)
        # Code to run from RAM
        #  Use MPAGE:R0 and MPAGE:R1 to point to FCTL and FWDATA regs in XDATA
        code = [
            O.MOV_direct_immed, SFR.MPAGE, (self.xreg['FCTL'] >> 8) & 0x0ff,
            O.MOV_R0_immed, self.xreg['FCTL'] & 0x0ff,
            O.MOV_R1_immed, self.xreg['FWDATA'] & 0x0ff,
            O.MOV_DPTR_immed, (self.device.write_xdata_address >> 8) & 0xff,
                              self.device.write_xdata_address & 0xff,
            O.MOV_R7_immed, word_count_h,
            O.MOV_R6_immed, word_count_l,
            O.MOV_A_immed, 0x02,
            O.MOVX_atR0_A,                                 # FCTL = WRITE
            O.MOV_R5_immed, self.device.flash_word_size,   # 1$:
            O.MOVX_A_atDPTR,                               # 2$:
            O.INC_DPTR,
            O.MOVX_atR1_A,                                 # FWDATA=A
            O.DJNZ_R5_offset, offset(-5),                  #  -> 2$
            O.MOVX_A_atR0,                                 # 3$:  A = FCTL
            O.JB_bit_offset, SFR.ACC+6, offset(-4),        #  -> 3$
            O.DJNZ_R6_offset, offset(-13),                 #  -> 1$
            O.DJNZ_R7_offset, offset(-15),                 #  -> 1$
            O.HALT
        ]
        # Copy code into SRAM in next page
        await self.write_xdata(self.device.write_xdata_address + self.device.write_block_size, code)
        # Set flash address via XDATA
        await self.write_xdata(self.xreg['FADDRL'], [word_address & 0xff, (word_address >> 8) & 0xff])
        # Allow code to execute from XDATA
        if self.device.extended:
            memctr = 0x08
        elif self.device.banked:
            memctr = 0x40
        else:
            memctr = 0
        await self.debug_instr(O.MOV_direct_immed, SFR.MEMCTR, memctr)
        # Start CPU - then wait for it to halt
        await self.set_pc(self.device.write_code_address + self.device.write_block_size)
        await self.resume()
        #  Worst case across all parts appears to be CC2430 at 27ms
        await self._delay_ms(30)
        if not await self.get_status() & Status.CPU_HALTED:
            raise CCDPIError("flash writing code not finished")

    async def soak_test(self, count):
        """
        Soak test debug communication.
        Repeatedly write a block to XDATA, then read back and check.
        """
        for iteration in range(count):
            write_block = bytes(random.randrange(256) for _ in range(1024))
            await self.connect()
            await self.clock_init()
            await self.write_xdata(self.device.write_xdata_address, write_block)
            read_block = await self.read_xdata(self.device.write_xdata_address, len(write_block))
            if read_block != write_block:
                raise CCDPIError("soak test block %d mismatch: %s %s" %
                                 (iteration, write_block.hex(), read_block.hex()))
            self._log("soak_test: %d", iteration)
            await self.disconnect()
