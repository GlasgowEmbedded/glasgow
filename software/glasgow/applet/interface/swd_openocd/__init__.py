import struct
import logging
import asyncio
from amaranth import *
from amaranth.lib import io
from amaranth.lib.cdc import FFSynchronizer

from ....support.bits import *
from ....support.logging import *
from ....support.endpoint import *
from ... import *


# Will eventually live in `..swd_probe`.
class SWDProbeBus(Elaboratable):
    def __init__(self, ports):
        self.ports = ports
        self.swclk = Signal(init=1)
        self.swdio_i = Signal()
        self.swdio_o = Signal()
        self.swdio_z = Signal()

    def elaborate(self, platform):
        m = Module()
        m.submodules.swclk = swclk_buffer = io.Buffer("o", self.ports.swclk)
        m.submodules.swdio = swdio_buffer = io.Buffer("io", self.ports.swdio)
        m.d.comb += [
            swclk_buffer.o.eq(self.swclk),
            swdio_buffer.oe.eq(~self.swdio_z),
            swdio_buffer.o.eq(self.swdio_o)
        ]
        m.submodules += [
            FFSynchronizer(swdio_buffer.i, self.swdio_i),
        ]
        return m


class SWDOpenOCDSubtarget(Elaboratable):
    def __init__(self, ports, out_fifo, in_fifo, period_cyc, us_cyc):
        self.ports      = ports
        self.out_fifo   = out_fifo
        self.in_fifo    = in_fifo
        self.period_cyc = period_cyc
        self.us_cyc     = us_cyc
        self.srst_z     = Signal(init=0)
        self.srst_o     = Signal(init=0)

    def elaborate(self, platform):
        m = Module()

        out_fifo = self.out_fifo
        in_fifo  = self.in_fifo

        m.submodules.bus = bus = SWDProbeBus(self.ports)
        m.d.comb += [
            self.srst_z.eq(0),
        ]
        if self.ports.srst is not None:
            m.submodules.srst_buffer = srst_buffer = io.Buffer("o")
            m.d.sync += [
                srst_buffer.oe.eq(~self.srst_z),
                srst_buffer.o.eq(~self.srst_o)
            ]

        blink = Signal()
        try:
            m.submodules.io_blink = io_blink = io.Buffer("o", platform.request("led", dir="-"))
            m.d.comb += io_blink.o.eq(blink)
        except:
            pass

        timer = Signal(range(max(self.period_cyc, 1000 * self.us_cyc)))
        with m.If(timer != 0):
            m.d.sync += timer.eq(timer - 1)
        with m.Else():
            with m.If(out_fifo.r_rdy):
                m.d.comb += out_fifo.r_en.eq(1)
                with m.Switch(out_fifo.r_data):
                    # remote_bitbang_swdio_drive(int is_output)
                    with m.Case(*b"Oo"):
                        m.d.sync += bus.swdio_z.eq(out_fifo.r_data[5])
                    # remote_bitbang_swdio_read()
                    with m.Case(*b"c"):
                        m.d.comb += out_fifo.r_en.eq(in_fifo.w_rdy)
                        m.d.comb += in_fifo.w_en.eq(1)
                        m.d.comb += in_fifo.w_data.eq(b"0"[0] | Cat(bus.swdio_i))
                    # remote_bitbang_swd_write(int swclk, int swdio)
                    with m.Case(*b"defg"):
                        m.d.sync += Cat(bus.swdio_o, bus.swclk).eq(out_fifo.r_data[:2])
                        m.d.sync += timer.eq(self.period_cyc - 1)
                    # remote_bitbang_reset(int trst, int srst)
                    with m.Case(*b"rstu"):
                        m.d.sync += self.srst_o.eq(out_fifo.r_data - ord(b"r"))
                    # remote_bitbang_blink(int on)
                    with m.Case(*b"Bb"):
                        m.d.sync += blink.eq(~out_fifo.r_data[5])
                    # remote_bitbang_sleep(unsigned int microseconds)
                    with m.Case(*b"Z"):
                        m.d.sync += timer.eq(1000 * self.us_cyc - 1)
                    with m.Case(*b"z"):
                        m.d.sync += timer.eq(self.us_cyc - 1)
                    # remote_bitbang_quit(void)
                    with m.Case(*b"Q"):
                        pass
                    with m.Default():
                        # Hang if an unknown command is received.
                        m.d.comb += out_fifo.r_en.eq(0)

        return m


class SWDOpenOCDApplet(GlasgowApplet):
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
        super().add_build_arguments(parser, access)

        access.add_pin_argument(parser, "swclk", default=True)
        access.add_pin_argument(parser, "swdio", default=True)

        access.add_pin_argument(parser, "srst")

        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=100,
            help="set SWCLK frequency to FREQ kHz (default: %(default)s)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(SWDOpenOCDSubtarget(
            ports=iface.get_port_group(
                swclk = args.pin_swclk,
                swdio = args.pin_swdio,
                srst  = args.pin_srst
            ),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(),
            period_cyc=int(target.sys_clk_freq // (args.frequency * 1000)),
            us_cyc=int(target.sys_clk_freq // 1_000_000),
        ))

    async def run(self, device, args):
        return await device.demultiplexer.claim_interface(self, self.mux_interface, args)

    @classmethod
    def add_interact_arguments(cls, parser):
        ServerEndpoint.add_argument(parser, "endpoint")

    async def interact(self, device, args, iface):
        endpoint = await ServerEndpoint("socket", self.logger, args.endpoint)
        async def forward_out():
            while True:
                try:
                    data = await endpoint.recv()
                    await iface.write(data)
                    await iface.flush()
                except asyncio.CancelledError:
                    pass
        async def forward_in():
            while True:
                try:
                    data = await iface.read()
                    await endpoint.send(data)
                except asyncio.CancelledError:
                    pass
        forward_out_fut = asyncio.ensure_future(forward_out())
        forward_in_fut  = asyncio.ensure_future(forward_in())
        await asyncio.wait([forward_out_fut, forward_in_fut],
                           return_when=asyncio.FIRST_EXCEPTION)

    @classmethod
    def tests(cls):
        from . import test
        return test.SWDOpenOCDAppletTestCase
