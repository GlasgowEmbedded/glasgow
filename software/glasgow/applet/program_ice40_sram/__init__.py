import math
import argparse
import logging
from migen import *

from .. import *


class ProgramICE40SRAMSubtarget(Module):
    def __init__(self, pads, out_fifo, sys_clk_freq):
        oe = Signal()
        self.comb += [
            pads.rst_n_t.oe.eq(1),
            pads.ss_n_t.oe.eq(oe),
            pads.sck_t.oe.eq(oe),
            pads.si_t.oe.eq(oe),
        ]

        reset_cyc = math.ceil(1e-6 * sys_clk_freq)
        start_cyc = math.ceil(1200e-6 * sys_clk_freq)
        done_cyc  = 49
        timer     = Signal(max=start_cyc)

        byteno = Signal(max=255)
        bitno  = Signal(3)
        shreg  = Signal(8)

        divisor = Signal(4, reset=1)

        self.submodules.fsm = FSM(reset_state="IDLE")
        self.fsm.act("IDLE",
            If(out_fifo.readable,
                NextValue(oe, 1),
                NextValue(pads.rst_n_t.o, 0),
                NextValue(pads.sck_t.o, 1),
                NextValue(timer, reset_cyc),
                NextState("RESET")
            ).Else(
                NextValue(oe, 0),
                NextValue(pads.rst_n_t.o, 1),
            )
        )
        self.fsm.act("RESET",
            If(timer == 0,
                NextValue(pads.rst_n_t.o, 1),
                NextValue(timer, start_cyc),
                NextState("START")
            ).Else(
                NextValue(timer, timer - 1)
            )
        )
        self.fsm.act("START",
            If(timer == 0,
                NextState("CHUNK")
            ).Else(
                NextValue(timer, timer - 1)
            )
        )
        self.fsm.act("CHUNK",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                If(out_fifo.dout == 0,
                    NextValue(timer, done_cyc),
                    NextState("DONE")
                ).Else(
                    NextValue(byteno, out_fifo.dout),
                    NextState("LOAD")
                )
            )
        )
        self.fsm.act("LOAD",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(byteno, byteno - 1),
                NextValue(bitno, 7),
                NextValue(shreg, out_fifo.dout),
                NextValue(divisor, divisor.reset),
                NextState("SETUP")
            )
        )
        self.fsm.act("SETUP",
            NextValue(pads.sck_t.o, 0),
            NextValue(pads.si_t.o, shreg[7]),
            If(divisor == 0,
                NextValue(divisor, divisor.reset),
                NextState("HOLD")
            ).Else(
                NextValue(divisor, divisor - 1)
            )
        )
        self.fsm.act("HOLD",
            NextValue(pads.sck_t.o, 1),
            If(divisor == 0,
                NextValue(divisor, divisor.reset),
                If((bitno == 0) & (byteno == 0),
                    NextState("CHUNK")
                ).Elif(bitno == 0,
                    NextState("LOAD")
                ).Else(
                    NextValue(bitno, bitno - 1),
                    NextValue(shreg, shreg << 1),
                    NextState("SETUP")
                )
            ).Else(
                NextValue(divisor, divisor - 1)
            )
        )
        self.fsm.act("DONE",
            NextValue(pads.sck_t.o, ~pads.sck_t.o),
            If(pads.sck_t.o,
                If(timer == 0,
                    NextState("IDLE")
                ).Else(
                    NextValue(timer, timer - 1)
                )
            )
        )


class ProgramICE40SRAMApplet(GlasgowApplet, name="program-ice40-sram"):
    logger = logging.getLogger(__name__)
    help = "program iCE40 FPGAs SRAM"
    description = """
    Program iCE40 FPGAs SRAM. This directly loads a bitstream into the FPGA
    volatile memory.
    """
    pins = ("rst_n", "ss_n", "sck", "si")

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_build_arguments(parser)
        for pin in cls.pins:
            access.add_pin_argument(parser, pin, default=True)

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(ProgramICE40SRAMSubtarget(
            pads=iface.get_pads(args, pins=self.pins),
            out_fifo=iface.get_out_fifo(),
            sys_clk_freq=target.sys_clk_freq,
        ))

    @classmethod
    def add_run_arguments(cls, parser, access):
        access.add_run_arguments(parser)

        parser.add_argument(
            "bitstream", metavar="BITSTREAM", type=argparse.FileType("rb"),
            help="bitstream file")

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)

        bitstream = args.bitstream.read()
        while len(bitstream) > 0:
            chunk = bitstream[:255]
            bitstream = bitstream[255:]
            await iface.write([len(chunk)])
            await iface.write(chunk)
        await iface.write([0])
        await iface.flush()

        # TODO: do this nicely
        # if args.port in device.poll_alert():
        #     raise Exception("Port {} voltage went out of range during programming"
        #                     .format(args.port))
        # TODO: check CDONE

# -------------------------------------------------------------------------------------------------

class ProgramICE40SRAMAppletTestCase(GlasgowAppletTestCase, applet=ProgramICE40SRAMApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
