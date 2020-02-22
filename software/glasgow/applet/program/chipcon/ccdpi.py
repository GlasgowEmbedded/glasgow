# Chipcon Debug and Programming Interface
#
# Supports: CC1110, CC1111, CC2510, CC2511, CC2430, CC2431 up to ...F32 sizes.
#
# From: "CC1110/ CC2430/ CC2510 Debug and Programming Interface Specification Rev. 1.2"
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

class CCDPIError(GlasgowAppletError):
    pass

class CCDPIBus(Elaboratable):
    """Bus interface - byte<->serial."""

    def __init__(self, pads, period_cyc):
        self.pads = pads
        self.period_cyc = period_cyc
        self.di  = Signal(8)
        self.do  = Signal(8)
        self.bits = Signal(range(8))
        self.w   = Signal()
        self.ack = Signal()
        self.rdy = Signal()
        self.reset = Signal()

    def elaborate(self, platform):
        m = Module()
        m.submodules.period = period = ClockGen(self.period_cyc)

        dclk = Signal()
        oe   = Signal()
        o    = Signal()
        i    = Signal()
        m.d.comb += [
            self.pads.dclk_t.oe.eq(1),
            self.pads.dclk_t.o.eq(dclk),
            self.pads.ddat_t.oe.eq(oe),
            self.pads.ddat_t.o.eq(o),
            i.eq(self.pads.ddat_t.i),
            self.pads.resetn_t.oe.eq(1),
            self.pads.resetn_t.o.eq(~self.reset),
        ]

        d   = Signal(8)
        cnt = Signal(range(8))
        m.d.comb += self.di.eq(d)
        with m.FSM():
            with m.State("READY"):
                m.d.comb += self.rdy.eq(1),
                with m.If(self.ack):
                    m.d.sync += cnt.eq(self.bits)
                    with m.If(self.w):
                        m.d.sync += d.eq(self.do)
                        m.d.sync += oe.eq(1),
                        m.next = "WRITE_RISE"
                    with m.Else():
                        m.d.sync += oe.eq(0),
                        m.next = "READ_RISE"
            with m.State("WRITE_RISE"):
                with m.If(period.stb_r):
                    m.d.sync += [
                        o.eq(d[-1]),
                        dclk.eq(1),
                        cnt.eq(cnt-1),
                    ]
                    m.next = "WRITE_FALL"
            with m.State("WRITE_FALL"):
                with m.If(period.stb_f):
                    m.d.sync += [
                        d[1:].eq(d),
                        dclk.eq(0),
                    ]
                    with m.If(cnt == 0):
                        m.d.sync += oe.eq(0)
                        m.next = "WRITE_DONE"
                    with m.Else():
                        m.next = "WRITE_RISE"
            with m.State("WRITE_DONE"):
                with m.If(period.stb_r):
                        m.next = "READY"
            with m.State("READ_RISE"):
                with m.If(period.stb_r):
                    m.d.sync += [
                        dclk.eq(1),
                        cnt.eq(cnt-1),
                    ]
                    m.next = "READ_FALL"
            with m.State("READ_FALL"):
                with m.If(period.stb_f):
                    m.d.sync += [
                        d.eq(Cat(i, d[0:-1])),
                        dclk.eq(0),
                    ]
                    with m.If(cnt == 0):
                        m.next = "READY"
                    with m.Else():
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

class Operation(IntEnum):
    COMMAND         = 0
    COMMAND_DISCARD = 1
    RESET_ON        = 2
    RESET_OFF       = 3
    DEBUG_ENTRY     = 4
    DELAY           = 5

