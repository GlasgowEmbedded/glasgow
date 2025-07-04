import unittest
from amaranth import *
from amaranth.sim import Simulator, BrokenTrigger
from amaranth.lib import io

from glasgow.gateware.ports import PortGroup
from glasgow.gateware.stream import stream_get, stream_put
from glasgow.gateware.qspi import *


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

    async def dev_get(ctx, ports, *, x):
        sck, io0, io1, io2, io3, cs = ports.sck, *ports.io, ports.cs
        word = 0
        for _ in range(0, 8, x):
            if ctx.get(sck.o):
                await watch_cs(cs.o, ctx.negedge(sck.o))
            _, io0_oe, io0_o, io1_oe, io1_o, io2_oe, io2_o, io3_oe, io3_o = \
                await watch_cs(cs.o, ctx.posedge(sck.o).sample(
                    io0.oe, io0.o, io1.oe, io1.o, io2.oe, io2.o, io3.oe, io3.o))
            if x == 1:
                assert (io0_oe, io1_oe, io2_oe, io3_oe) == (1, 0, 0, 0)
                word = (word << 1) | (io0_o << 0)
            if x == 2:
                assert (io0_oe, io1_oe, io2_oe, io3_oe) == (1, 1, 0, 0)
                word = (word << 2) | (io1_o << 1) | (io0_o << 0)
            if x == 4:
                assert (io0_oe, io1_oe, io2_oe, io3_oe) == (1, 1, 1, 1)
                word = (word << 4) | (io3_o << 3) | (io2_o << 2) | (io1_o << 1) | (io0_o << 0)
        return word

    async def dev_nop(ctx, ports, *, x, cycles):
        sck, io0, io1, io2, io3, cs = ports.sck, *ports.io, ports.cs
        for _ in range(cycles):
            if ctx.get(sck.o):
                await watch_cs(cs.o, ctx.negedge(sck.o))
            _, io0_oe, io1_oe, io2_oe, io3_oe = \
                await watch_cs(cs.o, ctx.posedge(sck.o).sample(io0.oe, io1.oe, io2.oe, io3.oe))
            if x == 1:
                assert (        io1_oe, io2_oe, io3_oe) == (   0, 0, 0)
            else:
                assert (io0_oe, io1_oe, io2_oe, io3_oe) == (0, 0, 0, 0)

    async def dev_put(ctx, ports, word, *, x):
        sck, io0, io1, io2, io3, cs = ports.sck, *ports.io, ports.cs
        for _ in range(0, 8, x):
            if ctx.get(sck.o):
                await watch_cs(cs.o, ctx.negedge(sck.o))
            if x == 1:
                ctx.set(Cat(io1.i), (word >> 7))
                word = (word << 1) & 0xff
            if x == 2:
                ctx.set(Cat(io0.i, io1.i), (word >> 6))
                word = (word << 2) & 0xff
            if x == 4:
                ctx.set(Cat(io0.i, io1.i, io2.i, io3.i), (word >> 4))
                word = (word << 4) & 0xff
            _, io0_oe, io1_oe, io2_oe, io3_oe = \
                await watch_cs(cs.o, ctx.posedge(sck.o).sample(io0.oe, io1.oe, io2.oe, io3.oe))
            assert (io0_oe, io1_oe, io2_oe, io3_oe) == (x == 1, 0, 0, 0)

    async def testbench(ctx):
        await ctx.negedge(ports.cs.o)
        while True:
            try:
                cmd = await dev_get(ctx, ports, x=1)
                if cmd in (0x0B, 0x3B, 0x6B):
                    addr2 = await dev_get(ctx, ports, x=1)
                    addr1 = await dev_get(ctx, ports, x=1)
                    addr0 = await dev_get(ctx, ports, x=1)
                    if cmd == 0x0B:
                        await dev_nop(ctx, ports, x=1, cycles=8)
                    if cmd == 0x3B:
                        await dev_nop(ctx, ports, x=2, cycles=4)
                    if cmd == 0x6B:
                        await dev_nop(ctx, ports, x=4, cycles=4)
                    addr = (addr2 << 16) | (addr1 << 8) | (addr0 << 0)
                    while True:
                        if addr >= len(memory):
                            addr = 0
                        if cmd == 0x0B:
                            await dev_put(ctx, ports, memory[addr], x=1)
                        if cmd == 0x3B:
                            await dev_put(ctx, ports, memory[addr], x=2)
                        if cmd == 0x6B:
                            await dev_put(ctx, ports, memory[addr], x=4)
                        addr += 1
            except CSDeasserted:
                await ctx.negedge(ports.cs.o)
                continue

    return testbench


