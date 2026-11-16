import enum
from abc import ABCMeta, abstractmethod
from amaranth import *
from amaranth.lib import wiring, stream
from amaranth.lib.wiring import In, Out

from glasgow.support import logging
from glasgow.gateware.i2c import I2CTarget
from glasgow.abstract import AbstractAssembly, GlasgowPin
from glasgow.applet import GlasgowAppletV2


class Event(enum.IntEnum):
    START   = 0x10
    STOP    = 0x20
    RESTART = 0x30
    WRITE   = 0x40
    READ    = 0x50


class I2CTargetComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))

    def __init__(self, ports, address):
        self.ports      = ports
        self.address    = address
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.i2c_target = i2c_target = I2CTarget(self.ports)
        m.d.comb += i2c_target.address.eq(self.address)

        with m.FSM():
            w_data = Signal(8)

            m.d.comb += i2c_target.busy.eq(1)
            with m.State("IDLE"):
                m.d.comb += i2c_target.busy.eq(0)
                with m.If(i2c_target.start):
                    m.next = "SEND-START-EVENT"
                with m.Elif(i2c_target.stop):
                    m.next = "SEND-STOP-EVENT"
                with m.Elif(i2c_target.restart):
                    m.next = "SEND-RESTART-EVENT"
                with m.Elif(i2c_target.write):
                    m.d.sync += w_data.eq(i2c_target.data_i)
                    m.next = "SEND-WRITE-EVENT"
                with m.Elif(i2c_target.read):
                    m.next = "SEND-READ-EVENT"

            with m.State("SEND-START-EVENT"):
                m.d.comb += [
                    self.o_stream.payload.eq(Event.START),
                    self.o_stream.valid.eq(1),
                ]
                with m.If(self.o_stream.ready):
                    m.next = "IDLE"

            with m.State("SEND-STOP-EVENT"):
                m.d.comb += [
                    self.o_stream.payload.eq(Event.STOP),
                    self.o_stream.valid.eq(1),
                ]
                with m.If(self.o_stream.ready):
                    m.next = "IDLE"

            with m.State("SEND-RESTART-EVENT"):
                m.d.comb += [
                    self.o_stream.payload.eq(Event.RESTART),
                    self.o_stream.valid.eq(1),
                ]
                with m.If(self.o_stream.ready):
                    m.next = "IDLE"

            with m.State("SEND-WRITE-EVENT"):
                m.d.comb += [
                    self.o_stream.payload.eq(Event.WRITE),
                    self.o_stream.valid.eq(1),
                ]
                with m.If(self.o_stream.ready):
                    m.next = "SEND-WRITE-DATA"

            with m.State("SEND-WRITE-DATA"):
                m.d.comb += [
                    self.o_stream.payload.eq(w_data),
                    self.o_stream.valid.eq(1),
                ]
                with m.If(self.o_stream.ready):
                    m.next = "RECV-WRITE-ACK"

            with m.State("RECV-WRITE-ACK"):
                with m.If(self.i_stream.valid):
                    m.d.comb += [
                        i2c_target.ack_o.eq(self.i_stream.payload[0]),
                        self.i_stream.ready.eq(1),
                    ]
                    m.next = "IDLE"

            with m.State("SEND-READ-EVENT"):
                m.d.comb += [
                    self.o_stream.payload.eq(Event.READ),
                    self.o_stream.valid.eq(1),
                ]
                with m.If(self.o_stream.ready):
                    m.next = "RECV-READ-DATA"

            with m.State("RECV-READ-DATA"):
                with m.If(self.i_stream.valid):
                    m.d.comb += [
                        i2c_target.data_o.eq(self.i_stream.payload),
                        self.i_stream.ready.eq(1),
                    ]
                    m.next = "IDLE"

        return m


