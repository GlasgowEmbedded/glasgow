import argparse
import logging
import time
from migen import *
from migen.genlib.fsm import *

from . import *
from ..gateware.pads import *
from ..gateware.i2c import I2CMaster


logger = logging.getLogger(__name__)


CMD_RESET = 0x00
CMD_START = 0x01
CMD_STOP  = 0x02
CMD_WRITE = 0x03
CMD_READ  = 0x04


class I2CPadsWrapper(Module):
    def __init__(self, pads):
        self.scl_t = TSTriple(reset_i=1, reset_o=1, reset_oe=0)
        self.sda_t = TSTriple(reset_i=1, reset_o=1, reset_oe=0)

        if hasattr(pads, "scl_i_t"):
            self.comb += self.scl_t.i.eq(pads.scl_i_t.i)
        if hasattr(pads, "sda_i_t"):
            self.comb += self.sda_t.i.eq(pads.sda_i_t.i)
        if hasattr(pads, "scl_o_t"):
            self.comb += pads.scl_o_t.oe.eq(1)
            self.comb += pads.scl_o_t.o.eq(~self.scl_t.oe)
        if hasattr(pads, "sda_o_t"):
            self.comb += pads.sda_o_t.oe.eq(1)
            self.comb += pads.sda_o_t.o.eq(~self.sda_t.oe)
        if hasattr(pads, "scl_oe_t"):
            self.comb += pads.scl_oe_t.oe.eq(1)
            self.comb += pads.scl_oe_t.o.eq(self.scl_t.oe)
        if hasattr(pads, "sda_oe_t"):
            self.comb += pads.sda_oe_t.oe.eq(1)
            self.comb += pads.sda_oe_t.o.eq(self.sda_t.oe)
        if hasattr(pads, "scl_io_t"):
            self.comb += pads.scl_io_t.oe.eq(self.scl_t.oe)
            self.comb += pads.scl_io_t.o.eq(self.scl_t.o)
            self.comb += self.scl_t.i.eq(pads.scl_io_t.i)
        if hasattr(pads, "sda_io_t"):
            self.comb += pads.sda_io_t.oe.eq(self.sda_t.oe)
            self.comb += pads.sda_io_t.o.eq(self.sda_t.o)
            self.comb += self.sda_t.i.eq(pads.sda_io_t.i)


class I2CMasterSubtarget(Module):
    def __init__(self, pads, out_fifo, in_fifo, bit_rate):
        period_cyc = round(30e6 // bit_rate)

        self.submodules.pads = I2CPadsWrapper(pads)
        self.submodules.i2c_master = ResetInserter()(I2CMaster(self.pads, period_cyc))

        ###

        cmd   = Signal(8)
        count = Signal(8)

        self.submodules.fsm = FSM(reset_state="IDLE")
        self.fsm.act("IDLE",
            If(out_fifo.readable & (out_fifo.dout == CMD_RESET),
                out_fifo.re.eq(1),
                self.i2c_master.reset.eq(1),
                NextState("RESET")
            ).Elif(~self.i2c_master.busy & out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(cmd, out_fifo.dout),
                NextState("COMMAND")
            )
        )
        self.fsm.act("RESET",
            NextState("IDLE")
        )
        self.fsm.act("COMMAND",
            If(cmd == CMD_START,
                self.i2c_master.start.eq(1),
                NextState("IDLE")
            ).Elif(cmd == CMD_STOP,
                self.i2c_master.stop.eq(1),
                NextState("IDLE")
            ).Elif(cmd == CMD_WRITE,
                If(out_fifo.readable,
                    out_fifo.re.eq(1),
                    NextValue(count, out_fifo.dout),
                    If(out_fifo.dout == 0,
                        NextState("IDLE")
                    ).Else(
                        NextState("WRITE-FIRST")
                    )
                )
            ).Elif(cmd == CMD_READ,
                If(out_fifo.readable,
                    out_fifo.re.eq(1),
                    NextValue(count, out_fifo.dout),
                    If(out_fifo.dout == 0,
                        NextState("IDLE")
                    ).Else(
                        NextState("READ-FIRST")
                    )
                )
            ).Else(
                NextState("IDLE")
            )
        )
        self.fsm.act("WRITE-FIRST",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                self.i2c_master.data_i.eq(out_fifo.dout),
                self.i2c_master.write.eq(1),
                NextState("WRITE")
            )
        )
        self.fsm.act("WRITE",
            If(~self.i2c_master.busy,
                If(self.i2c_master.ack_o,
                    NextValue(count, count - 1)
                ),
                If((count == 1) | ~self.i2c_master.ack_o,
                    NextState("REPORT")
                ).Elif(out_fifo.readable,
                    out_fifo.re.eq(1),
                    self.i2c_master.data_i.eq(out_fifo.dout),
                    self.i2c_master.write.eq(1),
                )
            )
        )
        self.fsm.act("REPORT",
            If(in_fifo.writable,
                in_fifo.we.eq(1),
                in_fifo.din.eq(count),
                NextState("IDLE")
            )
        )
        self.fsm.act("READ-FIRST",
            self.i2c_master.ack_i.eq(~(count == 1)),
            self.i2c_master.read.eq(1),
            NextValue(count, count - 1),
            NextState("READ")
        )
        self.fsm.act("READ",
            If(~self.i2c_master.busy,
                If(in_fifo.writable,
                    in_fifo.we.eq(1),
                    in_fifo.din.eq(self.i2c_master.data_o),
                    If(count == 0,
                        NextState("IDLE")
                    ).Else(
                        self.i2c_master.ack_i.eq(~(count == 1)),
                        self.i2c_master.read.eq(1),
                        NextValue(count, count - 1)
                    )
                )
            )
        )


