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
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2


__all__ = ["JTAGXVCComponent"]


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

    def __init__(self, ports):
        self._ports = ports

        super().__init__()

    def elaborate(self, platform):
        ioshape = {
            "tck": ("o", 1),
            "tms": ("o", 1),
            "tdi": ("o", 1),
            "tdo": ("i", 1),
        }

        m = Module()

        m.submodules.io_streamer = io_streamer = IOStreamer(ioshape, self._ports, meta_layout=1)

        timer = Signal.like(self.divisor)
        phase = Signal(5)
        last  = (phase + 1 == Cat(0, self.i_stream.p.len))
        m.d.comb += [
            io_streamer.o_stream.p.port.tck.oe.eq(1),
            io_streamer.o_stream.p.port.tck.o.eq(phase[0]),
            io_streamer.o_stream.p.port.tms.oe.eq(1),
            io_streamer.o_stream.p.port.tms.o.eq(self.i_stream.p.tms.bit_select(phase[1:], 1)),
            io_streamer.o_stream.p.port.tdi.oe.eq(1),
            io_streamer.o_stream.p.port.tdi.o.eq(self.i_stream.p.tdi.bit_select(phase[1:], 1)),
            io_streamer.o_stream.p.i_en.eq(phase[0] & (timer == 0)),
            io_streamer.o_stream.p.meta.eq(last),
        ]

        m.d.comb += io_streamer.o_stream.valid.eq(self.i_stream.valid)
        with m.If(self.i_stream.valid & io_streamer.o_stream.ready):
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
                m.d.sync += self.o_stream.p.tdo.bit_select(count, 1).eq(io_streamer.i_stream.p.port.tdo.i)
                m.d.comb += io_streamer.i_stream.ready.eq(1)
                with m.If(io_streamer.i_stream.valid):
                    m.d.sync += count.eq(count + 1)
                    with m.If(io_streamer.i_stream.p.meta):
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
    def __init__(self, logger, assembly, *, tck, tms, tdi, tdo):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        ports = assembly.add_port_group(tck=tck, tms=tms, tdi=tdi, tdo=tdo)
        component = assembly.add_submodule(JTAGXVCComponent(ports))
        self._pipe = assembly.add_inout_pipe(
            component.o_stream, component.i_stream, in_flush=component.o_flush)
        self._divisor = assembly.add_rw_register(component.divisor)
        self._sys_clk_period = assembly.sys_clk_period

    async def get_tck_period(self) -> int:
        """Get TCK period, in nanoseconds."""
        divisor = await self._divisor
        return round(1e9 * 2 * (divisor + 1) * self._sys_clk_period)

    async def set_tck_period(self, period: int):
        """Set TCK period, in nanoseconds."""
        await self._divisor.set(
            max(round(1e-9 * period / (2 * self._sys_clk_period) - 1), 0))

    async def shift(self, count: int, tms: bytes, tdi: bytes) -> bytes:
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
            help="override TCK frequency to always be FREQ kHz (default: %(default)s)")

    async def run(self, args):
        if args.frequency is not None:
            await self.xvc_iface.set_tck_period(round(1e6 / args.frequency))

        endpoint = await ServerEndpoint("socket", self.logger, args.endpoint)
        while True:
            command = await endpoint.recv_until(b":")
            self.logger.debug(f"cmd={command.decode('ascii')}")
            match command:
                case b"getinfo":
                    await endpoint.send(f"xvcServer_v1.0:{65535 // 8}\n".encode("ascii"))

                case b"settck":
                    tck_period, = struct.unpack("<L", await endpoint.recv(4))
                    self.logger.debug(f"  tck-i={tck_period}")
                    if args.frequency is None:
                        await self.xvc_iface.set_tck_period(tck_period)
                    tck_period = round(await self.xvc_iface.get_tck_period())
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

    @classmethod
    def tests(cls):
        from . import test
        return test.JTAGXVCAppletTestCase
