# Ref: https://www.sparkfun.com/datasheets/LCD/HD44780.pdf
# Accession: G00008
# Ref: http://ecee.colorado.edu/~mcclurel/SED1278F_Technical_Manual.pdf
# Accession: G00009
# Ref: https://www.openhacks.com/uploadsproductos/eone-1602a1.pdf
# Accession: G00010
# Note: HD44780's bus is *asynchronous*. Setup/hold timings are referenced
# to E falling edge, and BF/AC can and will change while E is high.
# We make use of it by waiting on BF falling edge when polling the IC.

import time
import math
import argparse
import logging
import asyncio
from nmigen.compat import *
from nmigen.compat.genlib.cdc import MultiReg

from ... import *


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
BIT_IFACE_8BIT     =    0b10000
BIT_DISPLAY_2_LINE =    0b01000
BIT_FONT_5X10_DOTS =    0b00100

CMD_CGRAM_ADDRESS  = 0b01000000

CMD_DDRAM_ADDRESS  = 0b10000000


class HD44780Subtarget(Module):
    def __init__(self, pads, out_fifo, in_fifo, sys_clk_freq):
        di = Signal(4)
        self.comb += [
            pads.rs_t.oe.eq(1),
            pads.rw_t.oe.eq(1),
            pads.e_t.oe.eq(1),
            pads.d_t.oe.eq(~pads.rw_t.o),
        ]
        self.specials += [
            MultiReg(pads.d_t.i, di)
        ]

        rx_setup_cyc = math.ceil(60e-9 * sys_clk_freq)
        e_pulse_cyc  = math.ceil(500e-9 * sys_clk_freq)
        e_wait_cyc   = math.ceil(700e-9 * sys_clk_freq)
        cmd_wait_cyc = math.ceil(1.52e-3 * sys_clk_freq)
        timer        = Signal(max=max([rx_setup_cyc, e_pulse_cyc, e_wait_cyc, cmd_wait_cyc]))

        cmd  = Signal(8)
        data = Signal(8)
        msb  = Signal()

        self.submodules.fsm = FSM(reset_state="IDLE")
        self.fsm.act("IDLE",
            NextValue(pads.e_t.o, 0),
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(cmd, out_fifo.dout),
                NextState("COMMAND")
            )
        )
        self.fsm.act("COMMAND",
            NextValue(msb, (cmd & XFER_BIT_HALF) == 0),
            NextValue(pads.rs_t.o, (cmd & XFER_BIT_DATA) != 0),
            NextValue(pads.rw_t.o, (cmd & XFER_BIT_READ) != 0),
            If(cmd & XFER_BIT_WAIT,
                NextValue(timer, cmd_wait_cyc),
                NextState("WAIT")
            ).Elif(cmd & XFER_BIT_READ,
                NextValue(timer, rx_setup_cyc),
                NextState("READ-SETUP")
            ).Elif(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(data, out_fifo.dout),
                NextState("WRITE"),
            )
        )
        self.fsm.act("WRITE",
            If(timer == 0,
                NextValue(pads.e_t.o, 1),
                If(msb,
                    NextValue(pads.d_t.o, data[4:])
                ).Else(
                    NextValue(pads.d_t.o, data[:4])
                ),
                NextValue(timer, e_pulse_cyc),
                NextState("WRITE-HOLD")
            ).Else(
                NextValue(timer, timer - 1)
            )
        )
        self.fsm.act("WRITE-HOLD",
            If(timer == 0,
                NextValue(pads.e_t.o, 0),
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
                NextValue(pads.e_t.o, 1),
                NextValue(timer, e_pulse_cyc),
                NextState("READ")
            ).Else(
                NextValue(timer, timer - 1)
            )
        )
        self.fsm.act("READ",
            If(timer == 0,
                If(~(cmd & XFER_BIT_DATA) & msb & di[3],
                    # BF=1, wait until it goes low
                ).Else(
                    NextValue(pads.e_t.o, 0),
                    NextValue(msb, ~msb),
                    NextValue(timer, e_wait_cyc),
                    If(msb,
                        NextValue(data[4:], di),
                        NextState("READ-SETUP")
                    ).Else(
                        NextValue(data[:4], di),
                        NextState("READ-PROCESS")
                    )
                )
            ).Else(
                NextValue(timer, timer - 1)
            )
        )
        self.fsm.act("READ-PROCESS",
            If(cmd & XFER_BIT_DATA,
                If(in_fifo.writable,
                    in_fifo.din.eq(data),
                    in_fifo.we.eq(1),
                    NextState("WAIT")
                )
            ).Else(
                # done reading status register, ignore it and continue
                NextState("WAIT")
            )
        )
        self.fsm.act("WAIT",
            If(timer == 0,
                NextState("IDLE"),
            ).Else(
                NextValue(timer, timer - 1)
            )
        )