class QSPIFramingTestCase(unittest.TestCase):
    def setUp(self):
        self.ports = PortGroup()
        self.ports.cs  = io.SimulationPort("o",  1)
        self.ports.sck = io.SimulationPort("o",  1)
        self.ports.io0 = io.SimulationPort("io", 1)
        self.ports.io1 = io.SimulationPort("io", 1)
        self.ports.io2 = io.SimulationPort("io", 1)
        self.ports.io3 = io.SimulationPort("io", 1)

    def test_qspi_enframer(self):
        dut = Enframer(self.ports)

        async def testbench_in(ctx):
            async def data_put(*, chip, data, mode):
                await stream_put(ctx, dut.octets, {"chip": chip, "data": data, "mode": mode})

            await data_put(chip=1, data=0xBA, mode=Mode.Swap)

            await data_put(chip=1, data=0xAA, mode=Mode.PutX1)
            await data_put(chip=1, data=0x55, mode=Mode.PutX1)
            await data_put(chip=1, data=0xC1, mode=Mode.PutX1)

            await data_put(chip=1, data=0xAA, mode=Mode.PutX2)
            await data_put(chip=1, data=0x55, mode=Mode.PutX2)
            await data_put(chip=1, data=0xC1, mode=Mode.PutX2)

            await data_put(chip=1, data=0xAA, mode=Mode.PutX4)
            await data_put(chip=1, data=0x55, mode=Mode.PutX4)
            await data_put(chip=1, data=0xC1, mode=Mode.PutX4)

            for _ in range(6):
                await data_put(chip=1, data=0, mode=Mode.Dummy)

            await data_put(chip=1, data=0, mode=Mode.GetX1)
            await data_put(chip=1, data=0, mode=Mode.GetX2)
            await data_put(chip=1, data=0, mode=Mode.GetX4)

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
                            "cs":  {"o": [      cs,       cs], "oe":         1},
                            "sck": {"o":                sck_o, "oe":         1},
                            "io0": {"o": [(o>>0)&1, (o>>0)&1], "oe": (oe>>0)&1},
                            "io1": {"o": [(o>>1)&1, (o>>1)&1], "oe": (oe>>1)&1},
                            "io2": {"o": [(o>>2)&1, (o>>2)&1], "oe": (oe>>2)&1},
                            "io3": {"o": [(o>>3)&1, (o>>3)&1], "oe": (oe>>3)&1},
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

            await bits_get(cs=1, ox=[0b10,0b10,0b10,0b10], oe=0b11, mode=Mode.Dummy)
            await bits_get(cs=1, ox=[0b01,0b01,0b01,0b01], oe=0b11, mode=Mode.Dummy)
            await bits_get(cs=1, ox=[0b11,0b00,0b00,0b01], oe=0b11, mode=Mode.Dummy)

            await bits_get(cs=1, ox=[0b1010,0b1010], oe=0b1111, mode=Mode.Dummy)
            await bits_get(cs=1, ox=[0b0101,0b0101], oe=0b1111, mode=Mode.Dummy)
            await bits_get(cs=1, ox=[0b1100,0b0001], oe=0b1111, mode=Mode.Dummy)

            await bits_get(cs=1, ox=[0,0,0,0,0,0], oe=0, mode=Mode.Dummy)

            await bits_get(cs=1, ox=[0,0,0,0,0,0,0,0], oe=1, mode=Mode.GetX1)
            await bits_get(cs=1, ox=[0,0,0,0],         oe=0, mode=Mode.GetX2)
            await bits_get(cs=1, ox=[0,0],             oe=0, mode=Mode.GetX4)

            await bits_get(cs=0, ox=[0], oe=0, mode=Mode.Dummy)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench_in)
        sim.add_testbench(testbench_out)
        with sim.write_vcd("test.vcd"):
            sim.run()

    def test_qspi_deframer(self):
        dut = Deframer(self.ports)

        async def testbench_in(ctx):
            async def bits_put(*, ix, mode):
                for cycle, i in enumerate(ix):
                    await stream_put(ctx, dut.frames, {
                        "port": {
                            "io0": {"i": [0, (i>>0)&1]},
                            "io1": {"i": [0, (i>>1)&1]},
                            "io2": {"i": [0, (i>>2)&1]},
                            "io3": {"i": [0, (i>>3)&1]},
                        },
                        "meta": {
                            "mode": mode,
                            "half": 1
                        }
                    })

            await bits_put(ix=[i<<1 for i in [1,0,1,1,1,0,1,0]], mode=Mode.Swap)

            await bits_put(ix=[i<<1 for i in [1,0,1,0,1,0,1,0]], mode=Mode.GetX1)
            await bits_put(ix=[i<<1 for i in [0,1,0,1,0,1,0,1]], mode=Mode.GetX1)
            await bits_put(ix=[i<<1 for i in [1,1,0,0,0,0,0,1]], mode=Mode.GetX1)

            await bits_put(ix=[0b10,0b10,0b10,0b10], mode=Mode.GetX2)
            await bits_put(ix=[0b01,0b01,0b01,0b01], mode=Mode.GetX2)
            await bits_put(ix=[0b11,0b00,0b00,0b01], mode=Mode.GetX2)

            await bits_put(ix=[0b1010,0b1010], mode=Mode.GetX4)
            await bits_put(ix=[0b0101,0b0101], mode=Mode.GetX4)
            await bits_put(ix=[0b1100,0b0001], mode=Mode.GetX4)

        async def testbench_out(ctx):
            async def data_get(*, data):
                expected = {"data": data}
                assert (actual := await stream_get(ctx, dut.octets)) == expected, \
                    f"{actual} != {expected}; data: {actual.data:08b} != {data:08b}"

            await data_get(data=0xBA)

            await data_get(data=0xAA)
            await data_get(data=0x55)
            await data_get(data=0xC1)

            await data_get(data=0xAA)
            await data_get(data=0x55)
            await data_get(data=0xC1)

            await data_get(data=0xAA)
            await data_get(data=0x55)
            await data_get(data=0xC1)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench_in)
        sim.add_testbench(testbench_out)
        with sim.write_vcd("test.vcd"):
            sim.run()


