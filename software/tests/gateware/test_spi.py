import unittest
from amaranth import *
from amaranth.sim import Simulator, BrokenTrigger
from amaranth.lib import io

from glasgow.gateware.ports import PortGroup
from glasgow.gateware.stream import stream_get, stream_put
from glasgow.gateware.spi import *


def simulate_flash(ports, memory=b"nya nya nya nya nyaaaaan"):
    class CSDeasserted(Exception):
        pass

    async def watch_cs(cs_o, triggers):
        try:
            *values, posedge_cs_o = await triggers.posedge(cs_o)
        except BrokenTrigger: # Workaround for amaranth-lang/amaranth#1508
            # Both our original trigger and posedge of cs happened at the same time.
            # Prioritize CS being deasserted.
            raise CSDeasserted
        if posedge_cs_o == 1:
            raise CSDeasserted
        return values

    async def dev_get(ctx, ports):
        sck, copi, cipo, cs = ports.sck, ports.copi, ports.cipo, ports.cs
        word = 0
        for _ in range(0, 8):
            if ctx.get(sck.o):
                await watch_cs(cs.o, ctx.negedge(sck.o))
            _, copi_oe, copi_o = await watch_cs(cs.o, ctx.posedge(sck.o).sample(copi.oe, copi.o))
            assert copi_oe == 1
            word = (word << 1) | (copi_o << 0)
        return word

    async def dev_nop(ctx, ports, *, cycles):
        sck, copi, cipo, cs = ports.sck, ports.copi, ports.cipo, ports.cs
        for _ in range(cycles):
            if ctx.get(sck.o):
                await watch_cs(cs.o, ctx.negedge(sck.o))
            _, _copi_oe = await watch_cs(cs.o, ctx.posedge(sck.o).sample(copi.oe))

    async def dev_put(ctx, ports, word):
        sck, copi, cipo, cs = ports.sck, ports.copi, ports.cipo, ports.cs
        for _ in range(0, 8):
            if ctx.get(sck.o):
                await watch_cs(cs.o, ctx.negedge(sck.o))
            ctx.set(Cat(cipo.i), (word >> 7))
            word = (word << 1) & 0xff
            _, copi_oe = await watch_cs(cs.o, ctx.posedge(sck.o).sample(copi.oe))
            assert copi_oe == 1

    async def testbench(ctx):
        await ctx.negedge(ports.cs.o)
        while True:
            try:
                cmd = await dev_get(ctx, ports)
                if cmd == 0x0B:
                    addr2 = await dev_get(ctx, ports)
                    addr1 = await dev_get(ctx, ports)
                    addr0 = await dev_get(ctx, ports)
                    await dev_nop(ctx, ports, cycles=8)
                    addr = (addr2 << 16) | (addr1 << 8) | (addr0 << 0)
                    while True:
                        if addr >= len(memory):
                            addr = 0
                        await dev_put(ctx, ports, memory[addr])
                        addr += 1
            except CSDeasserted:
                await ctx.negedge(ports.cs.o)
                continue

    return testbench


