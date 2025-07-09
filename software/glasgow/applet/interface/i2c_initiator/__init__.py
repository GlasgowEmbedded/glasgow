import argparse
import logging
import math
from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io
from amaranth.lib.wiring import In, Out
from glasgow.abstract import AbstractAssembly, GlasgowPin, PullState

from ....gateware.i2c import I2CInitiator
from ... import *


CMD_START = 0x01
CMD_STOP  = 0x02
CMD_COUNT = 0x03
CMD_WRITE = 0x04
CMD_READ  = 0x05


class I2CInitiatorComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))

    def __init__(self, ports, period_cyc):
        self._ports = ports
        self._period_cyc = period_cyc
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.i2c_initiator = i2c_initiator = I2CInitiator(self._ports, self._period_cyc)

        ###

        cmd   = Signal(8)
        count = Signal(16)

        with m.FSM():
            with m.State("IDLE"):
                with m.If(~i2c_initiator.busy & self.i_stream.valid):
                    m.d.comb += self.i_stream.ready.eq(1)
                    m.d.sync += cmd.eq(self.i_stream.payload)
                    m.next = "COMMAND"

            with m.State("COMMAND"):
                with m.If(cmd == CMD_START):
                    m.d.comb += i2c_initiator.start.eq(1)
                    m.next = "IDLE"
                with m.Elif(cmd == CMD_STOP):
                    m.d.comb += i2c_initiator.stop.eq(1)
                    m.next = "IDLE"
                with m.Elif(cmd == CMD_COUNT):
                    m.next = "COUNT-MSB"
                with m.Elif(cmd == CMD_WRITE):
                    with m.If(count == 0):
                        m.next = "IDLE"
                    with m.Else():
                        m.next = "WRITE-FIRST"
                with m.Elif(cmd == CMD_READ):
                    with m.If(count == 0):
                        m.next = "IDLE"
                    with m.Else():
                        m.next = "READ-FIRST"
                with m.Else():
                    m.next = "IDLE"

            with m.State("COUNT-MSB"):
                with m.If(self.i_stream.valid):
                    m.d.comb += self.i_stream.ready.eq(1)
                    m.d.sync += count.eq(self.i_stream.payload << 8)
                    m.next = "COUNT-LSB"
            with m.State("COUNT-LSB"):
                with m.If(self.i_stream.valid):
                    m.d.comb += self.i_stream.ready.eq(1)
                    m.d.sync += count.eq(count | self.i_stream.payload)
                    m.next = "IDLE"

            with m.State("WRITE-FIRST"):
                with m.If(self.i_stream.valid):
                    m.d.comb += [
                        self.i_stream.ready.eq(1),
                        i2c_initiator.data_i.eq(self.i_stream.payload),
                        i2c_initiator.write.eq(1),
                    ]
                    m.next = "WRITE"
            with m.State("WRITE"):
                with m.If(~i2c_initiator.busy):
                    with m.If(i2c_initiator.ack_o):
                        m.d.sync += count.eq(count - 1)
                    with m.If((count == 1) | ~i2c_initiator.ack_o):
                        m.next = "REPORT"
                    with m.Elif(self.i_stream.valid):
                        m.d.comb += [
                            self.i_stream.ready.eq(1),
                            i2c_initiator.data_i.eq(self.i_stream.payload),
                            i2c_initiator.write.eq(1),
                        ]
            with m.State("REPORT"):
                with m.If(self.o_stream.ready):
                    m.d.comb += [
                        self.o_stream.payload.eq(count),
                        self.o_stream.valid.eq(1),
                    ]
                    m.d.sync += count.eq(0)
                    m.next = "IDLE"

            with m.State("READ-FIRST"):
                m.d.comb += [
                    i2c_initiator.ack_i.eq(~(count == 1)),
                    i2c_initiator.read.eq(1),
                ]
                m.d.sync += count.eq(count - 1)
                m.next = "READ"
            with m.State("READ"):
                with m.If(~i2c_initiator.busy):
                    with m.If(self.o_stream.ready):
                        m.d.comb += [
                            self.o_stream.payload.eq(i2c_initiator.data_o),
                            self.o_stream.valid.eq(1),
                        ]
                        with m.If(count == 0):
                            m.next = "IDLE"
                        with m.Else():
                            m.d.comb += [
                                i2c_initiator.ack_i.eq(~(count == 1)),
                                i2c_initiator.read.eq(1),
                            ]
                            m.d.sync += count.eq(count - 1)

        return m


