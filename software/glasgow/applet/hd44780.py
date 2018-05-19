# Reference: https://www.sparkfun.com/datasheets/LCD/HD44780.pdf
# Reference: http://ecee.colorado.edu/~mcclurel/SED1278F_Technical_Manual.pdf
# Reference: https://www.openhacks.com/uploadsproductos/eone-1602a1.pdf
# Note: the timings here are *absurdly* conservative. The display I have
# (which may or may not actually be the original HD44780) doesn't work
# with anything smaller. This needs investigation.

import time
import math
import argparse
from migen import *
from migen.genlib.fsm import *
from migen.genlib.cdc import MultiReg

from . import GlasgowApplet


# FPGA commands
XFER_BIT_DATA = 0b0001
XFER_BIT_READ = 0b0010
XFER_BIT_HALF = 0b0100
XFER_BIT_WAIT = 0b1000

XFER_COMMAND  = 0
XFER_POLL     = XFER_BIT_READ
XFER_WRITE    = XFER_BIT_DATA
XFER_READ     = XFER_BIT_DATA|XFER_BIT_READ
XFER_INIT     = XFER_BIT_HALF
XFER_WAIT     = XFER_BIT_WAIT

# HD44780 commands
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
BIT_IFACE_HALF     =    0b10000
BIT_DISPLAY_2_LINE =    0b01000
BIT_FONT_5X10_DOTS =    0b00100

CMD_CGRAM_ADDRESS  = 0b01000000

CMD_DDRAM_ADDRESS  = 0b10000000


class HD44780Subtarget(Module):
    def __init__(self, io_port, out_fifo, in_fifo):
        rs = io_port[0]
        rw = io_port[1]
        e  = io_port[2]
        d  = io_port[3:7]
        di = Signal(4)
        self.comb += [
            rs.oe.eq(1),
            rw.oe.eq(1),
            e.oe.eq(1),
            d.oe.eq(~rw.o),
        ]
        self.specials += [
            # The data bus is *asynchronous*. The D setup time *is* referenced
            # to the E falling edge, but BF (D8) may go down at any time, and
            # AC (D7:0) gets updated some microseconds after BF goes down. Sigh.
            MultiReg(d.i, di)
        ]

        rx_setup_cyc = math.ceil(1e-6 * 30e6)
        e_pulse_cyc  = math.ceil(40e-6 * 30e6)
        e_wait_cyc   = math.ceil(40e-6 * 30e6)
        cmd_wait_cyc = math.ceil(1.52e-3 * 30e6)
        timer        = Signal(max=cmd_wait_cyc)

        cmd  = Signal(2)
        data = Signal(8)
        msb  = Signal()

        self.submodules.fsm = FSM(reset_state="IDLE")
        self.fsm.act("IDLE",
            NextValue(e.o, 0),
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(cmd, out_fifo.dout),
                NextState("COMMAND")
            )
        )
        self.fsm.act("COMMAND",
            If(cmd & XFER_BIT_WAIT,
                NextValue(timer, cmd_wait_cyc),
                NextState("WAIT")
            ).Else(
                NextValue(msb,  (cmd & XFER_BIT_HALF) == 0),
                NextValue(rs.o, (cmd & XFER_BIT_DATA) != 0),
                NextValue(rw.o, (cmd & XFER_BIT_READ) != 0),
                NextValue(timer, rx_setup_cyc),
                If(cmd & XFER_BIT_READ,
                    NextState("READ-SETUP")
                ).Elif(out_fifo.readable,
                    out_fifo.re.eq(1),
                    NextValue(data, out_fifo.dout),
                    NextState("WRITE"),
                )
            )
        )
        self.fsm.act("WRITE",
            If(timer == 0,
                NextValue(e.o, 1),
                If(msb,
                    NextValue(d.o, data[4:])
                ).Else(
                    NextValue(d.o, data[:4])
                ),
                NextValue(timer, e_pulse_cyc),
                NextState("WRITE-HOLD")
            ).Else(
                NextValue(timer, timer - 1)
            )
        )
        self.fsm.act("WRITE-HOLD",
            If(timer == 0,
                NextValue(e.o, 0),
                NextValue(msb, ~msb),
                NextValue(timer, e_wait_cyc),
                If(msb,
                    NextState("WRITE")
                ).Else(
                    NextState("WAIT")
                )
            ).Else(
                NextValue(timer, timer - 1)
            )
        )
        self.fsm.act("READ-SETUP",
            If(timer == 0,
                NextValue(e.o, 1),
                NextValue(timer, e_pulse_cyc),
                NextState("READ")
            ).Else(
                NextValue(timer, timer - 1)
            )
        )
        self.fsm.act("READ",
            If(timer == 0,
                NextValue(e.o, 0),
                NextValue(msb, ~msb),
                NextValue(timer, e_wait_cyc),
                If(msb,
                    NextValue(data[4:], di),
                    NextState("READ-SETUP")
                ).Else(
                    NextValue(data[:4], di),
                    NextState("READ-HANDLE")
                ),
            ).Else(
                NextValue(timer, timer - 1)
            )
        )
        self.fsm.act("READ-HANDLE",
            If(rs.o,
                in_fifo.din.eq(data),
                in_fifo.we.eq(1),
                NextState("WAIT")
            ).Else(
                If(data[7],
                    NextState("READ-SETUP")
                ).Else(
                    NextState("WAIT")
                )
            )
        )
        self.fsm.act("WAIT",
            If(timer == 0,
                NextState("IDLE"),
            ).Else(
                NextValue(timer, timer - 1)
            )
        )


