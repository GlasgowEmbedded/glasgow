import argparse
import logging
import time
from migen import *
from migen.genlib.fsm import *

from . import *
from ..gateware.pads import *
from ..gateware.i2c import I2CMaster


logger = logging.getLogger(__name__)


CMD_START = 0x01
CMD_STOP  = 0x02
CMD_COUNT = 0x03
CMD_WRITE = 0x04
CMD_READ  = 0x05


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
        self.submodules.i2c_master = I2CMaster(self.pads, period_cyc)

        ###

        cmd   = Signal(8)
        count = Signal(16)

        self.submodules.fsm = FSM(reset_state="IDLE")
        self.fsm.act("IDLE",
            If(~self.i2c_master.busy & out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(cmd, out_fifo.dout),
                NextState("COMMAND")
            )
        )
        self.fsm.act("COMMAND",
            If(cmd == CMD_START,
                self.i2c_master.start.eq(1),
                NextState("IDLE")
            ).Elif(cmd == CMD_STOP,
                self.i2c_master.stop.eq(1),
                NextState("IDLE")
            ).Elif(cmd == CMD_COUNT,
                NextState("COUNT-MSB")
            ).Elif(cmd == CMD_WRITE,
                If(count == 0,
                    NextState("IDLE")
                ).Else(
                    NextState("WRITE-FIRST")
                )
            ).Elif(cmd == CMD_READ,
                If(count == 0,
                    NextState("IDLE")
                ).Else(
                    NextState("READ-FIRST")
                )
            ).Else(
                NextState("IDLE")
            )
        )
        self.fsm.act("COUNT-MSB",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(count, out_fifo.dout << 8),
                NextState("COUNT-LSB")
            )
        )
        self.fsm.act("COUNT-LSB",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(count, count | out_fifo.dout),
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
    def __init__(self, interface, logger, addr_reset):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._addr_reset = addr_reset

    def reset(self):
        self._logger.debug("I2C: reset")
        self.lower._device.write_register(self._addr_reset, 1)
        self.lower._device.write_register(self._addr_reset, 0)

    def _cmd_start(self):
        self.lower.write([CMD_START])

    def _cmd_stop(self):
        self.lower.write([CMD_STOP])

    def _cmd_count(self, count):
        msb = (count >> 8) & 0xff
        lsb = (count >> 0) & 0xff
        self.lower.write([CMD_COUNT, msb, lsb])

    def _cmd_write(self):
        self.lower.write([CMD_WRITE])

    def _data_write(self, data):
        self.lower.write(data)

    def _cmd_read(self):
        self.lower.write([CMD_READ])

    def _data_read(self, size):
        return self.lower.read(size)

    def write(self, addr, data, stop=False):
        data = bytes(data)

        if stop:
            self._logger.log(self._level, "I2C: start addr=%s write=<%s> stop",
                             bin(addr), data.hex())
        else:
            self._logger.log(self._level, "I2C: start addr=%s write=<%s>",
                             bin(addr), data.hex())

        self._cmd_start()
        self._cmd_count(1 + len(data))
        self._cmd_write()
        self._data_write([(addr << 1) | 0])
        self._data_write(data)
        if stop: self._cmd_stop()

        unacked, = self._data_read(1)
        acked = len(data) - unacked
        if unacked == 0:
            self._logger.log(self._level, "I2C: acked")
        else:
            self._logger.log(self._level, "I2C: unacked=%d", unacked)

        return unacked == 0

    def read(self, addr, size, stop=False):
        if stop:
            self._logger.log(self._level, "I2C: start addr=%s read=%d stop",
                             bin(addr), size)
        else:
            self._logger.log(self._level, "I2C: start addr=%s read=%d",
                             bin(addr), size)

        self._cmd_start()
        self._cmd_count(1)
        self._cmd_write()
        self._data_write([(addr << 1) | 1])
        self._cmd_count(size)
        self._cmd_read()
        if stop: self._cmd_stop()

        unacked, = self._data_read(1)
        data = self._data_read(size)
        if unacked == 0:
            self._logger.log(self._level, "I2C: acked data=<%s>", data.hex())
            return data
        else:
            self._logger.log(self._level, "I2C: unacked")
            return None

    def poll(self, addr):
        self._logger.trace("I2C: poll addr=%s", bin(addr))
        self._cmd_start()
        self._cmd_count(1)
        self._cmd_write()
        self._data_write([(addr << 1) | 0])
        self._cmd_stop()

        unacked, = self._data_read(1)
        if unacked == 0:
            self._logger.log(self._level, "I2C: poll addr=%s acked", bin(addr))

        return unacked == 0


class I2CMasterApplet(GlasgowApplet, name="i2c-master"):
    logger = logger
    help = "initiate transactions on I2C"
    description = """
    Initiate transactions on the I2C bus.

    Maximum transaction length is 65535 bytes.
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

        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = ResetInserter()(I2CMasterSubtarget(
            pads=iface.get_pads(args, pins=self.pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(streaming=False),
            bit_rate=args.bit_rate * 1000,
        ))
        target.submodules += subtarget

        reset, self.__addr_reset = target.registers.add_rw(1)
        target.comb += subtarget.reset.eq(reset)

    @classmethod
    def add_run_arguments(cls, parser, access):
        access.add_run_arguments(parser)

    def run(self, device, args, interactive=True):
        iface = device.demultiplexer.claim_interface(self, args)
        i2c = I2CMasterInterface(iface, self.logger, self.__addr_reset)
        if interactive:
            pass # TODO: implement
        else:
            return i2c