class QSPIIntegrationTestCase(unittest.TestCase):
    def subtest_qspi_controller(self, *, divisor: int):
        ports = PortGroup()
        ports.cs  = io.SimulationPort("o",  1)
        ports.sck = io.SimulationPort("o",  1)
        ports.io  = io.SimulationPort("io", 4)

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

            await ctrl_put(mode=Mode.PutX1, data=0x0B)
            await ctrl_put(mode=Mode.PutX1, data=0x00)
            await ctrl_put(mode=Mode.PutX1, data=0x00)
            await ctrl_put(mode=Mode.PutX1, data=0x08)
            for _ in range(8):
                await ctrl_put(mode=Mode.Dummy)
            assert (data := await ctrl_get(mode=Mode.GetX1, count=4)) == b"awa!", data

            await ctrl_idle()

            await ctrl_put(mode=Mode.PutX1, data=0x6B)
            await ctrl_put(mode=Mode.PutX1, data=0x00)
            await ctrl_put(mode=Mode.PutX1, data=0x00)
            await ctrl_put(mode=Mode.PutX1, data=0x10)
            for _ in range(4):
                await ctrl_put(mode=Mode.Dummy)
            assert (data := await ctrl_get(mode=Mode.GetX4, count=8)) == b"nyaaaaan", data

            await ctrl_idle()

        testbench_flash = simulate_flash(ports, memory=b"nya nya awa!nya nyaaaaan")

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(testbench_controller)
        sim.add_testbench(testbench_flash, background=True)
        with sim.write_vcd("test.vcd"):
            sim.run()

    def test_qspi_controller_div0(self):
        self.subtest_qspi_controller(divisor=0)

    def test_qspi_controller_div1(self):
        self.subtest_qspi_controller(divisor=1)

    def test_qspi_controller_div2(self):
        self.subtest_qspi_controller(divisor=2)

    def test_qspi_controller_div3(self):
        self.subtest_qspi_controller(divisor=2)