class I2CInitiatorInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 scl: GlasgowPin, sda: GlasgowPin, period_cyc):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        assembly.use_pulls({scl: "high", sda: "high"})
        ports = assembly.add_port_group(scl=scl, sda=sda)
        component = assembly.add_submodule(I2CInitiatorComponent(ports, period_cyc))
        self._pipe = assembly.add_inout_pipe(component.o_stream, component.i_stream)

    async def reset(self):
        self._logger.debug("I2C: reset")
        await self._pipe.reset()

    async def _cmd_start(self):
        await self._pipe.send([CMD_START])

    async def _cmd_stop(self):
        await self._pipe.send([CMD_STOP])

    async def _cmd_count(self, count):
        assert count < 0xffff
        msb = (count >> 8) & 0xff
        lsb = (count >> 0) & 0xff
        await self._pipe.send([CMD_COUNT, msb, lsb])

    async def _cmd_write(self):
        await self._pipe.send([CMD_WRITE])

    async def _data_write(self, data):
        await self._pipe.send(data)

    async def _cmd_read(self):
        await self._pipe.send([CMD_READ])

    async def _data_read(self, size):
        return await self._pipe.recv(size)

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
        await self._pipe.flush()

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
        await self._pipe.flush()

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
                                        f"{addr:#09b}")
                    found.add(addr)
                    # After a successful write detection no read scan is done anymore
                    continue
            if read:
                # We need to read at least one byte in order to transmit a NAK bit
                # so that the addressed device releases SDA.
                if await self.read(addr, 1, stop=True) is not None:
                    self._logger.log(self._level, "I2C scan: found read address %s",
                                        f"{addr:#09b}")
                    found.add(addr)
        return found


class I2CInitiatorApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "initiate I²C transactions"
    description = """
    Initiate transactions on the I²C bus.

    Maximum transaction length is 65535 bytes.
    """
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "scl", default=True)
        access.add_pins_argument(parser, "sda", default=True)

        parser.add_argument(
            "-b", "--bit-rate", metavar="FREQ", type=int, default=100,
            help="set I2C bit rate to FREQ kHz (default: %(default)s)")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.i2c_iface = I2CInitiatorInterface(self.logger, self.assembly,
                scl=args.scl, sda=args.sda, period_cyc=math.ceil(1 / (self.assembly.sys_clk_period * args.bit_rate * 1000)))

    @classmethod
    def add_setup_arguments(cls, parser):
        pass

    async def setup(self, args):
        pass

    @classmethod
    def add_run_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

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

    async def run(self, args):
        if args.operation == "scan":
            # read/write is the default option
            if not args.read and not args.write:
                args.read  = True
                args.write = True

            found_addrs = await self.i2c_iface.scan(read=args.read, write=args.write)
            for addr in sorted(found_addrs):
                self.logger.info("scan found address %s",
                                    f"{addr:#09b}")
                if args.device_id:
                    device_id = await self.i2c_iface.device_id(addr)
                    if device_id is None:
                        self.logger.warning("device %s did not acknowledge Device ID", bin(addr))
                    else:
                        manufacturer, part_ident, revision = device_id
                        self.logger.info("device %s ID: manufacturer %s, part %s, revision %s",
                            bin(addr), bin(manufacturer), bin(part_ident), bin(revision))

    @classmethod
    def tests(cls):
        from . import test
        return test.I2CInitiatorAppletTestCase
