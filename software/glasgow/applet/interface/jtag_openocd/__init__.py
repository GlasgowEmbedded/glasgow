import struct
import logging
import asyncio
from nmigen import *

from ....support.bits import *
from ....support.logging import *
from ....support.endpoint import *
from ....gateware.pads import *
from ....database.jedec import *
from ....arch.jtag import *
from ... import *
from ..jtag_probe import JTAGProbeBus


class JTAGOpenOCDSubtarget(Elaboratable):
    def __init__(self, pads, out_fifo, in_fifo, period_cyc):
        self.pads       = pads
        self.out_fifo   = out_fifo
        self.in_fifo    = in_fifo
        self.period_cyc = period_cyc

    def elaborate(self, platform):
        m = Module()

        out_fifo = self.out_fifo
        in_fifo  = self.in_fifo

        m.submodules.bus = bus = JTAGProbeBus(self.pads)
        m.d.comb += [
            bus.trst_z.eq(0),
        ]

        blink = Signal()

        timer = Signal(range(self.period_cyc))

        with m.If(timer != 0):
            m.d.sync += timer.eq(timer - 1)
        with m.Else():
            with m.If(out_fifo.r_rdy):
                with m.Switch(out_fifo.r_data):
                    m.d.comb += out_fifo.r_en.eq(1)
                    # remote_bitbang_write(int tck, int tms, int tdi)
                    with m.Case(*b"01234567"):
                        m.d.sync += Cat(bus.tdi, bus.tms, bus.tck).eq(out_fifo.r_data[:3])
                    # remote_bitbang_reset(int trst, int srst)
                    with m.Case(*b"rs"):
                        m.d.sync += Cat(bus.trst_o).eq(0b0)
                    with m.Case(*b"tu"):
                        m.d.sync += Cat(bus.trst_o).eq(0b1)
                    # remote_bitbang_sample(void)
                    with m.Case(*b"R"):
                        m.d.comb += out_fifo.r_en.eq(in_fifo.w_rdy)
                        m.d.comb += in_fifo.w_en.eq(1)
                        m.d.comb += in_fifo.w_data.eq(b"0"[0] | Cat(bus.tdo))
                    # remote_bitbang_blink(int on)
                    with m.Case(*b"Bb"):
                        m.d.sync += blink.eq(~out_fifo.r_data[5])
                    # remote_bitbang_quit(void)
                    with m.Case(*b"Q"):
                        pass
                    with m.Default():
                        m.d.comb += out_fifo.r_en.eq(0)
                with m.If(out_fifo.r_en):
                    m.d.sync += timer.eq(self.period_cyc - 1)

        return m


class JTAGOpenOCDApplet(GlasgowApplet, name="jtag-openocd"):
    logger = logging.getLogger(__name__)
    help = "expose JTAG via OpenOCD remote bitbang interface"
    description = """
    Expose JTAG via a socket using the OpenOCD remote bitbang protocol.

    Usage with TCP sockets:

    ::
        glasgow run jtag-openocd tcp:localhost:2222
        openocd -c 'interface remote_bitbang; remote_bitbang_port 2222'

    Usage with Unix domain sockets:

    ::
        glasgow run jtag-openocd unix:/tmp/jtag.sock
        openocd -c 'interface remote_bitbang; remote_bitbang_host /tmp/jtag.sock'
    """

    __pins = ("tck", "tms", "tdi", "tdo", "trst")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in ("tck", "tms", "tdi", "tdo"):
            access.add_pin_argument(parser, pin, default=True)
        access.add_pin_argument(parser, "trst")

        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=100,
            help="set TCK frequency to FREQ kHz (default: %(default)s)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(JTAGOpenOCDSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(),
            period_cyc=int(target.sys_clk_freq // (args.frequency * 1000)),
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

# -------------------------------------------------------------------------------------------------

class JTAGOpenOCDAppletTestCase(GlasgowAppletTestCase, applet=JTAGOpenOCDApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
