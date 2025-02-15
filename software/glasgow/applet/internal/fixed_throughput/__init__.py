import logging
import asyncio
import argparse
import time
from amaranth import *

from ... import *


class FixedThroughputSubtarget(Elaboratable):
    def __init__(self, rate_reg, in_fifo):
        self.rate_reg = rate_reg
        self.in_fifo = in_fifo

    def elaborate(self, platform):
        m = Module()

        data_rate_count = Signal(8)
        data_valid = Signal()
        data = Signal(8)
        overflow = Signal()

        m.d.comb += data.eq(Cat(overflow, Const(0, 7)))

        # delta sigma ish
        m.d.sync += Cat(data_rate_count, data_valid).eq(data_rate_count + self.rate_reg + 1)

        with m.If(data_valid):
            with m.If(self.in_fifo.w_rdy):
                m.d.comb += [
                    self.in_fifo.w_data.eq(data),
                    self.in_fifo.w_en.eq(1),
                ]
            with m.Else():
                m.d.sync += overflow.eq(1)

        return m


class FixedThroughputApplet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "evaluate fixed read throughput performance"
    description = """
    Evaluate fixed read throughput performance and check for in FIFO overflows 
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        pass

    def build(self, target, args):
        self.mux_interface = iface = \
            target.multiplexer.claim_interface(self, args=None, throttle="none")

        rate_reg, self.__addr_rate = target.registers.add_rw(8)

        subtarget = iface.add_subtarget(
            FixedThroughputSubtarget(
                rate_reg,
                iface.get_in_fifo(auto_flush=False)
            )
        )

    @classmethod
    def add_run_arguments(cls, parser, access):
        parser.add_argument(
            "--rpkts", metavar="READ-PACKETS", type=int,
            help="How many packets per read transfer")

        parser.add_argument(
            "--rxfers", metavar="READ-TRANSFERS", type=int,
            help="How many read transfers to have active at a time")

    async def run(self, device, args):
        kwargs = {}
        if args.rpkts is not None:
            kwargs["read_packets_per_xfer"] = args.rpkts
        if args.rxfers is not None:
            kwargs["read_xfers_per_queue"] = args.rxfers

        return await device.demultiplexer.claim_interface(self, self.mux_interface, args=None, **kwargs)

    @classmethod
    def add_interact_arguments(cls, parser):
        parser.add_argument(
            "rate_mbps", metavar="rate", type=float,
            help="data rate in Mbps")

    async def interact(self, device, args, iface):
        data_rate = round(args.rate_mbps/8 * 1e6 / 48e6 * 256) - 1
        await device.write_register(self.__addr_rate, data_rate)
        await iface.reset()

        try:
            count = 0
            begin = time.time()
            overflow = False

            while not overflow:
                data = await iface.read()
                data_list = list(data)

                count += len(data_list)
                overflow = 1 in data_list

        finally:
            duration = time.time() - begin
            mbps = count*8 / duration / 1e6
            expected_mbps = (data_rate+1)/256 * 8 * 48

            print(f"{overflow=}")
            print(f"Elapsed: {duration}")
            print(f"Mbps: {mbps}")
            print(f"Expected Mbps: {expected_mbps}")

    @classmethod
    def tests(cls):
        from . import test
        return test.FixedThroughputAppletTestCase
