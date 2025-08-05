# Ref: I2C-bus specification and user manual Rev 7.0
# Document Number: UM10204
# Accession: G00101

import contextlib
import logging
import struct

from amaranth import *
from amaranth.lib import enum, wiring, stream
from amaranth.lib.wiring import In, Out

from glasgow.support.logging import dump_hex
from glasgow.abstract import AbstractAssembly, GlasgowPin, PullState, ClockDivisor
from glasgow.gateware.i2c import I2CInitiator
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2


__all__ = ["I2CNotAcknowledged", "I2CControllerInterface", "PullState"]


class I2CNotAcknowledged(GlasgowAppletError):
    pass


class _Command(enum.Enum, shape=8):
    Start = 0x00
    Stop  = 0x01
    Write = 0x02
    Read  = 0x03


class I2CControllerComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))

    divisor: In(16)

    def __init__(self, ports):
        self._ports = ports

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.ctrl = ctrl = I2CInitiator(self._ports, 0)
        m.d.comb += ctrl.divisor.eq(self.divisor)

        cmd   = Signal(_Command)
        count = Signal(16)

        with m.FSM():
            with m.State("IDLE"):
                m.d.sync += cmd.eq(self.i_stream.payload)
                with m.If(self.i_stream.valid & ~ctrl.busy):
                    m.d.comb += self.i_stream.ready.eq(1)
                    m.next = "COMMAND"

            with m.State("COMMAND"):
                with m.Switch(cmd):
                    with m.Case(_Command.Start):
                        m.d.comb += ctrl.start.eq(1)
                        m.next = "SYNC"
                    with m.Case(_Command.Stop):
                        m.d.comb += ctrl.stop.eq(1)
                        m.next = "SYNC"
                    with m.Case(_Command.Write, _Command.Read):
                        m.next = "COUNT"

            with m.State("SYNC"):
                with m.If(~ctrl.busy):
                    m.d.comb += self.o_stream.valid.eq(1)
                    with m.If(self.o_stream.ready):
                        m.next = "IDLE"

            with m.State("COUNT"):
                word = Signal(range(2))
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    m.d.sync += count.word_select(word, 8).eq(self.i_stream.payload)
                    m.d.sync += word.eq(word + 1)
                    with m.If(word == 1):
                        with m.Switch(cmd):
                            with m.Case(_Command.Write):
                                m.next = "WRITE-FIRST"
                            with m.Case(_Command.Read):
                                m.next = "READ-FIRST"

            with m.State("WRITE-FIRST"):
                with m.If(self.i_stream.valid):
                    m.d.comb += self.i_stream.ready.eq(1)
                    m.d.comb += ctrl.data_i.eq(self.i_stream.payload)
                    m.d.comb += ctrl.write.eq(1)
                    m.next = "WRITE-ACK"

            with m.State("WRITE-ACK"):
                with m.If(~ctrl.busy):
                    with m.If(ctrl.ack_o):
                        m.d.sync += count.eq(count - 1)
                    m.next = "WRITE"

            with m.State("WRITE"):
                with m.If((count == 0) | ~ctrl.ack_o):
                    m.next = "REPORT"
                with m.Elif(self.i_stream.valid):
                    m.d.comb += self.i_stream.ready.eq(1)
                    m.d.comb += ctrl.data_i.eq(self.i_stream.payload)
                    m.d.comb += ctrl.write.eq(1)
                    m.next = "WRITE-ACK"

            with m.State("REPORT"):
                word = Signal(range(2))
                m.d.comb += self.o_stream.valid.eq(1)
                with m.If(self.o_stream.ready):
                    m.d.comb += self.o_stream.payload.eq(count.word_select(word, 8))
                    m.d.sync += word.eq(word + 1)
                    with m.If(word == 1):
                        m.d.sync += count.eq(0)
                        m.next = "IDLE"

            with m.State("READ-FIRST"):
                m.d.comb += ctrl.ack_i.eq(count != 1)
                m.d.comb += ctrl.read.eq(1)
                m.d.sync += count.eq(count - 1)
                m.next = "READ"

            with m.State("READ"):
                with m.If(~ctrl.busy):
                    m.d.comb += self.o_stream.valid.eq(1)
                    m.d.comb += self.o_stream.payload.eq(ctrl.data_o)
                    with m.If(self.o_stream.ready):
                        with m.If(count == 0):
                            m.next = "IDLE"
                        with m.Else():
                            m.d.comb += ctrl.ack_i.eq(count != 1)
                            m.d.comb += ctrl.read.eq(1)
                            m.d.sync += count.eq(count - 1)

        return m


