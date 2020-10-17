import enum
import asyncio
import logging
from functools import reduce
from nmigen import *
from nmigen.lib.cdc import FFSynchronizer

from ....gateware.pads import *
from ....gateware.pll import *
from ....support.si_prefix import num_to_si
from ... import *

class _Command(enum.IntEnum):
    COUNT = 0x00


class FreqCounter(Elaboratable):
    def __init__(self, signal_in, trigger, busy, count, counters, edge="r", domain="sync"):
        self.signal_in = signal_in
        self.trigger = trigger
        self.busy = busy
        self.count = count
        self.counters = counters
        self.edge = edge
        self.domain = domain

    def elaborate(self, platform):
        m = Module()

        f_edge = Signal(2)
        m.d[self.domain] += f_edge.eq(Cat(self.signal_in, f_edge[:-1]))

        f_start = Signal()
        if self.edge in ("r", "rising"):
            m.d.comb += f_start.eq(f_edge == 0b01)
        elif self.edge in ("f", "falling"):
            m.d.comb += f_start.eq(f_edge == 0b10)
        else:
            assert False

        count_t = Signal.like(self.count)

        cyc = Array(self.counters["total"])[self.signal_in]

        cyc_cur_lo = Signal.like(self.counters["total"][0])
        cyc_cur_hi = Signal.like(self.counters["total"][1])
        cyc_cur_v = Array([ cyc_cur_lo, cyc_cur_hi ])
        cyc_cur = cyc_cur_v[self.signal_in]

        with m.FSM(domain=self.domain) as fsm:
            m.d.comb += self.busy.eq(~fsm.ongoing("IDLE"))

            with m.State("IDLE"):
                with m.If(self.trigger):
                    m.d[self.domain] += [
                        count_t.eq(self.count),
                        cyc_cur_lo.eq(0),
                        cyc_cur_hi.eq(0),
                        self.counters["total"][0].eq( 0), self.counters["total"][1].eq( 0),
                        self.counters["min_l"][0].eq(~0), self.counters["min_l"][1].eq(~0),
                        self.counters["max_l"][0].eq( 0), self.counters["max_l"][1].eq( 0),
                        self.counters["min_h"][0].eq(~0), self.counters["min_h"][1].eq(~0),
                        self.counters["max_h"][0].eq( 0), self.counters["max_h"][1].eq( 0),
                    ]
                    m.next = "COUNT-WAIT"

            with m.State("COUNT-WAIT"):
                with m.If(f_start):
                    m.next = "COUNT-RUN"

            with m.State("COUNT-RUN"):
                m.d[self.domain] += [
                    cyc.eq(cyc + 1),
                    cyc_cur.eq(cyc_cur + 1),
                ]

                with m.If(f_start):
                    m.d[self.domain] += [
                        count_t.eq(count_t - 1),
                        cyc_cur_lo.eq(0),
                        cyc_cur_hi.eq(0),
                    ]

                    for k, lvl, lt in (
                        ( "min_l", 0, True  ),
                        ( "max_l", 0, False ),
                        ( "min_h", 1, True  ),
                        ( "max_h", 1, False ),
                    ):
                        cyc_cur_x = cyc_cur_v[lvl]
                        counter_x = self.counters[k][lvl]
                        with m.If(cyc_cur_x < counter_x if lt else cyc_cur_x > counter_x):
                            m.d[self.domain] += [
                                self.counters[k][0].eq(cyc_cur_v[0]),
                                self.counters[k][1].eq(cyc_cur_v[1]),
                            ]

                with m.If(count_t == 0):
                    m.next = "IDLE"

        return m


