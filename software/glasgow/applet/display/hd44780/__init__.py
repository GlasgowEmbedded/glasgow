# Ref: https://www.sparkfun.com/datasheets/LCD/HD44780.pdf
# Accession: G00008
# Ref: http://ecee.colorado.edu/~mcclurel/SED1278F_Technical_Manual.pdf
# Accession: G00009
# Ref: https://www.openhacks.com/uploadsproductos/eone-1602a1.pdf
# Accession: G00010
# Note: HD44780's bus is *asynchronous*. Setup/hold timings are referenced
# to E falling edge, and BF/AC can and will change while E is high.
# We make use of it by waiting on BF falling edge when polling the IC.

import math
import asyncio

from amaranth import *
from amaranth.lib import io, cdc, wiring, stream, enum
from amaranth.lib.wiring import In, Out

from glasgow.abstract import AbstractAssembly, GlasgowPin
from glasgow.gateware.ports import PortGroup
from glasgow.support import logging
from glasgow.applet import GlasgowAppletV2


__all__ = ["HD44780Component", "HD44780Interface"]


# FPGA commands
class _Command(enum.IntFlag, shape=8):
    XFER_BIT_DATA = 0b0001
    XFER_BIT_READ = 0b0010
    XFER_BIT_HALF = 0b0100
    XFER_BIT_WAIT = 0b1000


XFER_COMMAND  = 0
XFER_WRITE    = _Command.XFER_BIT_DATA
XFER_POLL     = _Command.XFER_BIT_READ
XFER_READ     = _Command.XFER_BIT_DATA | _Command.XFER_BIT_READ
XFER_INIT     = _Command.XFER_BIT_HALF
XFER_WAIT     = _Command.XFER_BIT_WAIT


class _HD44780Command(enum.IntFlag, shape=8):
    CMD_CLEAR_DISPLAY  = 0b00000001

    CMD_CURSOR_HOME    = 0b00000010

    CMD_ENTRY_MODE     = 0b00000100
    BIT_CURSOR_INC_POS =       0b10
    BIT_DISPLAY_SHIFT  =       0b01

    CMD_DISPLAY_ON_OFF = 0b00001000
    BIT_DISPLAY_ON     =      0b100
    BIT_CURSOR_ON      =      0b010
    BIT_CURSOR_BLINK   =      0b001

    CMD_SHIFT          = 0b00010000
    BIT_SHIFT_DISPLAY  = 0b00001000
    BIT_SHIFT_RIGHT    = 0b00000100

    CMD_FUNCTION_SET   = 0b00100000
    BIT_IFACE_8BIT     =    0b10000
    BIT_DISPLAY_2_LINE =    0b01000
    BIT_FONT_5X10_DOTS =    0b00100

    CMD_CGRAM_ADDRESS  = 0b01000000

    CMD_DDRAM_ADDRESS  = 0b10000000


