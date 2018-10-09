import argparse
import logging
from migen import *
from migen.genlib.fsm import *

from .. import *
from ...gateware.pads import *
from ...gateware.i2c import I2CMaster
from ...pyrepl import *


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
    def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    async def reset(self):
        self._logger.debug("I2C: reset")
        await self.lower.reset()

    async def _cmd_start(self):
        await self.lower.write([CMD_START])

    async def _cmd_stop(self):
        await self.lower.write([CMD_STOP])

    async def _cmd_count(self, count):
        msb = (count >> 8) & 0xff
        lsb = (count >> 0) & 0xff
        await self.lower.write([CMD_COUNT, msb, lsb])

    async def _cmd_write(self):
        await self.lower.write([CMD_WRITE])

    async def _data_write(self, data):
        await self.lower.write(data)

    async def _cmd_read(self):
        await self.lower.write([CMD_READ])

    async def _data_read(self, size):
        return await self.lower.read(size)

    async def write(self, addr, data, stop=False):
        data = bytes(data)

        if stop:
            self._logger.log(self._level, "I2C: start addr=%s write=<%s> stop",
                             bin(addr), data.hex())
        else:
            self._logger.log(self._level, "I2C: start addr=%s write=<%s>",
                             bin(addr), data.hex())

        await self._cmd_start()
        await self._cmd_count(1 + len(data))
        await self._cmd_write()
        await self._data_write([(addr << 1) | 0])
        await self._data_write(data)
        if stop: await self._cmd_stop()

        unacked, = await self._data_read(1)
        acked = len(data) - unacked
        if unacked == 0:
            self._logger.log(self._level, "I2C: acked")
        else:
            self._logger.log(self._level, "I2C: unacked=%d", unacked)

        return unacked == 0

    async def read(self, addr, size, stop=False, start=True):
        if stop:
            self._logger.log(self._level, "I2C: start addr=%s read=%d stop",
                             bin(addr), size)
        else:
            self._logger.log(self._level, "I2C: start addr=%s read=%d",
                             bin(addr), size)

        await self._cmd_start()
        await self._cmd_count(1)
        await self._cmd_write()
        await self._data_write([(addr << 1) | 1])
        await self._cmd_count(size)
        await self._cmd_read()
        if stop: await self._cmd_stop()

        unacked, = await self._data_read(1)
        data = await self._data_read(size)
        if unacked == 0:
            self._logger.log(self._level, "I2C: acked data=<%s>", data.hex())
            return data
        else:
            self._logger.log(self._level, "I2C: unacked")
            return None

    async def poll(self, addr):
        self._logger.trace("I2C: poll addr=%s", bin(addr))
        await self._cmd_start()
        await self._cmd_count(1)
        await self._cmd_write()
        await self._data_write([(addr << 1) | 0])
        await self._cmd_stop()

        unacked, = await self._data_read(1)
        if unacked == 0:
            self._logger.log(self._level, "I2C: poll addr=%s acked", bin(addr))

        return unacked == 0

    async def device_id(self, addr):
        if await self.write(0b1111_100, [addr]) is False:
            return None
        device_id = await self.read(0b1111_100, 3)
        if device_id is None:
            return None
        manufacturer = (device_id[0] << 8) | (device_id[1] >> 4)
        part_ident   = ((device_id[1] & 0xf) << 5) | (device_id[2] >> 3)
        revision     = device_id[2] & 0x7
        return (manufacturer, part_ident, revision)


class I2CMasterApplet(GlasgowApplet, name="i2c-master"):
    logger = logging.getLogger(__name__)
    help = "initiate I2C transactions"
    description = """
    Initiate transactions on the I2C bus.

    Maximum transaction length is 65535 bytes.
    """

    __pins = ("scl_i", "scl_o", "scl_oe", "scl_io", "sda_i", "sda_o", "sda_oe", "sda_io")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in cls.__pins:
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
        iface.add_subtarget(I2CMasterSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(),
            bit_rate=args.bit_rate * 1000,
        ))

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        i2c_iface = I2CMasterInterface(iface, self.logger)
        return i2c_iface

    @classmethod
    def add_interact_arguments(cls, parser):
        parser.add_argument(
            "--scan-device-id", action="store_true", default=False,
            help="read device ID from devices responding to scan")

        g_operation = parser.add_mutually_exclusive_group(required=True)
        g_operation.add_argument(
            "--scan-read", action="store_true", default=False,
            help="scan all possible I2C read addresses")
        g_operation.add_argument(
            "--scan-write", action="store_true", default=False,
            help="scan all possible I2C write addresses")
        g_operation.add_argument(
            "--repl", action="store_true", default=False,
            help="drop into Python shell; use `i2c_iface` to communicate")

    async def interact(self, device, args, i2c_iface):
        if args.scan_read or args.scan_write:
            # Don't scan reserved I2C addresses.
            for addr in range(0b0001_000, 0b1111_000):
                responded = False
                if args.scan_read:
                    # We need to read at least one byte in order to transmit a NAK bit
                    # so that the addressed device releases SDA.
                    if await i2c_iface.read(addr, 1, stop=True) is not None:
                        self.logger.info("scan found read address %s", bin(addr))
                        responded = True
                if args.scan_write:
                    if await i2c_iface.write(addr, [], stop=True) is True:
                        self.logger.info("scan found write address %s", bin(addr))
                        responded = True

                if responded and args.scan_device_id:
                    device_id = await i2c_iface.device_id(addr)
                    if device_id is None:
                        self.logger.warning("device %s did not acknowledge Device ID", bin(addr))
                    else:
                        manufacturer, part_ident, revision = device_id
                        self.logger.info("device %s ID: manufacturer %s, part %s, revision %s",
                            bin(addr), bin(manufacturer), bin(part_ident), bin(revision))

        if args.repl:
            await AsyncInteractiveConsole(locals={"i2c_iface":i2c_iface}).interact()