class I2CTargetInterface(metaclass=ABCMeta):
    """Software-defined I²C target at a 7-bit *address*.

    Subclass this interface and implement all five event callbacks. Construct it with a logger,
    an assembly, and the ``scl``, ``sda``, and ``address`` keyword arguments inside the assembly's
    ``add_applet()`` context. Call :meth:`read_event` repeatedly to process transactions.

    An applet subclass can set ``I2CTargetApplet.interface_cls`` to its custom interface class
    to reuse the applet's argument parsing and event loop.
    """

    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 scl: GlasgowPin, sda: GlasgowPin, address: int, pulls: bool = False):
        ports = assembly.add_port_group(scl=scl, sda=sda)
        if pulls:
            assembly.use_pulls({scl: "high", sda: "high"})
        component = assembly.add_submodule(I2CTargetComponent(ports, address))
        self._pipe = assembly.add_inout_pipe(component.o_stream, component.i_stream,
            in_flush=C(1))
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, "I²C: " + message, *args)

    async def read_event(self):
        """Process one bus event, await its callback, and transmit any response."""
        event, = await self._pipe.recv(1)
        if event == Event.START:
            self._log("event start")
            await self.on_start()
        elif event == Event.STOP:
            self._log("event stop")
            await self.on_stop()
        elif event == Event.RESTART:
            self._log("event restart")
            await self.on_restart()
        elif event == Event.WRITE:
            data, = await self._pipe.recv(1)
            self._log("event write data=<%02x>", data)
            ack = await self.on_write(data)
            assert isinstance(ack, bool)
            self._log("write %s", "ack" if ack else "nak")
            await self._pipe.send(bytes([ack]))
            await self._pipe.flush()
        elif event == Event.READ:
            self._log("event read")
            data = await self.on_read()
            assert isinstance(data, int) and data in range(256)
            self._log("read data=<%02x>", data)
            await self._pipe.send(bytes([data]))
            await self._pipe.flush()
        else:
            assert False

    @abstractmethod
    async def on_start(self):
        """Called when the initiator starts a transaction with this target."""
        pass

    @abstractmethod
    async def on_stop(self):
        """Called when the initiator ends a transaction."""
        pass

    @abstractmethod
    async def on_restart(self):
        """Called when the initiator issues a repeated START."""
        pass

    @abstractmethod
    async def on_write(self, data):
        """Receive one byte. Return ``True`` to acknowledge it or ``False`` to reject it."""
        pass

    @abstractmethod
    async def on_read(self):
        """Return the next byte to transmit as an integer from ``0`` through ``255``."""
        pass


class _DummyI2CTargetInterface(I2CTargetInterface):
    async def on_start(self):
        pass

    async def on_stop(self):
        pass

    async def on_restart(self):
        pass

    async def on_write(self, data):
        return True

    async def on_read(self):
        return 0xFF


class I2CTargetApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "accept I²C transactions"
    description = """
    Process transactions on the I²C bus as a software-defined target.

    This applet allows emulating any I²C device in Python, provided that the I²C initiator supports
    clock stretching and tolerates delays caused by host roundtrips. (Unfortunately, this excludes
    many I²C initiators.)

    The default emulated device is a dummy device that logs all transactions, acknowledges all
    writes, and returns 0xFF in response to all reads. Use the global -v option to display
    the transaction log. For example, emulate address 0x50 on A0 (SCL) and A1 (SDA),
    with integrated pull-ups enabled:

    ::

        $ glasgow run i2c-target -V 3.3 --scl A0 --sda A1 --address 0x50 --pulls
    """
    required_revision = "C0"

    interface_cls = _DummyI2CTargetInterface

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)

        access.add_pins_argument(parser, "scl", default=True, required=True)
        access.add_pins_argument(parser, "sda", default=True, required=True)

        def i2c_address(arg):
            return int(arg, 0)
        parser.add_argument(
            "-A", "--address", type=i2c_address, metavar="I2C-ADDR", required=True,
            help="I²C address of the target")

        parser.add_argument(
            "--pulls", default=False, action="store_true",
            help="enable integrated pull-ups")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.i2c_iface = self.interface_cls(self.logger, self.assembly,
                scl=args.scl, sda=args.sda, address=args.address, pulls=args.pulls)

    async def run(self, args):
        while True:
            await self.i2c_iface.read_event()

    @classmethod
    def tests(cls):
        from . import test
        return test.I2CTargetAppletTestCase
