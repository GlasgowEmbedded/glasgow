import struct
import logging
import asyncio
from amaranth import *
from amaranth.lib import io, cdc

from ....support.bits import *
from ....support.logging import *
from ....support.endpoint import *
from ... import *


class JTAGOpenOCDSubtarget(Elaboratable):
    def __init__(self, ports, out_fifo, in_fifo, period_cyc, us_cyc):
        self._ports      = ports
        self._out_fifo   = out_fifo
        self._in_fifo    = in_fifo
        self._period_cyc = period_cyc
        self._us_cyc     = us_cyc

    def elaborate(self, platform):
        m = Module()

        tck = Signal()
        tms = Signal()
        tdi = Signal()
        tdo = Signal()
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
        with m.Else():
            with m.If(self._out_fifo.r_rdy):
                m.d.comb += self._out_fifo.r_en.eq(1)
                with m.Switch(self._out_fifo.r_data):
                    # remote_bitbang_write(int tck, int tms, int tdi)
                    with m.Case(*b"01234567"):
                        m.d.sync += Cat(tdi, tms, tck).eq(self._out_fifo.r_data[:3])
                        m.d.sync += timer.eq(self._period_cyc - 1)
                    # remote_bitbang_reset(int trst, int srst)
                    with m.Case(*b"rstu"):
                        m.d.sync += Cat(srst, trst).eq(self._out_fifo.r_data - b"r"[0])
                    # remote_bitbang_sample(void)
                    with m.Case(*b"R"):
                        m.d.comb += self._out_fifo.r_en.eq(self._in_fifo.w_rdy)
                        m.d.comb += self._in_fifo.w_en.eq(1)
                        m.d.comb += self._in_fifo.w_data.eq(b"0"[0] | tdo)
                    # remote_bitbang_blink(int on)
                    with m.Case(*b"Bb"):
                        m.d.sync += blink.eq(~self._out_fifo.r_data[5])
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
                        m.d.comb += self._out_fifo.r_en.eq(0)

        return m


class JTAGOpenOCDApplet(GlasgowApplet):
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
        super().add_build_arguments(parser, access)

        for name in ("tck", "tms", "tdi", "tdo"):
            access.add_pins_argument(parser, name, default=True)
        for name in ("trst", "srst"):
            access.add_pins_argument(parser, name)

        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=100,
            help="set TCK frequency to FREQ kHz (default: %(default)s)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(JTAGOpenOCDSubtarget(
            ports=iface.get_port_group(
                tck=args.tck,
                tms=args.tms,
                tdi=args.tdi,
                tdo=args.tdo,
                trst=args.trst,
                srst=args.srst,
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
                except EOFError:
                    continue
                await iface.write(data)
                await iface.flush()
        async def forward_in():
            while True:
                data = await iface.read()
                await endpoint.send(data)
        async with asyncio.TaskGroup() as group:
            group.create_task(forward_out())
            group.create_task(forward_in())

    @classmethod
    def tests(cls):
        from . import test
        return test.JTAGOpenOCDAppletTestCase