class SPIFramingTestCase(unittest.TestCase):
    def setUp(self):
        self.ports = PortGroup()
        self.ports.cs   = io.SimulationPort("o",  1)
        self.ports.sck  = io.SimulationPort("o",  1)
        self.ports.copi = io.SimulationPort("io", 1)
        self.ports.cipo = io.SimulationPort("io", 1)

    def test_spi_enframer(self):
        dut = Enframer(self.ports)

        async def testbench_in(ctx):
            async def data_put(*, chip, data, mode):
                await stream_put(ctx, dut.octets, {"chip": chip, "data": data, "mode": mode})

            await data_put(chip=1, data=0xBA, mode=Mode.Swap)

            await data_put(chip=1, data=0xAA, mode=Mode.Put)
            await data_put(chip=1, data=0x55, mode=Mode.Put)
            await data_put(chip=1, data=0xC1, mode=Mode.Put)

            for _ in range(6):
                await data_put(chip=1, data=0, mode=Mode.Dummy)

            await data_put(chip=1, data=0, mode=Mode.Get)

            await data_put(chip=0, data=0, mode=Mode.Dummy)

        async def testbench_out(ctx):
            async def bits_get(*, cs, ox, oe, mode):
                for cycle, o in enumerate(ox):
                    if cs:
                        sck_o = [0,1]
                    else:
                        sck_o = [1,1]
                    expected = {
                        "port": {
                            "cs":   {"o": [cs,cs], "oe":  1},
                            "sck":  {"o": sck_o,   "oe":  1},
                            "copi": {"o": [ o, o], "oe": oe},
                            "cipo": {"o": [ 0, 0], "oe":  0},
                        },
                        "meta": {
                            "mode": mode,
                            "half": 0 if mode == Mode.Dummy else 1
                        }
                    }
                    assert (actual := await stream_get(ctx, dut.frames)) == expected, \
                        f"(cycle {cycle}) {actual} != {expected}"

            await bits_get(cs=1, ox=[1,0,1,1,1,0,1,0], oe=1, mode=Mode.Swap)

            await bits_get(cs=1, ox=[1,0,1,0,1,0,1,0], oe=1, mode=Mode.Dummy)
            await bits_get(cs=1, ox=[0,1,0,1,0,1,0,1], oe=1, mode=Mode.Dummy)
            await bits_get(cs=1, ox=[1,1,0,0,0,0,0,1], oe=1, mode=Mode.Dummy)

            await bits_get(cs=1, ox=[0,0,0,0,0,0],     oe=0, mode=Mode.Dummy)

            await bits_get(cs=1, ox=[0,0,0,0,0,0,0,0], oe=1, mode=Mode.Get)

            await bits_get(cs=0, ox=[0],               oe=0, mode=Mode.Dummy)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench_in)
        sim.add_testbench(testbench_out)
        with sim.write_vcd("test.vcd"):
            sim.run()

    def test_spi_deframer(self):
        dut = Deframer(self.ports)

        async def testbench_in(ctx):
            async def bits_put(*, ix, mode):
                for _cycle, i in enumerate(ix):
                    await stream_put(ctx, dut.frames, {
                        "port": {
                            "cipo": {"i": [0, i]},
                        },
                        "meta": {
                            "mode": mode,
                            "half": 1
                        }
                    })

            await bits_put(ix=[1,0,1,1,1,0,1,0], mode=Mode.Swap)

            await bits_put(ix=[1,0,1,0,1,0,1,0], mode=Mode.Get)
            await bits_put(ix=[0,1,0,1,0,1,0,1], mode=Mode.Get)
            await bits_put(ix=[1,1,0,0,0,0,0,1], mode=Mode.Get)

        async def testbench_out(ctx):
            async def data_get(*, data):
                expected = {"data": data}
                assert (actual := await stream_get(ctx, dut.octets)) == expected, \
                    f"{actual} != {expected}; data: {actual.data:08b} != {data:08b}"

            await data_get(data=0xBA)

            await data_get(data=0xAA)
            await data_get(data=0x55)
            await data_get(data=0xC1)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench_in)
        sim.add_testbench(testbench_out)
        with sim.write_vcd("test.vcd"):
            sim.run()


class SPIIntegrationTestCase(unittest.TestCase):
    def subtest_spi_controller(self, *, divisor: int):
        ports = PortGroup()
        ports.cs   = io.SimulationPort("o", 1)
        ports.sck  = io.SimulationPort("o", 1)
        ports.copi = io.SimulationPort("o", 1)
        ports.cipo = io.SimulationPort("i", 1)

        dut = Controller(ports)

        async def testbench_controller(ctx):
            async def ctrl_idle():
                await stream_put(ctx, dut.i_stream, {"chip": 0, "data": 0, "mode": Mode.Dummy})

            async def ctrl_put(*, mode, data=0):
                await stream_put(ctx, dut.i_stream, {"chip": 1, "data": data, "mode": mode})

            async def ctrl_get(*, mode, count=1):
                ctx.set(dut.i_stream.p.chip, 1)
                ctx.set(dut.i_stream.p.mode, mode)
                ctx.set(dut.i_stream.valid, 1)
                ctx.set(dut.o_stream.ready, 1)
                words = bytearray()
                o_count = i_count = 0
                while True:
                    _, _, o_stream_ready, i_stream_valid, i_stream_p_data = \
                        await ctx.tick().sample(
                            dut.i_stream.ready, dut.o_stream.valid, dut.o_stream.p.data)
                    if o_stream_ready:
                        o_count += 1
                        if o_count == count:
                            ctx.set(dut.i_stream.valid, 0)
                    if i_stream_valid:
                        words.append(i_stream_p_data)
                        if len(words) == count:
                            ctx.set(dut.o_stream.ready, 0)
                            assert not ctx.get(dut.i_stream.valid)
                            break
                return words
            if divisor is not None:
                ctx.set(dut.divisor, divisor)

            await ctrl_idle()

            await ctrl_put(mode=Mode.Put, data=0x0B)
            await ctrl_put(mode=Mode.Put, data=0x00)
            await ctrl_put(mode=Mode.Put, data=0x00)
            await ctrl_put(mode=Mode.Put, data=0x08)
            for _ in range(8):
                await ctrl_put(mode=Mode.Dummy)
            assert (data := await ctrl_get(mode=Mode.Get, count=4)) == b"awa!", data

            await ctrl_idle()

        testbench_flash = simulate_flash(ports, memory=b"nya nya awa!nya nyaaaaan")

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench_controller)
        sim.add_testbench(testbench_flash, background=True)
        with sim.write_vcd("test.vcd"):
            sim.run()

    def test_spi_controller_div0(self):
        self.subtest_spi_controller(divisor=0)

    def test_spi_controller_div1(self):
        self.subtest_spi_controller(divisor=1)

    def test_spi_controller_div2(self):
        self.subtest_spi_controller(divisor=2)

    def test_spi_controller_div3(self):
        self.subtest_spi_controller(divisor=2)