class DisplayHD44780Applet(GlasgowApplet, name="display-hd44780"):
    preview = True
    logger = logging.getLogger(__name__)
    help = "display characters on HD44780-compatible LCDs"
    description = """
    Control HD44780/SED1278/ST7066/KS0066-compatible displays via a 4-bit bus.

    Port pins should be connected to display pins as follows: RS->4, RW->5, E->6,
    D->11,12,13,14. Port voltage is set to 5.0 V.
    """
    # The revA/B level shifters interact very badly with the input cascade of most such displays,
    # causing severe glitching.
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_build_arguments(parser)
        access.add_pin_argument(parser, "rs", default=True)
        access.add_pin_argument(parser, "rw", default=True)
        access.add_pin_argument(parser, "e", default=True)
        access.add_pin_set_argument(parser, "d", width=4, default=True)

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(HD44780Subtarget(
            pads=iface.get_pads(args, pins=("rs", "rw", "e"), pin_sets=("d",)),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(),
            sys_clk_freq=target.sys_clk_freq,
        ))

    @classmethod
    def add_run_arguments(cls, parser, access):
        parser.add_argument(
            "--reset", default=False, action="store_true",
            help="power-cycle the port on startup")

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args=None)

        if args.reset:
            await device.set_voltage(args.port_spec, 0.0)
            await asyncio.sleep(0.3)
        await device.set_voltage(args.port_spec, 5.0)
        await asyncio.sleep(0.040) # wait 40ms after reset

        # TODO: abstract this away into a HD44780Interface
        async def init(command, poll):
            await iface.write([XFER_INIT, command, XFER_POLL if poll else XFER_WAIT])

        async def cmd(command):
            await iface.write([XFER_COMMAND, command, XFER_POLL])

        async def data(bytes):
            for byte in bytes:
                await iface.write([XFER_WRITE, byte, XFER_POLL])

        # HD44780 may be in either 4-bit or 8-bit mode and we don't know which.
        # The following sequence brings it to 4-bit mode regardless of which one it was in.
        await init(0x03, poll=False) # either CMD_FUNCTION_SET|BIT_IFACE_8BIT or CMD_CURSOR_HOME
                                     # or the second nibble of an unknown command/data
        await init(0x03, poll=False) # either CMD_FUNCTION_SET|BIT_IFACE_8BIT or CMD_CURSOR_HOME
                                     # or the second nibble of CMD_FUNCTION_SET (the set bits
                                     # are ignored)
        await init(0x03, poll=False) # CMD_FUNCTION_SET|BIT_IFACE_8BIT
        await init(0x02, poll=True)  # CMD_FUNCTION_SET

        await cmd(CMD_FUNCTION_SET|BIT_DISPLAY_2_LINE)
        await cmd(CMD_DISPLAY_ON_OFF|BIT_DISPLAY_ON|BIT_CURSOR_BLINK)
        await cmd(CMD_CLEAR_DISPLAY)
        await cmd(CMD_ENTRY_MODE|BIT_CURSOR_INC_POS)
        await data(b"Hello")
        await cmd(CMD_DDRAM_ADDRESS|0x40)
        await data(b"  World")
        await iface.flush()
        await asyncio.sleep(1)

        from datetime import datetime
        while True:
            await asyncio.sleep(1)
            await cmd(CMD_DDRAM_ADDRESS|0x00)
            await data(datetime.now().strftime("%H:%M:%S").encode("ascii"))
            await cmd(CMD_DDRAM_ADDRESS|0x40)
            await data(datetime.now().strftime("%y-%m-%d").encode("ascii"))
            await iface.flush()

# -------------------------------------------------------------------------------------------------

class DisplayHD44780AppletTestCase(GlasgowAppletTestCase, applet=DisplayHD44780Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