class CCDPISubtarget(Elaboratable):
    def __init__(self, pads, out_fifo, in_fifo, period_cyc, delay_cyc):
        self.pads = pads
        self.out_fifo = out_fifo
        self.in_fifo = in_fifo
        self.period_cyc = period_cyc
        self.delay_cyc = delay_cyc

    def elaborate(self, platform):
        m = Module()
        m.submodules.bus = bus = CCDPIBus(self.pads, self.period_cyc)
        m.submodules.delay = delay = ClockGen(self.delay_cyc)

        op = Signal(3)
        count_out = Signal(3)
        count_in = Signal(2)

        discard = Signal()
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
                    with m.Case(Operation.COMMAND):
                        m.d.sync += discard.eq(0)
                        m.next = "OUT"
                    with m.Case(Operation.COMMAND_DISCARD):
                        m.d.sync += discard.eq(1)
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
                    m.next = "IN"
                with m.Elif(bus.rdy & self.out_fifo.readable):
                    m.d.comb += [
                        self.out_fifo.re.eq(1),
                        bus.do.eq(self.out_fifo.dout),
                        bus.w.eq(1),
                        bus.bits.eq(8),
                        bus.ack.eq(1),
                    ]
                    m.d.sync += count_out.eq(count_out-1)
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
                        self.in_fifo.we.eq(~discard),
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
    # XDATA address for block to be written to flash
    WRITE_DATA_ADDRESS=0xf000

    def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self.connected = False
        self.chip_id = 0
        self.chip_rev = 0

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

    async def _send_recv(self, op, out_bytes, num_bytes_in):
        await self._send(op, out_bytes, num_bytes_in)
        await self._flush()
        return await self._recv(num_bytes_in)

    async def _delay_us(self, micros):
        # delay clock is *4, and make sure we wait at least requested time
        delay_count = micros*4+1
        await self._send(Operation.DELAY, [(delay_count >> 8) & 0xff, delay_count & 0xff], 0)

    async def _delay_ms(self, millis):
        while millis > 0:
            msecs = min(10, millis)
            await self._delay_us(msecs * 1000)
            millis -= msecs

    async def connect(self):
        """Reset device into debug mode."""
        self.connected = True
        await self.lower.reset()
        # Generate entry signal - two clocks while reset
        await self._send(Operation.RESET_ON, [], 0)
        await self._delay_us(1)
        await self._send(Operation.DEBUG_ENTRY, [], 0)
        await self._delay_us(1)
        await self._send(Operation.RESET_OFF, [], 0)
        await self.lower.flush()
        # Is there something recognizable attached?
        self.chip_id,self.chip_rev = await self.get_chip_id()
        self.device = devices.get(self.chip_id, None)
        if not self.device:
            raise CCDPIError("Did not find device")
        if not await self.get_status() & Status.OSCILLATOR_STABLE:
            raise CCDPIError("Oscillator not stable")
        await self.halt()

    async def disconnect(self):
        """Reset device into normal operation."""
        await self._send(Operation.RESET_ON, [], 0)
        await self._delay_us(1)
        await self._send(Operation.RESET_OFF, [], 0)
        await self._flush()
        self.connected = False

    async def get_chip_id(self):
        id,rev = await self._send_recv(Operation.COMMAND, [Cmd.GET_CHIP_ID], 2)
        return (id, rev)

    async def get_status(self):
        return (await self._send_recv(Operation.COMMAND, [Cmd.READ_STATUS], 1))[0]

    async def halt(self):
        await self._send_recv(Operation.COMMAND, [Cmd.HALT], 1)

    async def resume(self):
        await self._send_recv(Operation.COMMAND, [Cmd.RESUME], 1)

    async def step(self):
        return (await self._send_recv(Operation.COMMAND, [Cmd.STEP_INSTR], 1))[0]

    async def get_pc(self):
        recv_bytes = await self._send_recv(Operation.COMMAND, [Cmd.GET_PC], 2)
        return (recv_bytes[0] << 8) + recv_bytes[1]

    async def get_config(self):
        return (await self._send_recv(Operation.COMMAND, [Cmd.RD_CONFIG], 1))[0]

    async def set_config(self, cfg):
        await self._send_recv(Operation.COMMAND, [Cmd.WR_CONFIG, cfg], 1)

    async def set_breakpoint(self, bp_number, bank, address, enable=True):
        await self._send_recv(Operation.COMMAND, [Cmd.SET_HW_BRKPNT,
                                                  (bp_number << 4)+(0x4 if enable else 0) + bank,
                                                  (address>>8) & 0xff, address & 0xff], 1)

    async def clear_breakpoint(self, bp):
        await self._send_recv(Operation.COMMAND, [Cmd.SET_HW_BRKPNT, (bp << 4) + 0x00, 0x00, 0x00], 1)

    async def debug_instr(self, *args, discard=True):
        if not 1 <= len(args) <= 3:
            raise CCDPIError("Instructions must be 1..3 bytes")
        target_op = Operation.COMMAND_DISCARD if discard else Operation.COMMAND
        await self._send(target_op, [Cmd.DEBUG_INSTR + len(args)] + list(args), 1)

    async def debug_instr_a(self, *args):
        if not 1 <= len(args) <= 3:
            raise CCDPIError("Instructions must be 1..3 bytes")
        return (await self._send_recv(Operation.COMMAND, [Cmd.DEBUG_INSTR + len(args)] + list(args), 1))[0]

    async def set_pc(self, address):
        await self.debug_instr(0x02, (address >> 8) & 0xff, address & 0xff)     # LJMP address

    async def read_code(self, linear_address, count):
        """Read from CODE address space."""
        if (linear_address // 0x8000) != ((linear_address+count-1) // 0x8000):
            raise CCDPIError("reading across a bank boundary")
        if linear_address < 0x8000:
            bank = 0
            address = linear_address
        else:
            # CC2430 banking
            bank = linear_address // 0x8000
            address = (linear_address % 0x8000) + 0x8000
        await self.debug_instr(0x75, 0xC7, (bank * 16) + 1)                     # MOV MEMCTR, (bank * 16) + 1
        await self.debug_instr(0x90, (address >> 8) & 0xff, address & 0xff)     # MOV DPTR, address
        # Read in chunk - send out a burst of read insns, then read back the replies
        recv_bytes = bytearray()
        while count:
            block_size = min(self.READ_BLOCK_SIZE, count)
            count -= block_size
            for _ in range(block_size):
                await self.debug_instr(0xE4)                                    #   CLR A
                await self.debug_instr(0x93, discard=False)                     #   MOVC A, @A+DPTR
                await self.debug_instr(0xA3)                                    #   INC DPTR
            await self._flush()
            recv_bytes += await self._recv(block_size)
        return recv_bytes

    async def read_xdata(self, address, count):
        """Read from XDATA address space."""
        await self.debug_instr(0x90, (address >> 8) & 0xff, address & 0xff)     # MOV DPTR, address
        # Read in chunk - send out a burst of read insns, then read back the replies
        recv_bytes = bytearray()
        while count:
            block_size = min(self.READ_BLOCK_SIZE, count)
            count -= block_size
            for _ in range(block_size):
                await self.debug_instr(0xE0, discard=False)                     #   MOVC A, @A+DPTR
                await self.debug_instr(0xA3)                                    #   INC DPTR
            await self._flush()
            recv_bytes += await self._recv(block_size)
        return recv_bytes

    async def write_xdata(self, address, data):
        """Write to XDATA address space."""
        await self.debug_instr(0x90, (address >> 8) & 0xff, address & 0xff)     # MOV DPTR, address
        for byte in data:
            await self.debug_instr(0x74, byte)                                  #   MOV A,#imm8
            await self.debug_instr(0xF0)                                        #   MOV @DPTR,A
            await self.debug_instr(0xA3)                                        #   INC DPTR
        await self._flush()

    async def clock_init(self):
        """Set up high speed clock (24Mhz Xtal or 12Mhz internal RC). """
        await self.debug_instr(0x75, 0xC6, 0x00)                                # MOV CLKCON,#imm8
        await self._delay_us(3000)
        if not await self.debug_instr_a(0xE5, 0xBE) & 0x40:                     #   MOV A, SLEEP
            raise CCDPIError("High speed clock not stable")

    async def chip_erase(self):
        await self._send_recv(Operation.COMMAND, [Cmd.CHIP_ERASE], 1)
        await self._delay_ms(200)
        await self.debug_instr(0x00)                                            # NOP
        await self._flush()
        if not (await self.get_status() & Status.CHIP_ERASE_DONE):
            raise CCDPIError("Chip erase not done")

    async def erase_flash_page(self, address):
        """Erase one page of flash memory."""
        if (address % self.device.flash_page_size) != 0:
            raise CCDPIError("Address is not page aligned")
        word_address = address // self.device.flash_word_size
        await self.debug_instr(0x75, 0xAD, (word_address >> 8) & 0x7f)          # MOV FADDRH, #imm8
        await self.debug_instr(0x75, 0xAC, 0)                                   # MOV FADDRH, #0
        await self.debug_instr(0x75, 0xAE, 0x01)                                # MOV FLC, #01h ; ERASE
        await self._delay_ms(20)
        if (await self.debug_instr_a(0xE5, 0xAE)) & 0x80:                       # MOV A, FLC
            raise CCDPIError("Cannot erase flash page")

    async def write_flash(self, address, data):
        """Write up to a page of data to flash memory.

        Pads data with 0xFF so that writes can be to byte boundaries.
        """
        # Word align start and end of data by padding with 0xff
        start_pad = address % self.device.flash_word_size
        if start_pad != 0:
            data = bytes([0xff]*start_pad) + data
            address -= start_pad
        end_pad = len(data) % self.device.flash_word_size
        if end_pad != 0:
            data += bytes([0xff]*(self.device.flash_word_size-end_pad))
        if len(data) > self.device.write_block_size:
            raise CCDPIError("Trying to write a block larger than write buffer.")
        if not data:
            return
        # Copy data into SRAM
        await self.write_xdata(self.WRITE_DATA_ADDRESS, data)
        words_per_flash_page = self.device.flash_page_size // self.device.flash_word_size
        word_address = address // self.device.flash_word_size
        word_count = len(data) // self.device.flash_word_size
        # Counters for nested DJNZ loop
        word_count_l = word_count & 0xff
        word_count_h = ((word_count >> 8) & 0xff) + (1 if word_count_l != 0 else 0)
        # Code to run from RAM
        code = [
            0x75, 0xAD, (word_address >> 8) & 0x7f,                         #    MOV FADDRH, #imm8
            0x75, 0xAC, word_address & 0xff,                                #    MOV FADDRL, #imm8
            0x90, (self.WRITE_DATA_ADDRESS >> 8) & 0xff,
                   self.WRITE_DATA_ADDRESS & 0xff,                          #    MOV DPTR, #imm16
            0x7F, word_count_h,                                             #    MOV R7, #imm8
            0x7E, word_count_l,                                             #    MOV R6, #imm8
            0x75, 0xAE, 0x02,                                               #    MOV FLC, #02H ; WRITE
            0x7D, self.device.flash_word_size,                              # 1$: MOV R5, #imm8
            0xE0,                                                           # 2$:  MOVX A, @DPTR
            0xA3,                                                           #      INC DPTR
            0xF5, 0xAF,                                                     #      MOV FWDATA, A
            0xDD, 0xFA,                                                     #      DJNZ R5, 2$
            0xE5, 0xAE,                                                     # 3$:   MOV A, FLC
            0x20, 0XE6, 0xFB,                                               #       JB ACC_SWBSY, 3$
            0xDE, 0xF1,                                                     #     DJNZ R6, 1$
            0xDF, 0xEF,                                                     #    DJNZ R7, 1$
            0xA5                                                            #    HALT
        ]
        # Copy code into SRAM in next page
        code_address = self.WRITE_DATA_ADDRESS + self.device.write_block_size
        await self.write_xdata(code_address, code)
        # Start CPU - then wait for it to halt
        await self.set_pc(code_address)
        await self.resume()
        await self._delay_us(21 * word_count)
        if not await self.get_status() & Status.CPU_HALTED:
            raise CCDPIError("Flash code not finished")

    async def soak_test(self, count):
        """
        Sock test debug communication.
        Repeatedly write a block to SRAM, then read back and check.
        """
        for iteration in range(count):
            write_block = bytes(random.randrange(256) for _ in range(1024))
            await self.connect()
            await self.clock_init()
            await self.write_xdata(self.WRITE_DATA_ADDRESS, write_block)
            read_block = await self.read_xdata(self.WRITE_DATA_ADDRESS, len(write_block))
            if read_block != write_block:
                raise CCDPIError("soak test block %d mismatch: %s %s" % (iteration, write_block.hex(), read_block.hex()))
            self._log("soak_test: %d", iteration)
            await self.disconnect()
