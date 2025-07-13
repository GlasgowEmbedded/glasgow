import logging
import asyncio
import struct

from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io
from amaranth.lib.wiring import In, Out

from glasgow.support.logging import dump_hex
from glasgow.support.endpoint import ServerEndpoint
from glasgow.gateware.stream import StreamBuffer
from glasgow.gateware.iostream import IOStreamer
from glasgow.abstract import AbstractAssembly, GlasgowPin, ClockDivisor
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2


__all__ = ["JTAGXVCComponent", "JTAGXVCInterface"]


class _ShiftIn(enum.Enum, shape=unsigned(2)):
    Idle = 0
    More = 1
    Last = 2


class JTAGXVCProbe(wiring.Component):
    i_stream: In(stream.Signature(data.StructLayout({
        "len": 4,
        "tms": 8,
        "tdi": 8,
    })))
    o_stream: Out(stream.Signature(data.StructLayout({
        "tdo": 8,
    })))
    divisor:  In(16)

    def __init__(self, ports, *, offset=None):
        self._ports  = ports
        self._offset = offset

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.io_streamer = io_streamer = \
            IOStreamer(self._ports, meta_layout=_ShiftIn,
                # Offset sampling by ~10 ns to compensate for 10..15 ns of roundtrip delay caused by
                # the level shifters (5 ns each) and FPGA clock-to-out (5 ns).
                offset=1 if self._offset is None else self._offset
            )

        timer = Signal.like(self.divisor)
        phase = Signal(5)
        last  = (phase + 1 == Cat(0, self.i_stream.p.len))
        m.d.comb += [
            io_streamer.i.p.port.tck.oe.eq(1),
            io_streamer.i.p.port.tck.o.eq(phase[0]),
            io_streamer.i.p.port.tms.oe.eq(1),
            io_streamer.i.p.port.tms.o.eq(self.i_stream.p.tms.bit_select(phase[1:], 1)),
            io_streamer.i.p.port.tdi.oe.eq(1),
            io_streamer.i.p.port.tdi.o.eq(self.i_stream.p.tdi.bit_select(phase[1:], 1)),
        ]
        with m.If(phase[0] & (timer == 0)):
            m.d.comb += io_streamer.i.p.meta.eq(Mux(last, _ShiftIn.Last, _ShiftIn.More)),

        m.d.comb += io_streamer.i.valid.eq(self.i_stream.valid)
        with m.If(self.i_stream.valid & io_streamer.i.ready):
            with m.If(timer == self.divisor):
                m.d.sync += timer.eq(0)
                with m.If(last):
                    m.d.comb += self.i_stream.ready.eq(1)
                    m.d.sync += phase.eq(0)
                with m.Else():
                    m.d.sync += phase.eq(phase + 1)
            with m.Else():
                m.d.sync += timer.eq(timer + 1)

        count = Signal(4)
        with m.FSM():
            with m.State("More"):
                m.d.comb += io_streamer.o.ready.eq(1)
                with m.If(io_streamer.o.valid &
                        (io_streamer.o.p.meta != _ShiftIn.Idle)):
                    m.d.sync += count.eq(count + 1)
                    m.d.sync += self.o_stream.p.tdo.bit_select(count, 1).eq(
                        io_streamer.o.p.port.tdo.i)
                    with m.If(io_streamer.o.p.meta == _ShiftIn.Last):
                        m.next = "Last"

            with m.State("Last"):
                m.d.comb += self.o_stream.valid.eq(1)
                with m.If(self.o_stream.ready):
                    m.d.sync += count.eq(0)
                    m.next = "More"

        return m


class JTAGXVCComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))
    o_flush:  Out(1)
    divisor:  In(16)

    def __init__(self, ports):
        self._ports = ports

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.xvc_probe = xvc_probe = JTAGXVCProbe(self._ports)
        m.d.comb += xvc_probe.divisor.eq(self.divisor)

        m.submodules.buffer = buffer = StreamBuffer(xvc_probe.i_stream.p.shape())
        wiring.connect(m, xvc_probe.i_stream, buffer.o)

        count = Signal(16)
        with m.FSM():
            with m.State("Receive Count 8:16"):
                m.d.comb += self.o_flush.eq(1)
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    m.d.sync += count[8:16].eq(self.i_stream.payload)
                    m.next = "Receive Count 0:8"

            with m.State("Receive Count 0:8"):
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    m.d.sync += count[0:8].eq(self.i_stream.payload)
                    m.next = "Receive TMS Byte"

            with m.State("Receive TMS Byte"):
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    m.d.sync += buffer.i.p.tms.eq(self.i_stream.payload)
                    m.next = "Receive TDI Byte"

            with m.State("Receive TDI Byte"):
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    m.d.sync += buffer.i.p.tdi.eq(self.i_stream.payload)
                    m.next = "Submit"

            with m.State("Submit"):
                m.d.comb += buffer.i.valid.eq(1)
                with m.If(count > 8):
                    m.d.comb += buffer.i.p.len.eq(8)
                    with m.If(buffer.i.ready):
                        m.d.sync += count.eq(count - 8)
                        m.next = "Receive TMS Byte"
                with m.Else():
                    m.d.comb += buffer.i.p.len.eq(count)
                    with m.If(buffer.i.ready):
                        m.d.sync += count.eq(0)
                        m.next = "Receive Count 8:16"

        wiring.connect(m, wiring.flipped(self.o_stream), xvc_probe.o_stream)

        return m


class JTAGXVCInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *, tck: GlasgowPin,
                 tms: GlasgowPin, tdi: GlasgowPin, tdo: GlasgowPin):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        ports = assembly.add_port_group(tck=tck, tms=tms, tdi=tdi, tdo=tdo)
        component = assembly.add_submodule(JTAGXVCComponent(ports))
        self._pipe = assembly.add_inout_pipe(
            component.o_stream, component.i_stream, in_flush=component.o_flush)
        self._clock = assembly.add_clock_divisor(component.divisor,
            # Tolerance is 10% because the XVC protocol transfers frequencies as an integral period
            # in nanoseconds. For frequencies >1 MHz this often results in a significant error.
            ref_period=assembly.sys_clk_period * 2, tolerance=0.1, name="tck")

    @property
    def clock(self) -> ClockDivisor:
        """TCK clock divisor."""
        return self._clock

    async def shift(self, count: int, tms: bytes, tdi: bytes) -> bytes:
        """Shift :py:`count` cycles.

        State of TMS and TDI is taken from :py:`tms` and :py:`tdi`, where the LSB of the 0th byte
        is transmitted first; state of TDO is serialized in the same way and returned.
        """
        assert len(tms) == len(tdi) == (count + 7) // 8 and count > 0
        request = bytearray(2 + len(tms) + len(tdi))
        request[0:2:] = struct.pack(">H", count)
        request[2::2] = tms
        request[3::2] = tdi
        await self._pipe.send(request)
        await self._pipe.flush()
        response = await self._pipe.recv(len(tdi))
        return response


class JTAGXVCApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "expose JTAG via Xilinx Virtual Cable interface"
    description = """
    Expose JTAG via a socket using the Xilinx Virtual Cable protocol, version 1.0.

    To connect to the DUT in Vivado, use the following Tcl command:

    ::

        open_hw_target -xvc_url localhost:2542
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "tck", required=True, default=True)
        access.add_pins_argument(parser, "tms", required=True, default=True)
        access.add_pins_argument(parser, "tdi", required=True, default=True)
        access.add_pins_argument(parser, "tdo", required=True, default=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.xvc_iface = JTAGXVCInterface(self.logger, self.assembly,
                tck=args.tck, tms=args.tms, tdi=args.tdi, tdo=args.tdo)

    @classmethod
    def add_run_arguments(cls, parser):
        ServerEndpoint.add_argument(parser, "endpoint", default="tcp:localhost:2542")

        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=None,
            help="override TCK frequency to always be FREQ kHz (default: configured by client)")

    async def run(self, args):
        if args.frequency is not None:
            await self.xvc_iface.clock.set_frequency(args.frequency)

        endpoint = await ServerEndpoint("socket", self.logger, args.endpoint)
        while True:
            try:
                command = await endpoint.recv_until(b":")
                self.logger.debug(f"cmd={command.decode('ascii')}")
                match command:
                    case b"getinfo":
                        await endpoint.send(f"xvcServer_v1.0:{65535 // 8}\n".encode("ascii"))

                    case b"settck":
                        tck_period, = struct.unpack("<L", await endpoint.recv(4))
                        self.logger.debug(f"  tck-i={tck_period}") # in nanoseconds
                        if args.frequency is None:
                            await self.xvc_iface.clock.set_frequency(1e9 / tck_period)
                        tck_period = round(1e9 / await self.xvc_iface.clock.get_frequency())
                        self.logger.debug(f"  tck-o={tck_period}")
                        await endpoint.send(struct.pack("<L", tck_period))

                    case b"shift":
                        bit_count, = struct.unpack("<L", await endpoint.recv(4))
                        self.logger.debug(f"  count={bit_count}")
                        byte_count = (bit_count + 7) // 8
                        tms_bytes = await endpoint.recv(byte_count)
                        self.logger.debug("  tms=<%s>", dump_hex(tms_bytes))
                        tdi_bytes = await endpoint.recv(byte_count)
                        self.logger.debug("  tdi=<%s>", dump_hex(tdi_bytes))
                        tdo_bytes = await self.xvc_iface.shift(bit_count, tms_bytes, tdi_bytes)
                        self.logger.debug("  tdo=<%s>", dump_hex(tdo_bytes))
                        await endpoint.send(tdo_bytes)

                    case command:
                        raise GlasgowAppletError(f"unrecognized command {command!r}")

            except EOFError:
                pass

    @classmethod
    def tests(cls):
        from . import test
        return test.JTAGXVCAppletTestCase