class I2CMasterInterface:
    def __init__(self, interface):
        self.lower = interface

    def reset(self):
        self.lower.write([CMD_RESET])

    def stop(self):
        self.lower.write([CMD_STOP])

    def write(self, addr, data, stop=False):
        self.lower.write([CMD_START, CMD_WRITE, 1 + len(data), (addr << 1) | 0, *data])
        if stop: self.lower.write([CMD_STOP])
        assert self.lower.read(1) == b"\x00"

    def read(self, addr, size, stop=False):
        self.lower.write([CMD_START, CMD_WRITE, 1, (addr << 1) | 1, CMD_READ, size])
        if stop: self.lower.write([CMD_STOP])
        assert self.lower.read(1) == b"\x00"
        return self.lower.read(size)

    def poll(self, addr):
        self.lower.write([CMD_START, CMD_WRITE, 1, (addr << 1) | 0, CMD_STOP])
        return self.lower.read(1) == b"\x00"


class I2CMasterApplet(GlasgowApplet, name="i2c-master"):
    logger = logger
    help = "initiate transactions on I2C"
    description = """
    Initiate transactions on the I2C bus.

    Maximum transaction length is 256 bytes.
    """
    pins = ("scl_i", "scl_o", "scl_oe", "scl_io", "sda_i", "sda_o", "sda_oe", "sda_io")

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_build_arguments(parser)
        for pin in cls.pins:
            access.add_pin_argument(parser, pin)

        parser.add_argument(
            "-b", "--bit-rate", metavar="FREQ", type=int, default=100,
            help="set I2C bit rate to FREQ kHz (default: %(default)s)")

    def build(self, target, args):
        if not (args.pin_scl_io is not None or
                (args.pin_scl_i is not None and
                 (args.pin_scl_o is not None or args.pin_scl_oe is not None))):
            raise GlasgowAppletError("At least one SCL input and output pin must be specified.")

        if not (args.pin_sda_io is not None or
                (args.pin_sda_i is not None and
                 (args.pin_sda_o is not None or args.pin_sda_oe is not None))):
            raise GlasgowAppletError("At least one SDA input and output pin must be specified.")

        iface = target.multiplexer.claim_interface(self, args)
        target.submodules += I2CMasterSubtarget(
            pads=iface.get_pads(args, pins=self.pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(streaming=False),
            bit_rate=args.bit_rate * 1000,
        )

    @classmethod
    def add_run_arguments(cls, parser, access):
        access.add_run_arguments(parser)

    def run(self, device, args, interactive=True):
        interface = I2CMasterInterface(device.demultiplexer.claim_interface(self, args))
        if interactive:
            pass # TODO: implement
        else:
            return interface
