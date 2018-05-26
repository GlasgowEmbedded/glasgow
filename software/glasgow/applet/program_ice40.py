import math
import argparse
from migen import *
from migen.genlib.fsm import *

from . import GlasgowApplet


class ProgramICE40Subtarget(Module):
    def __init__(self, rst_n, ss_n, sck, si, out_fifo):
        oe = Signal()
        self.comb += [
            rst_n.oe.eq(1),
            ss_n.oe.eq(oe),
            sck.oe.eq(oe),
            si.oe.eq(oe),
        ]

        reset_cyc = math.ceil(1e-6 * 30e6)
        start_cyc = math.ceil(1200e-6 * 30e6)
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
                NextValue(rst_n.o, 0),
                NextValue(sck.o, 1),
                NextValue(timer, reset_cyc),
                NextState("RESET")
            ).Else(
                NextValue(oe, 0),
                NextValue(rst_n.o, 1),
            )
        )
        self.fsm.act("RESET",
            If(timer == 0,
                NextValue(rst_n.o, 1),
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
            NextValue(sck.o, 0),
            NextValue(si.o, shreg[7]),
            If(divisor == 0,
                NextValue(divisor, divisor.reset),
                NextState("HOLD")
            ).Else(
                NextValue(divisor, divisor - 1)
            )
        )
        self.fsm.act("HOLD",
            NextValue(sck.o, 1),
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
            NextValue(sck.o, ~sck.o),
            If(sck.o,
                If(timer == 0,
                    NextState("IDLE")
                ).Else(
                    NextValue(timer, timer - 1)
                )
            )
        )


class ProgramICE40Applet(GlasgowApplet, name="program-ice40"):
    help = "program iCE40 FPGAs"
    description = """
    Program iCE40 FPGAs.

    Port voltage is sensed and monitored.
    """

    @classmethod
    def add_build_arguments(cls, parser):
        cls.add_port_argument(parser, default="A")
        cls.add_pin_argument(parser, "rst_n", default=0)
        cls.add_pin_argument(parser, "ss_n", default=1)
        cls.add_pin_argument(parser, "sck", default=2)
        cls.add_pin_argument(parser, "si", default=3)

    def build(self, target, args):
        io_port = target.get_io_port(args.port)
        target.submodules += ProgramICE40Subtarget(
            rst_n=io_port[args.pin_rst_n],
            ss_n=io_port[args.pin_ss_n],
            sck=io_port[args.pin_sck],
            si=io_port[args.pin_si],
            out_fifo=target.get_out_fifo(args.port),
        )

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument(
            "bitstream", metavar="BITSTREAM", type=argparse.FileType("rb"),
            help="bitstream file")

    def run(self, device, args):
        device.mirror_voltage(self.spec)

        port = device.get_port(self.spec)
        bitstream = args.bitstream.read()
        while len(bitstream) > 0:
            chunk = bitstream[:255]
            bitstream = bitstream[255:]
            port.write([len(chunk)])
            port.write(chunk)
        port.write([0])
        port.flush()

        if self.spec in device.poll_alert():
            raise Exception("Port {} voltage went out of range during programming"
                            .format(self.spec))
        # TODO: check CDONE