class FreqCounterSubtarget(Elaboratable):
    def __init__(self, pads, out_fifo, reg_busy, reg_count, counters, sys_clk_freq, pll_out_freq, edge="r"):
        self.pads =  pads
        self.out_fifo = out_fifo
        self.reg_busy = reg_busy
        self.reg_count = reg_count
        self.counters = counters
        self.sys_clk_freq = sys_clk_freq
        self.pll_out_freq = pll_out_freq
        self.edge = edge

    def elaborate(self, platform):
        m = Module()

        m.domains += ClockDomain("samp")
        m.submodules += PLL(f_in=self.sys_clk_freq, f_out=self.pll_out_freq, odomain="samp")

        signal_in = Signal.like(self.pads.f_t.i)
        m.submodules += FFSynchronizer(self.pads.f_t.i, signal_in, o_domain="samp")

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
            counters=self.counters,
            edge=self.edge,
            domain="samp",
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
        self.pll_out_freq = 100e6
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)

        reg_busy,  self.__reg_busy  = target.registers.add_ro(1)
        reg_count, self.__reg_count = target.registers.add_rw(32)

        counter_regs = {
            "total": ( target.registers.add_ro(32), target.registers.add_ro(32) ),
            "min_l": ( target.registers.add_ro(32), target.registers.add_ro(32) ),
            "max_l": ( target.registers.add_ro(32), target.registers.add_ro(32) ),
            "min_h": ( target.registers.add_ro(32), target.registers.add_ro(32) ),
            "max_h": ( target.registers.add_ro(32), target.registers.add_ro(32) ),
        }
        counters        = { k: [ _[0] for _ in v ] for k,v in counter_regs.items() }
        self.__counters = { k: [ _[1] for _ in v ] for k,v in counter_regs.items() }

        iface.add_subtarget(FreqCounterSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            reg_busy=reg_busy,
            reg_count=reg_count,
            counters=counters,
            sys_clk_freq=self.sys_clk_freq,
            pll_out_freq=self.pll_out_freq,
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

    async def get_result_series(self, device, rising_edge, count, reg_cyc_lo, reg_cyc_hi):
        cyc_lo = await device.read_register(reg_cyc_lo, width=4)
        cyc_hi = await device.read_register(reg_cyc_hi, width=4)
        cyc_t  = cyc_lo + cyc_hi

        sys_clk_period = 1 / self.pll_out_freq
        duration = sys_clk_period * cyc_t

        frequency = (self.pll_out_freq / cyc_t) * count
        period = 1 / frequency

        t_lo = sys_clk_period * (cyc_lo / count)
        t_hi = sys_clk_period * (cyc_hi / count)
        t_t = t_lo + t_hi

        if rising_edge:
            duty = cyc_hi / cyc_t
        else:
            duty = cyc_lo / cyc_t

        return {
            "count": count,
            "duration": duration, "frequency": frequency,
            "cyc_lo": cyc_lo, "cyc_hi": cyc_hi, "cyc_total": cyc_t,
            "t_lo":   t_lo,   "t_hi":   t_hi,   "t_total":   t_t,
            "duty": duty * 100.0,
        }

    async def get_results(self, device, rising_edge, args):
        results = {
            k: await self.get_result_series(device, rising_edge, args.count if k == "total" else 1, *v)
            for k,v in self.__counters.items()
        }
        return results

    def print_result_row(self, title, unit, *values):
        print(f"{title:10}: ", end="")
        for i, ( value, prefix ) in enumerate(values):
            if i > 0:
                print("  <  ", end="")
            print(f"{value:>7.3f} {prefix:1}{unit:2}", end="")
        print("")

    def print_results(self, results, title, key, unit):
        values = (
            num_to_si(min(*( v[key] for k,v in results.items() ))),
            num_to_si(results["total"][key]),
            num_to_si(max(*( v[key] for k,v in results.items() ))),
        )
        self.print_result_row(title, unit, *values)

    async def run(self, device, args):
        rising_edge = args.edge in ("r", "rising")

        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)

        await self.wait_for_idle(device)

        await device.write_register(self.__reg_count, args.count, width=4)
        await iface.write([ _Command.COUNT ])
        await iface.flush()

        await self.wait_for_idle(device)

        results = await self.get_results(device, rising_edge, args)

        self.print_result_row("Duration", "s", num_to_si(results["total"]["duration"]))
        self.print_results(results, "Frequency", "frequency", "Hz")
        self.print_results(results, "Duty",      "duty",      "%")
        if rising_edge:
            self.print_results(results, "Time Lo", "t_lo", "s")
            self.print_results(results, "Time Hi", "t_hi", "s")
        else:
            self.print_results(results, "Time Hi", "t_hi", "s")
            self.print_results(results, "Time Lo", "t_lo", "s")

# -------------------------------------------------------------------------------------------------

class FreqCounterTestCase(GlasgowAppletTestCase, applet=FreqCounterApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
