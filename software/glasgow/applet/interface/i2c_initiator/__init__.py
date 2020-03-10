import argparse
import logging
import math
from nmigen.compat import *

from ....support.pyrepl import *
from ....gateware.pads import *
from ....gateware.i2c import I2CInitiator
from ... import *


CMD_START = 0x01
CMD_STOP  = 0x02
CMD_COUNT = 0x03
CMD_WRITE = 0x04
CMD_READ  = 0x05


class I2CInitiatorSubtarget(Module):
    def __init__(self, pads, out_fifo, in_fifo, period_cyc):
        self.submodules.i2c_initiator = I2CInitiator(pads, period_cyc)

        ###

        cmd   = Signal(8)
        count = Signal(16)

        self.submodules.fsm = FSM(reset_state="IDLE")
        self.fsm.act("IDLE",
            If(~self.i2c_initiator.busy & out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(cmd, out_fifo.dout),
                NextState("COMMAND")
            )
        )
        self.fsm.act("COMMAND",
            If(cmd == CMD_START,
                self.i2c_initiator.start.eq(1),
                NextState("IDLE")
            ).Elif(cmd == CMD_STOP,
                self.i2c_initiator.stop.eq(1),
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
                self.i2c_initiator.data_i.eq(out_fifo.dout),
                self.i2c_initiator.write.eq(1),
                NextState("WRITE")
            )
        )
        self.fsm.act("WRITE",
            If(~self.i2c_initiator.busy,
                If(self.i2c_initiator.ack_o,
                    NextValue(count, count - 1)
                ),
                If((count == 1) | ~self.i2c_initiator.ack_o,
                    NextState("REPORT")
                ).Elif(out_fifo.readable,
                    out_fifo.re.eq(1),
                    self.i2c_initiator.data_i.eq(out_fifo.dout),
                    self.i2c_initiator.write.eq(1),
                )
            )
        )
        self.fsm.act("REPORT",
            If(in_fifo.writable,
                in_fifo.we.eq(1),
                in_fifo.din.eq(count),
                NextValue(count, 0),
                NextState("IDLE")
            )
        )
        self.fsm.act("READ-FIRST",
            self.i2c_initiator.ack_i.eq(~(count == 1)),
            self.i2c_initiator.read.eq(1),
            NextValue(count, count - 1),
            NextState("READ")
        )
        self.fsm.act("READ",
            If(~self.i2c_initiator.busy,
                If(in_fifo.writable,
                    in_fifo.we.eq(1),
                    in_fifo.din.eq(self.i2c_initiator.data_o),
                    If(count == 0,
                        NextState("IDLE")
                    ).Else(
                        self.i2c_initiator.ack_i.eq(~(count == 1)),
                        self.i2c_initiator.read.eq(1),
                        NextValue(count, count - 1)
                    )
                )
            )
        )


class I2CInitiatorInterface:
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
        assert count < 0xffff
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

    async def read(self, addr, size, stop=False):
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

    async def scan(self, addresses=range(0b0001_000, 0b1111_000), *, read=True, write=True):
        # default address range: don't scan reserved I2C addresses
        found = set()
        for addr in addresses:
            # Do write scanning before read scanning to reduce the likeliness of possible
            # side effects due to really reading 1 byte in the read scan
            if write:
                if await self.write(addr, [], stop=True) is True:
                    self._logger.log(self._level, "I2C scan: found write address %s",
                                        "{:#09b}".format(addr))
                    found.add(addr)
                    # After a successful write detection no read scan is done anymore
                    continue
            if read:
                # We need to read at least one byte in order to transmit a NAK bit
                # so that the addressed device releases SDA.
                if await self.read(addr, 1, stop=True) is not None:
                    self._logger.log(self._level, "I2C scan: found read address %s",
                                        "{:#09b}".format(addr))
                    found.add(addr)
        return found


class I2CInitiatorApplet(GlasgowApplet, name="i2c-initiator"):
    logger = logging.getLogger(__name__)
    help = "initiate I²C transactions"
    description = """
    Initiate transactions on the I²C bus.

    Maximum transaction length is 65535 bytes.
    """
    required_revision = "C0"

    __pins = ("scl", "sda")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in cls.__pins:
            access.add_pin_argument(parser, pin, default=True)

        parser.add_argument(
            "-b", "--bit-rate", metavar="FREQ", type=int, default=100,
            help="set I2C bit rate to FREQ kHz (default: %(default)s)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(I2CInitiatorSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(),
            period_cyc=math.ceil(target.sys_clk_freq / (args.bit_rate * 1000))
        ))

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

        parser.add_argument(
            "--pulls", default=False, action="store_true",
            help="enable integrated pull-ups")

    async def run(self, device, args):
        pulls = set()
        if args.pulls:
            pulls = {args.pin_scl, args.pin_sda}
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args,
                                                           pull_high=pulls)
        i2c_iface = I2CInitiatorInterface(iface, self.logger)
        return i2c_iface

    @classmethod
    def add_interact_arguments(cls, parser):
        # TODO(py3.7): add required=True
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_scan = p_operation.add_parser(
            "scan", help="scan all possible I2C addresses")

        p_scan.add_argument(
            "--read", "-r", action="store_true", default=False,
            help="scan read addresses")

        p_scan.add_argument(
            "--write", "-w", action="store_true", default=False,
            help="scan write addresses")

        p_scan.add_argument(
            "--device-id", "-i", action="store_true", default=False,
            help="read device ID from devices responding to scan")

    async def interact(self, device, args, i2c_iface):
        if args.operation == "scan":
            # read/write is the default option
            if not args.read and not args.write:
                args.read  = True
                args.write = True

            found_addrs = await i2c_iface.scan(read=args.read, write=args.write)
            for addr in sorted(found_addrs):
                self.logger.info("scan found address %s",
                                    "{:#09b}".format(addr))
                if args.device_id:
                    device_id = await i2c_iface.device_id(addr)
                    if device_id is None:
                        self.logger.warning("device %s did not acknowledge Device ID", bin(addr))
                    else:
                        manufacturer, part_ident, revision = device_id
                        self.logger.info("device %s ID: manufacturer %s, part %s, revision %s",
                            bin(addr), bin(manufacturer), bin(part_ident), bin(revision))

# -------------------------------------------------------------------------------------------------

class I2CInitiatorAppletTestCase(GlasgowAppletTestCase, applet=I2CInitiatorApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
