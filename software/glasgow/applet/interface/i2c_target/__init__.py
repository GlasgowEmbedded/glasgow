import argparse
import logging
import enum
from abc import ABCMeta, abstractmethod
from nmigen import *

from ....gateware.pads import *
from ....gateware.i2c import I2CTarget
from ... import *


class Event(enum.IntEnum):
    START   = 0x10
    STOP    = 0x20
    RESTART = 0x30
    WRITE   = 0x40
    READ    = 0x50


class I2CTargetSubtarget(Elaboratable):
    def __init__(self, pads, out_fifo, in_fifo, address):
        self.pads       = pads
        self.out_fifo   = out_fifo
        self.in_fifo    = in_fifo
        self.address    = address

    def elaborate(self, platform):
        m = Module()

        m.submodules.i2c_target = i2c_target = I2CTarget(self.pads)
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
                    self.in_fifo.w_data.eq(Event.START),
                    self.in_fifo.w_en.eq(1),
                ]
                with m.If(self.in_fifo.w_rdy):
                    m.next = "IDLE"

            with m.State("SEND-STOP-EVENT"):
                m.d.comb += [
                    self.in_fifo.w_data.eq(Event.STOP),
                    self.in_fifo.w_en.eq(1),
                ]
                with m.If(self.in_fifo.w_rdy):
                    m.next = "IDLE"

            with m.State("SEND-RESTART-EVENT"):
                m.d.comb += [
                    self.in_fifo.w_data.eq(Event.RESTART),
                    self.in_fifo.w_en.eq(1),
                ]
                with m.If(self.in_fifo.w_rdy):
                    m.next = "IDLE"

            with m.State("SEND-WRITE-EVENT"):
                m.d.comb += [
                    self.in_fifo.w_data.eq(Event.WRITE),
                    self.in_fifo.w_en.eq(1),
                ]
                with m.If(self.in_fifo.w_rdy):
                    m.next = "SEND-WRITE-DATA"

            with m.State("SEND-WRITE-DATA"):
                m.d.comb += [
                    self.in_fifo.w_data.eq(w_data),
                    self.in_fifo.w_en.eq(1),
                ]
                with m.If(self.in_fifo.w_rdy):
                    m.next = "RECV-WRITE-ACK"

            with m.State("RECV-WRITE-ACK"):
                with m.If(self.out_fifo.r_rdy):
                    m.d.comb += [
                        i2c_target.ack_o.eq(self.out_fifo.r_data[0]),
                        self.out_fifo.r_en.eq(1),
                    ]
                    m.next = "IDLE"

            with m.State("SEND-READ-EVENT"):
                m.d.comb += [
                    self.in_fifo.w_data.eq(Event.READ),
                    self.in_fifo.w_en.eq(1),
                ]
                with m.If(self.in_fifo.w_rdy):
                    m.next = "RECV-READ-DATA"

            with m.State("RECV-READ-DATA"):
                with m.If(self.out_fifo.r_rdy):
                    m.d.comb += [
                        i2c_target.data_o.eq(self.out_fifo.r_data),
                        self.out_fifo.r_en.eq(1),
                    ]
                    m.next = "IDLE"

        return m


class I2CTargetInterface(metaclass=ABCMeta):
    def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, "I²C: " + message, *args)

    async def read_event(self):
        event, = await self.lower.read(1)
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
            data, = await self.lower.read(1)
            self._log("event write data=<%02x>", data)
            ack = await self.on_write(data)
            assert isinstance(ack, bool)
            self._log("write %s", "ack" if ack else "nak")
            await self.lower.write([ack])
        elif event == Event.READ:
            self._log("event read")
            data = await self.on_read()
            assert isinstance(data, int) and data in range(256)
            self._log("read data=<%02x>", data)
            await self.lower.write([data])
        else:
            assert False

    @abstractmethod
    async def on_start(self):
        pass

    @abstractmethod
    async def on_stop(self):
        pass

    @abstractmethod
    async def on_restart(self):
        pass

    @abstractmethod
    async def on_write(self, data):
        pass

    @abstractmethod
    async def on_read(self):
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


class I2CTargetApplet(GlasgowApplet, name="i2c-target"):
    logger = logging.getLogger(__name__)
    help = "accept I²C transactions"
    description = """
    Process transactions on the I²C bus as a software-defined target.

    This applet allows emulating any I²C device in Python, provided that the I²C initiator supports
    clock stretching and tolerates delays caused by host roundtrips. (Unfortunately, this excludes
    many I²C initiators.)

    The default emulated device is a dummy device that logs all transactions, acknowledges all
    writes, and returns 0xFF in response to all reads.
    """
    required_revision = "C0"

    __pins = ("scl", "sda")
    interface_cls = _DummyI2CTargetInterface

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in cls.__pins:
            access.add_pin_argument(parser, pin, default=True)

        def i2c_address(arg):
            return int(arg, 0)
        parser.add_argument(
            "-A", "--address", type=i2c_address, metavar="I2C-ADDR", required=True,
            help="I²C address of the target")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(I2CTargetSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(),
            address=args.address,
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
        return self.interface_cls(iface, self.logger)

    async def interact(self, device, args, iface):
        while True:
            await iface.read_event()

# -------------------------------------------------------------------------------------------------

class I2CTargetAppletTestCase(GlasgowAppletTestCase, applet=I2CTargetApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["-A", "0b1010000"])