class HD44780Component(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))

    def __init__(self, *, ports: PortGroup, sys_clk_period):
        self._ports = ports
        self._sys_clk_period = sys_clk_period

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        di = Signal(4)

        m.submodules.rs_buffer = rs_buffer = io.Buffer("o", self._ports.rs)
        m.submodules.rw_buffer = rw_buffer = io.Buffer("o", self._ports.rw)
        m.submodules.e_buffer = e_buffer = io.Buffer("o", self._ports.e)
        m.submodules.d_buffer = d_buffer = io.Buffer("io", self._ports.d)
        m.d.comb += d_buffer.oe.eq(~rw_buffer.o)
        m.submodules += cdc.FFSynchronizer(d_buffer.i, di)

        rx_setup_cyc = math.ceil(60e-9 / self._sys_clk_period)
        e_pulse_cyc  = math.ceil(500e-9 / self._sys_clk_period)
        e_wait_cyc   = math.ceil(700e-9 / self._sys_clk_period)
        cmd_wait_cyc = math.ceil(1.52e-3 / self._sys_clk_period)
        timer        = Signal(range(max([rx_setup_cyc, e_pulse_cyc, e_wait_cyc, cmd_wait_cyc])))

        cmd  = Signal(8)
        rdata = Signal(8)
        wdata = Signal(8)
        msb  = Signal()

        with m.FSM():
            with m.State("IDLE"):
                m.d.sync += e_buffer.o.eq(0)
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    m.d.sync += cmd.eq(self.i_stream.payload)
                    m.next = "COMMAND"

            with m.State("COMMAND"):
                m.d.sync += [
                    msb.eq((cmd & _Command.XFER_BIT_HALF) == 0),
                    rs_buffer.o.eq((cmd & _Command.XFER_BIT_DATA) != 0),
                    rw_buffer.o.eq((cmd & _Command.XFER_BIT_READ) != 0),
                ]
                with m.If(cmd & _Command.XFER_BIT_WAIT):
                    m.d.sync += timer.eq(cmd_wait_cyc)
                    m.next = "WAIT"
                with m.Elif(cmd & _Command.XFER_BIT_READ):
                    m.d.sync += timer.eq(rx_setup_cyc)
                    m.next = "READ-SETUP"
                with m.Else():
                    m.d.comb += self.i_stream.ready.eq(1)
                    with m.If(self.i_stream.valid):
                        m.d.sync += wdata.eq(self.i_stream.payload)
                        m.next = "WRITE"

            with m.State("WRITE"):
                with m.If(timer == 0):
                    m.d.sync += [
                        e_buffer.o.eq(1),
                        d_buffer.o.eq(Mux(msb, wdata[4:], wdata[:4])),
                        timer.eq(e_pulse_cyc),
                    ]
                    m.next = "WRITE-HOLD"
                with m.Else():
                    m.d.sync += timer.eq(timer - 1)

            with m.State("WRITE-HOLD"):
                with m.If(timer == 0):
                    m.d.sync += [
                        e_buffer.o.eq(0),
                        msb.eq(0),
                        timer.eq(e_wait_cyc),
                    ]
                    with m.If(msb):
                        m.next = "WRITE"
                    with m.Else():
                        m.next = "WAIT"
                with m.Else():
                    m.d.sync += timer.eq(timer - 1)

            with m.State("READ-SETUP"):
                with m.If(timer == 0):
                    m.d.sync += [
                        e_buffer.o.eq(1),
                        timer.eq(e_pulse_cyc),
                    ]
                    m.next = "READ"
                with m.Else():
                    m.d.sync += timer.eq(timer - 1)

            with m.State("READ"):
                with m.If(timer == 0):
                    with m.If(((cmd & _Command.XFER_BIT_DATA) == 0) & msb & di[3]):
                        # BF=1, wait until it goes low
                        pass
                    with m.Else():
                        m.d.sync += [
                            e_buffer.o.eq(0),
                            msb.eq(0),
                            timer.eq(e_wait_cyc),
                        ]
                        with m.If(msb):
                            m.d.sync += rdata[4:].eq(di)
                            m.next = "READ-SETUP"
                        with m.Else():
                            m.d.sync += rdata[:4].eq(di)
                            m.next = "READ-PROCESS"
                with m.Else():
                    m.d.sync += timer.eq(timer - 1)

            with m.State("READ-PROCESS"):
                with m.If(cmd & _Command.XFER_BIT_DATA):
                    m.d.comb += [
                        self.o_stream.payload.eq(rdata),
                        self.o_stream.valid.eq(1),
                    ]
                    with m.If(self.o_stream.ready):
                        m.next = "WAIT"
                with m.Else():
                    # done reading status register, ignore it and continue
                    m.next = "WAIT"

            with m.State("WAIT"):
                with m.If(timer == 0):
                    m.next = "IDLE"
                with m.Else():
                    m.d.sync += timer.eq(timer - 1)

        return m


