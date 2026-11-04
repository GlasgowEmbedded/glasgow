from contextlib import contextmanager

from amaranth import *
from amaranth.sim import Simulator, SimulatorContext
from amaranth.lib import io
from amaranth.utils import exact_log2

from glasgow.support.bits import bits
from glasgow.gateware.ports import PortGroup
from glasgow.gateware.stream import stream_put, stream_get, stream_assert

from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test
from . import Controller, Enframer, Operation, Status, ProgramEfinixSRAMApplet


def port_group(width):
    ports = PortGroup()

    ports.reset = ~io.SimulationPort("o",  1)
    ports.cs    = ~io.SimulationPort("o",  1)
    ports.cck   =  io.SimulationPort("o",  1)
    ports.cdi   =  io.SimulationPort("o",  width)
    ports.cbus  =  io.SimulationPort("o",  3)
    ports.cdone =  io.SimulationPort("io", 1)

    return ports


def simulate_trion(ports, *, data=bytearray(0x20)):
    async def bus_get(ctx):
        _, reset, cs, _, cdi, cbus, cdone, reset_oe, cs_oe, cck_oe, cdi_oe, cbus_oe, cdone_oe \
        = await ctx.posedge(ports.cck.o).sample(
            ports.reset.o,  ports.cs.o,  ports.cck.o,  ports.cdi.o,  ports.cbus.o,  ports.cdone.o,
            ports.reset.oe, ports.cs.oe, ports.cck.oe, ports.cdi.oe, ports.cbus.oe, ports.cdone.oe
        )

        assert reset_oe and cs_oe and cck_oe and cdi_oe and cbus_oe and cdone_oe
        assert (not reset) and cs and (not cdone)
        assert ~bits(cbus, 3) == bits(exact_log2(len(ports.cdi)), 3)
        return cdi

    async def bus_dummy(ctx):
        _, reset, cs, _, _, _, cdone, reset_oe, cs_oe, cck_oe, cdi_oe, cbus_oe, cdone_oe \
        = await ctx.posedge(ports.cck.o).sample(
            ports.reset.o,  ports.cs.o,  ports.cck.o,  ports.cdi.o,  ports.cbus.o,  ports.cdone.o,
            ports.reset.oe, ports.cs.oe, ports.cck.oe, ports.cdi.oe, ports.cbus.oe, ports.cdone.oe
        )

        # Strictly speaking the device does not actually require this
        assert (not reset_oe) and cs_oe and cck_oe and (not cdi_oe) and (not cbus_oe) and cdone_oe
        assert (not reset) and cs and (not cdone)

    async def testbench_trion(ctx):
        await ctx.posedge(ports.reset.o)
        _, cs, cs_oe = await ctx.negedge(ports.reset.o).sample(ports.cs.o, ports.cs.oe)
        assert cs and cs_oe

        for i in range(len(data)):
            byte = 0
            for j in range(0, 8, len(ports.cdi)):
                byte |= await bus_get(ctx) << (8 - j - len(ports.cdi))
            data[i] = byte
        for _ in range(120):
            await bus_dummy(ctx)
        await ctx.negedge(ports.cdone.oe)
        for _ in range(32):
            await ctx.tick()
        ctx.set(ports.cdone.i, 1)

    return testbench_trion


