import logging
import asyncio
from amaranth import *
from amaranth.lib import wiring, stream, io, cdc
from amaranth.lib.wiring import In, Out

from glasgow.support.endpoint import ServerEndpoint
from glasgow.applet import GlasgowAppletV2


__all__ = []


class SWDOpenOCDComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))

    def __init__(self, ports, *, period_cyc, us_cyc):
        self._ports      = ports
        self._period_cyc = period_cyc
        self._us_cyc     = us_cyc

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        swclk    = Signal(init=1)
        swdio_i  = Signal()
        swdio_o  = Signal()
        swdio_oe = Signal()
        srst     = Signal()

        m.submodules.swclk = swclk_buffer = io.Buffer("o", self._ports.swclk)
        m.d.comb += swclk_buffer.o.eq(swclk)

        m.submodules.swdio = swdio_buffer = io.Buffer("io", self._ports.swdio)
        m.d.comb += [
            swdio_buffer.oe.eq(swdio_oe),
            swdio_buffer.o.eq(swdio_o)
        ]
        m.submodules += cdc.FFSynchronizer(swdio_buffer.i, swdio_i)

        if self._ports.srst is not None:
            m.submodules.srst = srst_buffer = io.Buffer("o", ~self._ports.srst)
            m.d.sync += srst_buffer.o.eq(srst)

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
                # remote_bitbang_swdio_drive(int is_output)
                with m.Case(*b"Oo"):
                    m.d.sync += swdio_oe.eq(~self.i_stream.payload[5])
                # remote_bitbang_swdio_read()
                with m.Case(*b"c"):
                    m.d.comb += self.i_stream.ready.eq(self.o_stream.ready)
                    m.d.comb += self.o_stream.valid.eq(1)
                    m.d.comb += self.o_stream.payload.eq(b"0"[0] | swdio_i)
                # remote_bitbang_swd_write(int swclk, int swdio)
                with m.Case(*b"defg"):
                    m.d.sync += Cat(swdio_o, swclk).eq(self.i_stream.payload[:2])
                    m.d.sync += timer.eq(self._period_cyc - 1)
                # remote_bitbang_reset(int trst, int srst)
                with m.Case(*b"rstu"):
                    m.d.sync += srst.eq((self.i_stream.payload - ord(b"r"))[1])
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


class SWDOpenOCDApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "expose SWD via OpenOCD remote bitbang interface"
    description = """
    Expose SWD via a socket using the OpenOCD remote bitbang protocol.

    Note (2024-07-22): SWD remote bitbang support has not yet been a part of an OpenOCD release,
    and OpenOCD must be built from source to use this applet.

    Usage with TCP sockets:

    ::

        glasgow run swd-openocd tcp:localhost:2222
        openocd -c 'adapter driver remote_bitbang; transport select swd' \\
            -c 'remote_bitbang port 2222'

    Usage with Unix domain sockets:

    ::

        glasgow run swd-openocd unix:/tmp/swd.sock
        openocd -c 'adapter driver remote_bitbang; transport select swd' \\
            -c 'remote_bitbang host /tmp/swd.sock'
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "swclk", required=True, default=True)
        access.add_pins_argument(parser, "swdio", required=True, default=True)
        access.add_pins_argument(parser, "srst")

        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=100,
            help="set SWCLK frequency to FREQ kHz (default: %(default)s)")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            ports = self.assembly.add_port_group(
                swclk=args.swclk, swdio=args.swdio, srst=args.srst
            )
            component = self.assembly.add_submodule(SWDOpenOCDComponent(ports,
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
        return test.SWDOpenOCDAppletTestCase