class HD44780Interface:
    _current_entry_mode = _HD44780Command.CMD_ENTRY_MODE
    _current_display_mode = _HD44780Command.CMD_DISPLAY_ON_OFF
    _current_function_mode = _HD44780Command.CMD_FUNCTION_SET

    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 rs: GlasgowPin, rw: GlasgowPin, e: GlasgowPin, d: GlasgowPin):
        self._logger = logger
        self._level = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        ports = assembly.add_port_group(rs=rs, rw=rw, e=e, d=d)
        component = assembly.add_submodule(
            HD44780Component(ports=ports, sys_clk_period=assembly.sys_clk_period))
        self._pipe = assembly.add_inout_pipe(component.o_stream, component.i_stream)

    def _log(self, message, *args):
        self._logger.log(self._level, "HD44780: " + message, *args)

    async def _init(self, command, poll):
        self._log("INIT: %02x", command)
        await self._pipe.send(bytearray([XFER_INIT, command, XFER_POLL if poll else XFER_WAIT]))
        await self._flush()

    async def _cmd(self, command):
        self._log("CMD: %02x", command)
        await self._pipe.send(bytearray([XFER_COMMAND, command, XFER_POLL]))
        await self._flush()

    async def _data(self, data: bytes):
        self._log("DATA: %s", data.hex())
        for byte in data:
            await self._pipe.send(bytearray([XFER_WRITE, byte, XFER_POLL]))
        await self._flush()

    async def _flush(self):
        await self._pipe.flush()

    async def initialize(self):
        """Initialize the display.

        This will set the display to 4-bit mode regardless of the mode it is currently in.
        """
        # HD44780 may be in either 4-bit or 8-bit mode and we don't know which.
        # The following sequence brings it to 4-bit mode regardless of which one it was in.
        await self._init(0x03, poll=False)  # either CMD_FUNCTION_SET|BIT_IFACE_8BIT
                                            # or CMD_CURSOR_HOME
                                            # or the second nibble of an unknown command/data
        await self._init(0x03, poll=False)  # either CMD_FUNCTION_SET|BIT_IFACE_8BIT
                                            # or CMD_CURSOR_HOME
                                            # or the second nibble of CMD_FUNCTION_SET
                                            # (the set bits are ignored)
        await self._init(0x03, poll=False)  # CMD_FUNCTION_SET|BIT_IFACE_8BIT
        await self._init(0x02, poll=True)   # CMD_FUNCTION_SET

    async def clear_display(self):
        """Clear the display."""
        await self._cmd(_HD44780Command.CMD_CLEAR_DISPLAY)

    async def home(self):
        """Set the cursor to the leftmost position on the first line."""
        await self._cmd(_HD44780Command.CMD_CURSOR_HOME)

    async def increment_cursor(self):
        """Set the cursor movement to increment.

        This is the default after the display powers on and has self-initialized.
        """
        self._current_entry_mode |= _HD44780Command.BIT_CURSOR_INC_POS
        await self._cmd(self._current_entry_mode)

    async def decrement_cursor(self):
        """Set the cursor movement to decrement."""
        self._current_entry_mode &= ~_HD44780Command.BIT_CURSOR_INC_POS
        await self._cmd(self._current_entry_mode)

    async def display_shift_on(self):
        """Set the display to shift with every new character."""
        self._current_entry_mode |= _HD44780Command.BIT_DISPLAY_SHIFT
        await self._cmd(self._current_entry_mode)

    async def display_shift_off(self):
        """Set the display to not shift with every new character.

        This is the default after the display powers on and has self-initialized.
        """
        self._current_entry_mode &= ~_HD44780Command.BIT_DISPLAY_SHIFT
        await self._cmd(self._current_entry_mode)

    async def display_on(self):
        """Turn the display on."""
        self._current_display_mode |= _HD44780Command.BIT_DISPLAY_ON
        await self._cmd(self._current_display_mode)

    async def display_off(self):
        """Turn the display off.

        This is the default after the display powers on and has self-initialized.
        """
        self._current_display_mode &= ~_HD44780Command.BIT_DISPLAY_ON
        await self._cmd(self._current_display_mode)

    async def cursor_on(self):
        """Turn the cursor on."""
        self._current_display_mode |= _HD44780Command.BIT_CURSOR_ON
        await self._cmd(self._current_display_mode)

    async def cursor_off(self):
        """Turn the cursor off.

        This is the default after the display powers on and has self-initialized.
        """
        self._current_display_mode &= ~_HD44780Command.BIT_CURSOR_ON
        await self._cmd(self._current_display_mode)

    async def cursor_blink_on(self):
        """Turn cursor blinking on."""
        self._current_display_mode |= _HD44780Command.BIT_CURSOR_BLINK
        await self._cmd(self._current_display_mode)

    async def cursor_blink_off(self):
        """Turn cursor blinking off.

        This is the default after the display powers on and has self-initialized.
        """
        self._current_display_mode &= ~_HD44780Command.BIT_CURSOR_BLINK
        await self._cmd(self._current_display_mode)

    async def shift_display_and_cursor_left(self):
        """Shift the display and cursor one character to the left."""
        command = _HD44780Command.CMD_SHIFT | _HD44780Command.BIT_SHIFT_DISPLAY
        await self._cmd(command)

    async def shift_display_right(self):
        """Shift the display and cursor one character to the right."""
        command = (_HD44780Command.CMD_SHIFT
                   | _HD44780Command.BIT_SHIFT_DISPLAY
                   | _HD44780Command.BIT_SHIFT_RIGHT)
        await self._cmd(command)

    async def shift_cursor_left(self):
        """Shift the cursor one character to the left."""
        command = _HD44780Command.CMD_SHIFT
        await self._cmd(command)

    async def shift_cursor_right(self):
        """Shift the cursor one character to the right."""
        command = _HD44780Command.CMD_SHIFT | _HD44780Command.BIT_SHIFT_RIGHT
        await self._cmd(command)

    async def use_one_display_line(self):
        """Set the number of display lines to 1.

        This is the default after the display powers on and has self-initialized.
        """
        self._current_function_mode &= ~_HD44780Command.BIT_DISPLAY_2_LINE
        await self._cmd(self._current_function_mode)

    async def use_two_display_lines(self):
        """Set the number of display lines to 2."""
        self._current_function_mode |= _HD44780Command.BIT_DISPLAY_2_LINE
        await self._cmd(self._current_function_mode)

    async def use_5x7_font(self):
        """Set the font to 5x7 dots.

        This is the default after the display powers on and has self-initialized.
        """
        self._current_function_mode &= ~_HD44780Command.BIT_FONT_5X10_DOTS
        await self._cmd(self._current_function_mode)

    async def use_5x10_font(self):
        """Set the font to 5x10 dots.

        This setting will only take effect if one display line is selected.
        """
        self._current_function_mode |= _HD44780Command.BIT_FONT_5X10_DOTS
        await self._cmd(self._current_function_mode)

    async def set_cursor_positon(self, *, position: int = 0, line_no: int = 0):
        """Set the cursor position.

        The positon is dependent on the number of lines which have been set.

        For one line a ``position`` greater than 80 characters wraps around
        to the start of the line.

        For two lines a ``position`` greater than 40 characters wraps around
        to the start of the line for each of the lines selected with ``line_no``.
        """
        line_no = min(max(0, line_no), 1)
        command = _HD44780Command.CMD_DDRAM_ADDRESS
        if _HD44780Command.BIT_DISPLAY_2_LINE in self._current_function_mode:
            command |= 0x40 * line_no + (position % 40)
        else:
            command |= position % 80
        await self._cmd(command)

    async def write_bytes(self, msg: bytes):
        """Write raw bytes to the display at the current cursor position."""
        await self._data(msg)

    async def write_text(self, msg: str):
        """Write ASCII text to the display at the current cursor position."""
        await self.write_bytes(msg.encode("ascii"))

    async def define_cg_ram_char(self, offset: int, char_bytes: bytes):
        """Define a custom character in CG RAM.

        For the 5x7 dots font a total of 8 characters at offsets 0-7 can be defined.
        ``char_bytes`` should contain at most 8 bytes. Only the 5 least significant
        bits of each byte are relevant.

        For the 5x10 dots font a total of 4 characters at offsets 0-3 can be defined.
        ``char_bytes`` should contain at most 16 bytes. Only the 5 least significant
        bits of each byte are relevant and only the first 10 bytes will be used.
        """
        if _HD44780Command.BIT_FONT_5X10_DOTS in self._current_function_mode:
            await self._cmd(_HD44780Command.CMD_CGRAM_ADDRESS|((offset & 0x03) << 4))
            await self.write_bytes(char_bytes[:16])
        else:
            await self._cmd(_HD44780Command.CMD_CGRAM_ADDRESS|((offset & 0x07) << 3))
            await self.write_bytes(char_bytes[:8])