class I2CControllerInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 scl: GlasgowPin, sda: GlasgowPin):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        assembly.use_pulls({scl: "high", sda: "high"})
        ports = assembly.add_port_group(scl=scl, sda=sda)
        component = assembly.add_submodule(I2CControllerComponent(ports))
        self._pipe = assembly.add_inout_pipe(component.o_stream, component.i_stream)
        self._clock = assembly.add_clock_divisor(component.divisor,
            ref_period=assembly.sys_clk_period * 4, name="scl")

        self._multi = False
        self._busy  = False

    @staticmethod
    def _chunked(items, *, count=0xffff):
        while items:
            yield items[:count]
            items = items[count:]

    def _log(self, message, *args):
        self._logger.log(self._level, "I²C: " + message, *args)

    async def _command(self, cmd: _Command, *, send: bytes | bytearray, recv: int) -> memoryview:
        await self._pipe.send([cmd.value])
        await self._pipe.send(send)
        await self._pipe.flush()
        return await self._pipe.recv(recv)

    async def _do_start(self):
        if not self._busy:
            self._log("start")
        else:
            self._log("rep-start")
        await self._command(_Command.Start, send=b"", recv=1)
        self._busy = True

    async def _do_stop(self):
        self._log("stop")
        await self._command(_Command.Stop, send=b"", recv=1)
        self._busy = False

    async def _do_addr(self, address: int, *, read: bool) -> bool:
        if read:
            self._log(f"read addr={address:#09b}")
        else:
            self._log(f"write addr={address:#09b}")
        unacked, = struct.unpack("<H",
            await self._command(_Command.Write,
                send=struct.pack("<HB", 1, (address << 1) | read),
                recv=2))
        if unacked:
            raise I2CNotAcknowledged(
                f"address {address:#09b} ({'read' if read else 'write'}) not acknowledged")

    async def _do_write(self, data: bytes | bytearray | memoryview) -> int:
        self._log("write data=<%s>", dump_hex(data))
        acked = 0
        for chunk in self._chunked(data):
            chunk_unacked, = struct.unpack("<H",
                await self._command(_Command.Write,
                    send=struct.pack("<H", len(chunk)) + bytes(chunk),
                    recv=2))
            acked += len(chunk) - chunk_unacked
            if chunk_unacked > 0:
                raise I2CNotAcknowledged(
                    f"data not acknowledged ({acked}/{len(data)} written)")

    async def _do_read(self, count: int) -> bytes:
        data_chunks = []
        for chunk in self._chunked(range(count)):
            chunk_data = await self._command(_Command.Read,
                send=struct.pack("<H", len(chunk)),
                recv=len(chunk))
            data_chunks.append(chunk_data)

        data = b"".join(data_chunks)
        self._log("read data=<%s>", dump_hex(data))
        return data

    @contextlib.asynccontextmanager
    async def _do_operation(self):
        await self._do_start()
        try:
            yield
        finally:
            if not self._multi:
                await self._do_stop()

    @property
    def clock(self) -> ClockDivisor:
        """SCL clock divisor."""
        return self._clock

    @contextlib.asynccontextmanager
    async def transaction(self):
        """Perform a transaction.

        While a transaction is active, calls to :meth:`write` and :meth:`read` do not generate
        a STOP condition; only one STOP condition is generated once the transaction ends. This also
        means that each call to :meth:`write` or :meth:`read` after the first such call in
        a transaction will generate a repeated START condition.

        For example, to perform ``S 0x50 nW 0x01 A Sr 0x50 R 0x?? nA 0x?? P`` (read of two bytes
        from a 24-series single address byte EEPROM, starting at address 0x01), use the following
        code:

        .. code:: python

            async with iface.transaction():
                await iface.write(0x50, [0x01])
                data = await iface.read(0x50, 2)

        An empty transaction (where the body does not call :meth:`write` or :meth:`read`) is
        allowed and produces no bus activity. (A START condition followed by a STOP condition is
        prohibited by the I²C specification.)
        """
        assert not self._multi, "transaction already active"

        self._multi = True
        try:
            yield
        finally:
            if self._busy:
                await self._do_stop()
            self._multi = False

    async def write(self, address: int, data: bytes | bytearray | memoryview):
        """Write bytes.

        Generates a START condition followed by a WRITE target address (:py:`(address << 1) | 0`),
        writes data, then generates a STOP condition (unless used within a transaction).

        Raises
        ------
        I2CNotAcknowledged
            If either the target address or the written data receives a not-acknowledgement.
        """
        assert address in range(0, 128)

        async with self._do_operation():
            await self._do_addr(address, read=False)
            await self._do_write(data)

    async def read(self, address: int, count: int) -> bytes:
        """Read bytes.

        Generates a START condition followed by a READ target address (:py:`(address << 1) | 1`),
        reads data, then generates a STOP condition (unless used within a transaction).

        The I²C bus design requires :py:`count` to be 1 or more.

        Raises
        ------
        I2CNotAcknowledged
            If the target address receives a not-acknowledgement.
        """
        assert address in range(0, 128) and count >= 1

        async with self._do_operation():
            await self._do_addr(address, read=True)
            return await self._do_read(count)

    async def ping(self, address: int) -> bool:
        """Check address for presence.

        Generates a START condition followed by a WRITE target address, then generates a STOP
        condition (unless used within a transaction). This is done using a :meth:`write` call
        with no data.

        Returns :py:`True` if the target adddress receives an acknowledgement, :py:`False`
        otherwise.
        """
        assert address in range(0, 128)

        try:
            async with self._do_operation():
                await self._do_addr(address, read=False)
        except I2CNotAcknowledged:
            return False
        else:
            return True

    async def scan(self, addresses: range = range(0b0001_000, 0b1111_000)) -> set[int]:
        """Scan address range for presence.

        Calls :meth:`ping` for each of :py:`addresses`. The default address range includes every
        non-reserved I²C address.

        Returns the set of addresses receiving an acknowledgement.
        """

        acked = set()
        for address in addresses:
            if await self.ping(address):
                acked.add(address)
        return acked

    async def device_id(self, address: int) -> tuple[int, int, int]:
        """Retrieve Device ID.

        The standard I²C Device ID command (which uses the reserved address :py:`0b1111_100`) must
        not be confused with various vendor-specific device identifiers (which use a vendor-specific
        mechanism). This command is optional and rarely implemented.

        Returns a 3-tuple :py:`(manufacturer, part_ident, revision)`.

        Raises
        ------
        I2CNotAcknowledged
            If the command is not implemented.
        """

        async with self.transaction():
            await self.write(0b1111_100, [address])
            device_id = await self.read(0b1111_100, 3)

        manufacturer = (device_id[0] << 4) | (device_id[1] >> 4)
        part_ident   = ((device_id[1] & 0xf) << 5) | (device_id[2] >> 3)
        revision     = device_id[2] & 0x7
        return (manufacturer, part_ident, revision)


