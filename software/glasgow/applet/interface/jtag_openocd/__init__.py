import logging
import asyncio
from amaranth import *
from amaranth.lib import wiring, stream, io, cdc
from amaranth.lib.wiring import In, Out

from glasgow.support.endpoint import ServerEndpoint
from glasgow.applet import GlasgowAppletV2


__all__ = []


class JTAGOpenOCDComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))

    def __init__(self, ports, *, period_cyc, us_cyc):
        self._ports      = ports
        self._period_cyc = period_cyc
        self._us_cyc     = us_cyc

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        tck  = Signal()
        tms  = Signal()
        tdi  = Signal()
        tdo  = Signal()
        trst = Signal()
        srst = Signal()

        m.submodules.tck = tck_buffer = io.Buffer("o", self._ports.tck)
        m.d.comb += tck_buffer.o.eq(tck)
        m.submodules.tms = tms_buffer = io.Buffer("o", self._ports.tms)
        m.d.comb += tms_buffer.o.eq(tms)
        m.submodules.tdi = tdi_buffer = io.Buffer("o", self._ports.tdi)
        m.d.comb += tdi_buffer.o.eq(tdi)
        m.submodules.tdo = tdo_buffer = io.Buffer("i", self._ports.tdo)
        m.submodules += cdc.FFSynchronizer(tdo_buffer.i, tdo)
        if self._ports.trst is not None:
            m.submodules.trst = trst_buffer = io.Buffer("o", ~self._ports.trst)
            m.d.comb += trst_buffer.o.eq(trst)
        if self._ports.srst is not None:
            m.submodules.srst = srst_buffer = io.Buffer("o", ~self._ports.srst)
            m.d.comb += srst_buffer.o.eq(srst)

        blink = Signal()
        try:
            m.submodules.io_blink = io_blink = io.Buffer("o", platform.request("led", dir="-"))
            m.d.comb += io_blink.o.eq(blink)
        except:
            pass

        timer = Signal(range(max(self._period_cyc, 1000 * self._us_cyc)))
        with m.If(timer != 0):
            m.d.sync += timer.eq(timer - 1)
        with m.Elif(self.i_stream.valid):
            m.d.comb += self.i_stream.ready.eq(1)
            with m.Switch(self.i_stream.payload):
                # remote_bitbang_write(int tck, int tms, int tdi)
                with m.Case(*b"01234567"):
                    m.d.sync += Cat(tdi, tms, tck).eq(self.i_stream.payload[:3])
                    m.d.sync += timer.eq(self._period_cyc - 1)
                # remote_bitbang_reset(int trst, int srst)
                with m.Case(*b"rstu"):
                    m.d.sync += Cat(srst, trst).eq(self.i_stream.payload - b"r"[0])
                # remote_bitbang_sample(void)
                with m.Case(*b"R"):
                    m.d.comb += self.i_stream.ready.eq(self.o_stream.ready)
                    m.d.comb += self.o_stream.valid.eq(1)
                    m.d.comb += self.o_stream.payload.eq(b"0"[0] | tdo)
                # remote_bitbang_blink(int on)
                with m.Case(*b"Bb"):
                    m.d.sync += blink.eq(~self.i_stream.payload[5])
                # remote_bitbang_sleep(unsigned int microseconds)
                with m.Case(*b"Z"):
                    m.d.sync += timer.eq(1000 * self._us_cyc - 1)
                with m.Case(*b"z"):
                    m.d.sync += timer.eq(self._us_cyc - 1)
                # remote_bitbang_quit(void)
                with m.Case(*b"Q"):
                    pass
                with m.Default():
                    # Hang if an unknown command is received.
                    m.d.comb += self.i_stream.ready.eq(0)

        return m


class JTAGOpenOCDApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "expose JTAG via OpenOCD remote bitbang interface"
    description = """
    Expose JTAG via a socket using the OpenOCD remote bitbang protocol.

    Usage with TCP sockets:

    ::

        glasgow run jtag-openocd tcp:localhost:2222
        openocd -c 'adapter driver remote_bitbang; transport select jtag' \\
            -c 'remote_bitbang port 2222' \\
            -c 'reset_config none'

    Usage with Unix domain sockets:

    ::

        glasgow run jtag-openocd unix:/tmp/jtag.sock
        openocd -c 'adapter driver remote_bitbang; transport select jtag' \\
            -c 'remote_bitbang host /tmp/jtag.sock' \\
            -c 'reset_config none'

    If you use TRST# and/or SRST# pins, the 'reset_config none' option above must be
    replaced with 'reset_config trst', 'reset_config srst', or 'reset_config trst_and_srst'.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "tck", required=True, default=True)
        access.add_pins_argument(parser, "tms", required=True, default=True)
        access.add_pins_argument(parser, "tdi", required=True, default=True)
        access.add_pins_argument(parser, "tdo", required=True, default=True)
        access.add_pins_argument(parser, "trst")
        access.add_pins_argument(parser, "srst")

        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=100,
            help="set TCK frequency to FREQ kHz (default: %(default)s)")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            ports = self.assembly.add_port_group(
                tck=args.tck, tms=args.tms, tdi=args.tdi, tdo=args.tdo,
                trst=args.trst, srst=args.srst
            )
            component = self.assembly.add_submodule(JTAGOpenOCDComponent(ports,
                period_cyc=round(1 / (self.assembly.sys_clk_period * args.frequency * 1000)),
                us_cyc=round(1 / (self.assembly.sys_clk_period * 1_000_000)),
            ))
            self.__pipe = self.assembly.add_inout_pipe(component.o_stream, component.i_stream)

    @classmethod
    def add_run_arguments(cls, parser):
        ServerEndpoint.add_argument(parser, "endpoint")

    async def run(self, args):
        endpoint = await ServerEndpoint("socket", self.logger, args.endpoint)
        async def forward_out():
            while True:
                try:
                    data = await endpoint.recv()
                except EOFError:
                    continue
                await self.__pipe.send(data)
                await self.__pipe.flush()
        async def forward_in():
            while True:
                data = await self.__pipe.recv(self.__pipe.readable or 1)
                await endpoint.send(data)
        async with asyncio.TaskGroup() as group:
            group.create_task(forward_out())
            group.create_task(forward_in())

    @classmethod
    def tests(cls):
        from . import test
        return test.JTAGOpenOCDAppletTestCase