class ProgramEfinixSRAMAppletTestCase(GlasgowAppletV2TestCase, applet=ProgramEfinixSRAMApplet):
    @contextmanager
    def run_test(self, dut, name="test"):
        sim = Simulator(dut)
        sim.add_clock(1e-6)
        yield sim
        with sim.write_vcd(f"{name}.vcd"):
            sim.run()

    def test_enframer(self):
        dut = Enframer(port_group(1))

        async def testbench_input(ctx):
            await stream_put(ctx, dut.octets, {"oper": Operation.RESET})
            await stream_put(ctx, dut.octets, {"oper": Operation.SETUP, "data": 0xff})
            await stream_put(ctx, dut.octets, {"oper": Operation.SETUP, "data": 0x00})
            await stream_put(ctx, dut.octets, {"oper": Operation.PUT,   "data": 0xAA})
            await stream_put(ctx, dut.octets, {"oper": Operation.PUT,   "data": 0x55})
            await stream_put(ctx, dut.octets, {"oper": Operation.PUT,   "data": 0x0f})
            await stream_put(ctx, dut.octets, {"oper": Operation.PUT,   "data": 0xf0})
            await stream_put(ctx, dut.octets, {"oper": Operation.DUMMY, "data": 0xff})
            await stream_put(ctx, dut.octets, {"oper": Operation.DUMMY, "data": 0x00})
            await stream_put(ctx, dut.octets, {"oper": Operation.FINALIZE})

        async def testbench_output(ctx):
            for (r, e) in [(True, False), (True, True), (False, True)]:
                await stream_assert(ctx, dut.frames, {
                    "port": {
                        "reset": {"o": [r, r], "oe": 1},
                        "cs":    {"o": [1, 1], "oe": e},
                        "cck":   {"o": [1, 1], "oe": e},
                        "cdi":   {"o": [1, 1], "oe": e},
                        "cbus":  {"o": [7, 7], "oe": e},
                        "cdone": {"o": [0, 0], "oe": e},
                    },
                    "meta": {"finalize": 0, "shifted": 0}
                })
            for byte in b"\xAA\x55\x0f\xf0":
                for _ in range(8):
                    await stream_assert(ctx, dut.frames, {
                        "port": {
                            "reset": {"o": [0, 0], "oe": 1},
                            "cs":    {"o": [1, 1], "oe": 1},
                            "cck":   {"o": [0, 1], "oe": 1},
                            "cdi":   {"o": [
                                (byte & 0x80) >> 7, (byte & 0x80) >> 7
                            ], "oe": 1},
                            "cbus":  {"o": [7, 7], "oe": 1},
                            "cdone": {"o": [0, 0], "oe": 1},
                        },
                        "meta": {"finalize": 0, "shifted": 0}
                    })
                    byte = byte << 1
            for i in range(16):
                await stream_assert(ctx, dut.frames, {
                    "port": {
                        "reset": {"o": [0, 0], "oe": 0},
                        "cs":    {"o": [1, 1], "oe": 1},
                        "cck":   {"o": [0, 1], "oe": 1},
                        "cdi":   {"o": [1, 1], "oe": 0},
                        "cbus":  {"o": [7, 7], "oe": 0},
                        "cdone": {"o": [0, 0], "oe": 1},
                    },
                    "meta": {"finalize": 0, "shifted": i == 0}
                })
            await stream_assert(ctx, dut.frames, {
                "port": {
                    "reset": {"o": [0, 0], "oe": 0},
                    "cs":    {"o": [1, 1], "oe": 0},
                    "cck":   {"o": [1, 1], "oe": 0},
                    "cdi":   {"o": [1, 1], "oe": 0},
                    "cbus":  {"o": [7, 7], "oe": 0},
                    "cdone": {"o": [0, 0], "oe": 0},
                },
                "meta": {"finalize": 1, "shifted": 0}
            })

        with self.run_test(dut) as sim:
            sim.add_testbench(testbench_input)
            sim.add_testbench(testbench_output)

    def test_controller(self):
        SAMPLE_DATA = b"\xff\x00\x12\xAA\x55p"
        for width in [1, 2, 4, 8]:
            ports = port_group(width)

            async def testbench_input(ctx):
                for byte in bytes(SAMPLE_DATA):
                    await stream_put(ctx, dut.i, {"data": byte, "end": 0})
                await stream_put(ctx, dut.i, {"data": 0, "end": 1})

            async def testbench_output(ctx):
                assert await stream_get(ctx, dut.o) == Status.SHIFTED
                assert await stream_get(ctx, dut.o) == Status.FINALIZED

            data = bytearray(len(SAMPLE_DATA))
            dut = Controller(ports, clock_period=1e-6)
            with self.run_test(dut) as sim:
                sim.add_testbench(testbench_input)
                sim.add_testbench(testbench_output)
                sim.add_testbench(simulate_trion(ports, data=data))

            self.assertEqual(data, SAMPLE_DATA)

    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=[
            "--creset", "A0", "--cs", "A1", "--cck", "A2", "--cdone", "A3",
            "--freset", "A4", "--cbus", "A5,A6,A7", "--cdi", "B0"
        ])
        self.assertBuilds(args=[
            "--creset", "A0", "--cs", "A1", "--cck", "A2",
            "--freset", "A4", "--cdi", "B0"
        ])
        self.assertBuilds(args=[
            "--creset", "A0", "--cs", "A1", "--cck", "A2",
            "--cdi", "B0,B1"
        ])
        self.assertBuilds(args=[
            "--creset", "A0", "--cs", "A1", "--cck", "A2",
            "--cdi", "B0,B1,B2,B3"
        ])
        self.assertBuilds(args=[
            "--creset", "A0", "--cs", "A1", "--cck", "A2",
            "--cdi", "B0,B1,B2,B3,B4,B5,B6,B7"
        ])

    @applet_v2_simulation_test(args=[
        "--creset", "A0", "--cs", "A1", "--cck", "A2",
        "--freset", "A4", "--cbus", "A5,A6,A7", "--cdi", "B0", "--frequency", "1000"
    ])
    async def test_iface(self, applet: ProgramEfinixSRAMApplet, ctx: SimulatorContext):
        applet.efinix_iface._sim = True
        await applet.efinix_iface.load(b"\x00\x01\xaa\x55\x80\xff")

    @applet_v2_simulation_test(args=[
        "--creset", "A0", "--cs", "A1", "--cck", "A2",
        "--freset", "A4", "--cbus", "A5,A6,A7", "--cdi",
        "B0,B1,B2,B3,B4,B5,B6,B7", "--frequency", "1000"
    ])
    async def test_iface_8bit(self, applet: ProgramEfinixSRAMApplet, ctx: SimulatorContext):
        applet.efinix_iface._sim = True
        await applet.efinix_iface.load(b"\x00\x01\xaa\x55\x80\xff")