class DisplayHD44780Applet(GlasgowAppletV2):
    preview = True
    logger = logging.getLogger(__name__)
    help = "display characters on HD44780-compatible LCDs"
    description = """
    Control HD44780/SED1278/ST7066/KS0066-compatible displays via a 4-bit bus.

    Port pins should be connected to display pins as follows: RS->4, RW->5, E->6,
    D->11,12,13,14.
    """
    # The revA/B level shifters interact very badly with the input cascade of most such displays,
    # causing severe glitching.
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "rs", default=True)
        access.add_pins_argument(parser, "rw", default=True)
        access.add_pins_argument(parser, "e", default=True)
        access.add_pins_argument(parser, "d", width=4, default=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.hd44780_interface = HD44780Interface(self.logger, self.assembly,
                                                      rs=args.rs, rw=args.rw, e=args.e, d=args.d)

    async def setup(self, args):
        await self.hd44780_interface.initialize()

    async def run(self, args):
        await self.hd44780_interface.increment_cursor()
        await self.hd44780_interface.display_on()
        await self.hd44780_interface.cursor_on()
        await self.hd44780_interface.cursor_blink_on()
        await self.hd44780_interface.use_two_display_lines()
        await self.hd44780_interface.clear_display()

        # display available characters
        for i in range(16):
            # skip over addresses containing custom or no characters
            if i in [0,1,8,9]:
                continue
            await self.hd44780_interface.home()
            await self.hd44780_interface.write_bytes(bytes([16 * i + j for j in range(8)]))
            await self.hd44780_interface.set_cursor_positon(line_no=1)
            await self.hd44780_interface.write_bytes(bytes([16 * i + j + 8 for j in range(8)]))
            await asyncio.sleep(1)

        # display custom characters
        await self.hd44780_interface.define_cg_ram_char(0, b"\xff\x0a\x0e\x04\x0a\x0e\xff\x00")
        await self.hd44780_interface.define_cg_ram_char(1, b"\x00\x0a\x00\x04\x11\x0e\x00\x00")
        await self.hd44780_interface.define_cg_ram_char(2, b"\x04\x0a\x11\x04\x0a\x11\x00\x00")
        await self.hd44780_interface.define_cg_ram_char(3, b"\x15\x0a\x15\x0a\x15\x0a\x15\x00")
        await self.hd44780_interface.define_cg_ram_char(4, b"\x00\x00\x04\x02\x0e\x00\x00\x00")
        await self.hd44780_interface.define_cg_ram_char(5, b"\x0e\xff\x15\xff\xff\xff\x15\x00")
        await self.hd44780_interface.define_cg_ram_char(6, b"\x04\x0e\xff\x15\x1b\x1b\x00\x00")
        await self.hd44780_interface.define_cg_ram_char(7, b"\x04\x0e\x0e\x0e\xff\x04\x00\x00")
        await self.hd44780_interface.clear_display()
        await self.hd44780_interface.home()
        await self.hd44780_interface.write_bytes(bytes(list(range(8))))
        await asyncio.sleep(2)

        # display short animation with custom characters
        await self.hd44780_interface.define_cg_ram_char(0, b"\xff\x0e\x0e\x04\x0a\x0a\xff\x00")
        await self.hd44780_interface.define_cg_ram_char(1, b"\xff\x0a\x0e\x04\x0a\x0e\xff\x00")
        await self.hd44780_interface.define_cg_ram_char(2, b"\xff\x0a\x0a\x04\x0e\x0e\xff\x00")
        await self.hd44780_interface.cursor_off()
        await self.hd44780_interface.cursor_blink_off()
        await self.hd44780_interface.clear_display()
        await self.hd44780_interface.set_cursor_positon(position=2)
        for _ in range(5):
            for j in range(3):
                await self.hd44780_interface.write_bytes(bytes([j]))
                await self.hd44780_interface.shift_cursor_left()
                await asyncio.sleep(0.6)
        await self.hd44780_interface.cursor_on()
        await self.hd44780_interface.cursor_blink_on()

        # display Hello Wörld
        await self.hd44780_interface.clear_display()
        await self.hd44780_interface.home()
        await self.hd44780_interface.write_text("Hello")
        await self.hd44780_interface.set_cursor_positon(position=2, line_no=1)
        await self.hd44780_interface.write_bytes(b"W\xefrld")
        await asyncio.sleep(1)

        # display current time and date
        from datetime import datetime
        while True:
            await asyncio.sleep(1)
            await self.hd44780_interface.home()
            await self.hd44780_interface.write_text(datetime.now().strftime("%H:%M:%S"))
            await self.hd44780_interface.set_cursor_positon(line_no=1)
            await self.hd44780_interface.write_text(datetime.now().strftime("%y-%m-%d"))

    @classmethod
    def tests(cls):
        from . import test
        return test.DisplayHD44780AppletTestCase
