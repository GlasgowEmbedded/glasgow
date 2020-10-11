import enum
import asyncio
import logging
from functools import reduce
from nmigen import *
from nmigen.lib.cdc import FFSynchronizer

from ....gateware.pads import *
from ....support.si_prefix import num_to_si
from ... import *

class _Command(enum.IntEnum):
    COUNT = 0x00


class FreqCounter(Elaboratable):
    def __init__(self, signal_in, trigger, busy, count, cyc_lo, cyc_hi, edge="r"):
        self.signal_in = signal_in
        self.trigger = trigger
        self.busy = busy
        self.count = count
        self.cyc_lo = cyc_lo
        self.cyc_hi = cyc_hi
        self.edge = edge

    def elaborate(self, platform):
        m = Module()

        f_edge = Signal(2)
        m.d.sync += f_edge.eq(Cat(self.signal_in, f_edge[:-1]))

        f_start = Signal()
        if self.edge in ("r", "rising"):
            m.d.comb += f_start.eq(f_edge == 0b01)
        elif self.edge in ("f", "falling"):
            m.d.comb += f_start.eq(f_edge == 0b10)
        else:
            assert False

        count_t = Signal.like(self.count)

        cyc = Array([ self.cyc_lo, self.cyc_hi ])[self.signal_in]

        with m.FSM() as fsm:
            m.d.comb += self.busy.eq(~fsm.ongoing("IDLE"))

            with m.State("IDLE"):
                with m.If(self.trigger):
                    m.d.sync += [
                        count_t.eq(self.count),
                        self.cyc_lo.eq(0),
                        self.cyc_hi.eq(0),
                    ]
                    m.next = "COUNT-WAIT"

            with m.State("COUNT-WAIT"):
                with m.If(f_start):
                    m.next = "COUNT-RUN"

            with m.State("COUNT-RUN"):
                m.d.sync += cyc.eq(cyc + 1)
                with m.If(f_start):
                    m.d.sync += count_t.eq(count_t - 1)
                with m.If(count_t == 0):
                    m.next = "IDLE"

        return m


class FreqCounterSubtarget(Elaboratable):
    def __init__(self, pads, out_fifo, reg_busy, reg_count, reg_cyc_lo, reg_cyc_hi, edge="r"):
        self.pads =  pads
        self.out_fifo = out_fifo
        self.reg_busy = reg_busy
        self.reg_count = reg_count
        self.reg_cyc_lo = reg_cyc_lo
        self.reg_cyc_hi = reg_cyc_hi
        self.edge = edge

    def elaborate(self, platform):
        m = Module()

        signal_in = Signal.like(self.pads.f_t.i)
        m.submodules += FFSynchronizer(self.pads.f_t.i, signal_in)

        trigger = Signal()

        m.d.comb += [
            self.out_fifo.r_en.eq(self.out_fifo.r_rdy),
            trigger.eq(self.out_fifo.r_en & (self.out_fifo.r_data == _Command.COUNT)),
        ]

        m.submodules += FreqCounter(
            signal_in=signal_in,
            trigger=trigger,
            busy=self.reg_busy,
            count=self.reg_count,
            cyc_lo=self.reg_cyc_lo,
            cyc_hi=self.reg_cyc_hi,
            edge=self.edge
        )

        return m


class FreqCounterApplet(GlasgowApplet, name="freq-counter"):
    logger = logging.getLogger(__name__)
    help = "frequency counter"
    description = """
    Monitor a signal for frequency and duty cycle.
    """

    __pins = ("f")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in cls.__pins:
            access.add_pin_argument(parser, pin, default=True)

        parser.add_argument(
            "--edge", metavar="EDGE", type=str, choices=["r", "rising", "f", "falling"],
            default="rising",
            help="begin counting from the given EDGE (default: %(default)s)")

    def build(self, target, args):
        self.sys_clk_freq = target.sys_clk_freq
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)

        reg_busy,   self.__reg_busy   = target.registers.add_ro(1)
        reg_count,  self.__reg_count  = target.registers.add_rw(32)
        reg_cyc_lo, self.__reg_cyc_lo = target.registers.add_ro(32)
        reg_cyc_hi, self.__reg_cyc_hi = target.registers.add_ro(32)

        iface.add_subtarget(FreqCounterSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            reg_busy=reg_busy,
            reg_count=reg_count,
            reg_cyc_lo=reg_cyc_lo,
            reg_cyc_hi=reg_cyc_hi,
            edge=args.edge,
        ))

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

        parser.add_argument(
            "-c", "--count", metavar="COUNT", type=int, default=256,
            help="the number of edges to count")

    async def wait_for_idle(self, device, timeout=10):
        for i in range(timeout * 10):
            if not await device.read_register(self.__reg_busy, width=1):
                return

            await asyncio.sleep(0.1)

        raise TimeoutError("Timeout while waiting for counter to return to idle")

    async def run(self, device, args):
        rising_edge = args.edge in ("r", "rising")

        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)

        await self.wait_for_idle(device)

        await device.write_register(self.__reg_count, args.count, width=4)
        await iface.write([ _Command.COUNT ])
        await iface.flush()

        await self.wait_for_idle(device)

        cyc_lo = await device.read_register(self.__reg_cyc_lo, width=4)
        cyc_hi = await device.read_register(self.__reg_cyc_hi, width=4)
        cyc_t  = cyc_lo + cyc_hi

        sys_clk_period = 1 / self.sys_clk_freq
        duration = sys_clk_period * cyc_t

        frequency = (self.sys_clk_freq / cyc_t) * args.count
        period = 1 / frequency

        t_lo = sys_clk_period * (cyc_lo / args.count)
        t_hi = sys_clk_period * (cyc_hi / args.count)

        if rising_edge:
            duty = cyc_hi / cyc_t
        else:
            duty = cyc_lo / cyc_t

        print('Duration:         {:>7.3f} {:1}s  / {:>7} cycles'.format(*num_to_si(duration), args.count))
        print('Frequency:        {:>7.3f} {:1}Hz / {:>7.3f} {:1}s'.format(*num_to_si(frequency), *num_to_si(period)))
        if rising_edge:
            print('Time High / Low:  {:>7.3f} {:1}s  / {:>7.3f} {:1}s'.format(*num_to_si(t_hi), *num_to_si(t_lo)))
        else:
            print('Time Low / High:  {:>7.3f} {:1}s  / {:>7.3f} {:1}s'.format(*num_to_si(t_lo), *num_to_si(t_hi)))
        print('Duty Cycle:       {:>7.3f} %'.format(duty * 100))

# -------------------------------------------------------------------------------------------------

class FreqCounterTestCase(GlasgowAppletTestCase, applet=FreqCounterApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