class I2CControllerApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "initiate I²C transactions"
    description = """
    Initiate transactions on the I²C bus.

    The following optional bus features are supported:

    * Clock stretching
    * Device ID
    """
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "scl", default=True, required=True)
        access.add_pins_argument(parser, "sda", default=True, required=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.i2c_iface = I2CControllerInterface(self.logger, self.assembly,
                scl=args.scl, sda=args.sda)

    @classmethod
    def add_setup_arguments(cls, parser):
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=100,
            help="set SCL frequency to FREQ kHz (default: %(default)s, range: 100...4000)")

    async def setup(self, args):
        await self.i2c_iface.clock.set_frequency(args.frequency * 1000)

    @classmethod
    def add_run_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_scan = p_operation.add_parser(
            "scan", help="scan all possible I2C addresses")
        p_scan.add_argument(
            "--device-id", action="store_true", default=False,
            help="read device ID from devices responding to scan")

    async def run(self, args):
        if args.operation == "scan":
            for addr in await self.i2c_iface.scan():
                self.logger.info(f"scan found address {addr:#09b}/{addr:#04x}")
                if args.device_id:
                    try:
                        manufacturer, part_ident, revision = await self.i2c_iface.device_id(addr)
                        self.logger.info("device %s ID: manufacturer %s, part %s, revision %s",
                            bin(addr), bin(manufacturer), bin(part_ident), bin(revision))
                    except I2CNotAcknowledged:
                        self.logger.warning("device %s did not acknowledge Device ID", bin(addr))

    @classmethod
    def tests(cls):
        from . import test
        return test.I2CControllerAppletTestCase
