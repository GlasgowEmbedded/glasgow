from typing import Literal, Optional
from functools import reduce
import sys
import logging
import asyncio
import argparse

from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io
from amaranth.lib.wiring import In, Out

from glasgow.gateware.ports import PortGroup
from glasgow.gateware.uart import UART
from glasgow.gateware.stream import Queue
from glasgow.abstract import AbstractAssembly, GlasgowPin, ClockDivisor
from glasgow.applet import GlasgowAppletV2, GlasgowAppletError


__all__ = ["UARTAnalyzerError", "UARTAnalyzerInterface"]


class UARTAnalyzerError(enum.Enum, shape=2):
    Good   = 0
    Frame  = 1
    Parity = 2


class UARTAnalyzerMessage(data.Struct):
    channel: 6
    error:   UARTAnalyzerError
    data:    8


class UARTAnalyzerComponent(wiring.Component):
    o_stream: Out(stream.Signature(8))
    o_flush:  Out(1)

    period:   In(20)
    overflow: Out(1)

    def __init__(self, port, parity):
        assert len(port) <= 64

        self._port   = port
        self._parity = parity

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        channels = []
        for index, pin in enumerate(self._port):
            m.submodules[f"ch{index}"] = uart = UART(PortGroup(rx=pin),
                bit_cyc=(1 << len(self.period)) - 1, parity=self._parity)
            m.d.comb += uart.bit_cyc.eq(self.period + 1)
            channels.append(uart)

        m.submodules.queue = queue = Queue(shape=UARTAnalyzerMessage, depth=512)

        with m.If(0):
            pass
        for index, channel in enumerate(channels):
            # Note: this condition violates the stream invariant in case of overflow.
            with m.If(channel.rx_rdy | channel.rx_ferr | channel.rx_perr):
                with m.If(channel.rx_ferr):
                    m.d.comb += queue.i.p.error.eq(UARTAnalyzerError.Frame)
                with m.If(channel.rx_perr):
                    m.d.comb += queue.i.p.error.eq(UARTAnalyzerError.Parity)
                m.d.comb += [
                    queue.i.p.data.eq(channel.rx_data),
                    queue.i.p.channel.eq(index),
                    queue.i.valid.eq(1),
                    channel.rx_ack.eq(queue.i.ready),
                ]
                with m.If(~queue.i.ready):
                    m.d.sync += self.overflow.eq(1)

        offset = Signal(1)
        m.d.comb += self.o_stream.payload.eq(queue.o.payload.as_value().word_select(offset, 8))
        m.d.comb += self.o_stream.valid.eq(queue.o.valid)
        with m.If(self.o_stream.valid & self.o_stream.ready):
            m.d.sync += offset.eq(offset + 1)
            with m.If(offset == 1):
                m.d.comb += queue.o.ready.eq(1)

        # TODO: remove this in favor of Nagle-like flush once that's implemented
        timer = Signal(16, init=127 if platform is None else ~0)
        m.d.comb += self.o_flush.eq(timer == 0)
        with m.If(self.o_stream.valid):
            m.d.sync += timer.eq(timer.init)
        with m.Elif(timer != 0):
            m.d.sync += timer.eq(timer - 1)

        return m


class UARTAnalyzerInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly,
                 channels: dict[str, Optional[GlasgowPin]], parity="none"):
        self._logger   = logger
        self._level    = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._channels = [channel for channel, pin in channels.items() if pin is not None]
        self._pins     = tuple(channels[name] for name in self._channels)

        assembly.use_pulls({self._pins: "high"})
        port = assembly.add_port(self._pins, name="uart")
        component = assembly.add_submodule(UARTAnalyzerComponent(port, parity=parity))
        self._pipe = assembly.add_in_pipe(component.o_stream, in_flush=component.o_flush)
        self._period = assembly.add_clock_divisor(component.period,
            ref_period=assembly.sys_clk_period, round_mode="nearest", name="baud")
        self._overflow = assembly.add_ro_register(component.overflow)

    def _log(self, message, *args):
        self._logger.log(self._level, "UART analyzer: " + message, *args)

    @property
    def baud(self) -> ClockDivisor:
        return self._period

    async def capture(self) -> list[tuple[str, bytearray | UARTAnalyzerError]]:
        if await self._overflow:
            raise GlasgowAppletError("overflow")

        results = []

        def add_data(channel, data):
            self._log(f"chan={channel} data={message.data:02x}")
            match results:
                case [*_, (last_channel, bytearray() as last_data)] if channel == last_channel:
                    last_data.append(data)
                case _:
                    results.append((channel, bytearray([data])))

        def add_error(channel, error):
            self._log(f"chan={channel} err={message.error.name}")
            results.append((channel, error))

        size = 2
        data = await self._pipe.recv((self._pipe.readable - (self._pipe.readable % size)) or size)
        for start in range(len(data))[::size]:
            message = UARTAnalyzerMessage.from_bits(
                int.from_bytes(data[start:start + size], "little"))
            channel = self._channels[message.channel]
            if message.error == UARTAnalyzerError.Good:
                add_data(channel, message.data)
            else:
                add_error(channel, message.error)

        return results


class UARTAnalyzerApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "analyze UART communication"
    description = """
    Capture data exchange on a full duplex UART link. The ``rx`` and ``tx`` pins are always inputs;
    they only affect the channel to which data is attributed.

    The capture file format is Comma Separated Values, in the following line formats:

    * ``<CH>,<DATA>``, where <CH> is ``rx`` or ``tx``, and <DATA> is a sequence of 8-bit
      hexadecimal values.
    * ``<CH>,#F``, where <CH> is the same as above, to indicate a frame error on this channel.
    * ``<CH>,#P``, where <CH> is the same as above, to indicate a parity error on this channel.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "rx", default=True)
        access.add_pins_argument(parser, "tx", default=True)
        parser.add_argument(
            "--parity", metavar="PARITY",
            choices=("none", "zero", "one", "odd", "even"), default="none",
            help="receive parity bit as PARITY (default: %(default)s)")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.uart_analyzer_iface = UARTAnalyzerInterface(self.logger, self.assembly,
                channels={"rx": args.rx, "tx": args.tx}, parity=args.parity)

    @classmethod
    def add_setup_arguments(cls, parser):
        parser.add_argument(
            "-b", "--baud", metavar="RATE", type=int, default=115200,
            help="set baud rate to RATE bits per second (default: %(default)s)")

    async def setup(self, args):
        await self.uart_analyzer_iface.baud.set_frequency(args.baud)

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument("file", metavar="FILE",
            type=argparse.FileType("w"), nargs="?", default=sys.stdout,
            help="save communications to FILE as comma separated values")

    async def run(self, args):
        try:
            args.file.truncate()
        except OSError:
            pass # pipe, tty/pty, etc

        while True:
            for channel, data in await self.uart_analyzer_iface.capture():
                match data:
                    case bytearray():
                        args.file.write(f"{channel},{data.hex()}\n")
                    case UARTAnalyzerError.Frame:
                        args.file.write(f"{channel},#F\n")
                    case UARTAnalyzerError.Parity:
                        args.file.write(f"{channel},#P\n")
                    case _:
                        assert False
            args.file.flush()

    @classmethod
    def tests(cls):
        from . import test
        return test.UARTAnalyzerAppletTestCase