class HD44780Applet(GlasgowApplet, name="hd44780"):
    help = "control HD44780-compatible displays"
    description = """
    Control HD44780-compatible displays via a 4-bit bus.

    Port pins are configured as: 0=RS(4), 1=R/W(5), 2=E(6), 3=D4(11),
    4=D5(12), 5=D6(13), 6=D7(14).
    Port voltage is set to 5.0 V.
    """

    def __init__(self, spec):
        self.spec = spec

    @staticmethod
    def add_arguments(parser):
        parser.add_argument(
            "--reset", default=False, action="store_true",
            help="power-cycle the port on startup")

    def build(self, target):
        target.submodules += HD44780Subtarget(
            io_port=target.get_io_port(self.spec),
            out_fifo=target.get_out_fifo(self.spec),
            in_fifo=target.get_in_fifo(self.spec),
        )

    def run(self, device, args):
        if args.reset:
            device.set_voltage(self.spec, 0.0)
            time.sleep(0.3)
        device.set_voltage(self.spec, 5.0)
        time.sleep(0.040) # wait 40ms after reset

        port = device.get_port(self.spec)

        def init(command, poll=False):
            port.write([XFER_INIT, command, XFER_POLL if poll else XFER_WAIT])

        def cmd(command):
            port.write([XFER_COMMAND, command, XFER_POLL])

        def data(bytes):
            for byte in bytes:
                port.write([XFER_WRITE, byte, XFER_POLL])

        init(0x03)
        init(0x03)
        init(0x03)
        init(0x02, poll=True)
        cmd(CMD_FUNCTION_SET|BIT_DISPLAY_2_LINE)
        cmd(CMD_ENTRY_MODE|BIT_CURSOR_INC_POS)
        cmd(CMD_DISPLAY_ON_OFF|BIT_DISPLAY_ON|BIT_CURSOR_BLINK)
        cmd(CMD_CLEAR_DISPLAY)
        data(b"Hello, world!")
        port.flush()

        from datetime import datetime
        while True:
            time.sleep(1)
            cmd(CMD_CLEAR_DISPLAY)
            cmd(CMD_DDRAM_ADDRESS|0x04)
            data(datetime.now().strftime("%H:%M:%S\x00").encode("ascii"))
            cmd(CMD_DDRAM_ADDRESS|0x43)
            data(datetime.now().strftime("%Y-%m-%d\x00").encode("ascii"))
            port.flush()
