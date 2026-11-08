import functools
import logging
from typing import Any
from collections.abc import Callable, Mapping
import unittest
import logging as pylogging

from amaranth import *
from amaranth.lib import io
from amaranth.sim.pysim import TestbenchContext

from glasgow.support import logging
from glasgow.simulation.assembly import SimulationAssembly
from glasgow.abstract import GlasgowPin, PullState


logger = logging.getLogger(__name__)
pylogging.basicConfig(level=logging.TRACE)


def _simulation_test(
    prepare: Callable[[Any, SimulationAssembly], Any] | None = None,
):
    def decorator(case):
        @functools.wraps(case)
        def wrapper(self):
            assembly = SimulationAssembly()
            prepare_res = None
            if prepare is not None:
                prepare_res = prepare(self, assembly)

            async def launch(ctx: TestbenchContext):
                await assembly.configure_ports()
                await case(self, ctx, prepare_res)

            assembly.run(launch)

        return wrapper

    return decorator


def _connect_pins(
    *jumpers: list[str], pulls: Mapping[str, PullState] = {},
) -> Callable[[Any, SimulationAssembly], dict[str, io.Buffer]]:
    jumpers = [[GlasgowPin.parse(pin)[0] for pin in group] for group in jumpers]

    def prepare(self, assembly: SimulationAssembly) -> dict[str, io.Buffer]:
        buffers = {}

        m = Module()
        for pin in {pin for group in jumpers for pin in group}:
            port = assembly.add_port(pin, pin.location)
            buffers[pin.location] = buffer = io.Buffer("io", port)
            m.submodules[f"io_{pin.location}"] = buffer
        assembly.add_submodule(m)

        for group in jumpers:
            assembly.connect_pins(*(pin.location for pin in group))

        assembly.use_pulls(pulls)

        return buffers

    return prepare


class SimulationPinTestCase(unittest.TestCase):
    @_simulation_test(prepare=_connect_pins(["A0", "B0"]))
    async def test_jumper(self, ctx: TestbenchContext, buffers: dict[str, io.Buffer]):
        a0 = buffers["A0"]
        b0 = buffers["B0"]

        ctx.set(a0.oe, 1)
        ctx.set(a0.o, 0)

        await ctx.tick()

        self.assertEqual(ctx.get(b0.i), 0)

        ctx.set(a0.o, 1)

        await ctx.tick()

        self.assertEqual(ctx.get(b0.i), 1)

    @_simulation_test(prepare=_connect_pins(["A0#", "B0"]))
    async def test_jumper_invert(self, ctx: TestbenchContext, buffers: dict[str, io.Buffer]):
        a0 = buffers["A0"]
        b0 = buffers["B0"]

        ctx.set(a0.oe, 1)
        ctx.set(a0.o, 0)

        await ctx.tick()

        self.assertEqual(ctx.get(b0.i), 1)

        ctx.set(a0.o, 1)

        await ctx.tick()

        self.assertEqual(ctx.get(b0.i), 0)

    @_simulation_test(prepare=_connect_pins(["A0", "A1"], ["A1", "A2"]))
    async def test_jumper_transitivity(self, ctx: TestbenchContext, buffers: dict[str, io.Buffer]):
        a0 = buffers["A0"]
        a2 = buffers["A2"]

        ctx.set(a0.oe, 1)
        ctx.set(a0.o, 0)

        await ctx.tick()

        self.assertEqual(ctx.get(a2.i), 0)

        ctx.set(a0.o, 1)

        await ctx.tick()

        self.assertEqual(ctx.get(a2.i), 1)

    @_simulation_test(
        prepare=_connect_pins(["A0", "B0"], pulls={"A0": PullState.High})
    )
    async def test_jumper_pull_high(self, ctx: TestbenchContext, buffers: dict[str, io.Buffer]):
        a0 = buffers["A0"]
        b0 = buffers["B0"]

        await ctx.tick()

        self.assertEqual(ctx.get(a0.i), 1)
        self.assertEqual(ctx.get(b0.i), 1)

        ctx.set(a0.oe, 1)
        ctx.set(a0.o, 0)

        await ctx.tick()

        self.assertEqual(ctx.get(b0.i), 0)

        ctx.set(a0.oe, 0)

        await ctx.tick()

        self.assertEqual(ctx.get(a0.i), 1)
        self.assertEqual(ctx.get(b0.i), 1)

        ctx.set(b0.oe, 1)
        ctx.set(b0.o, 0)

        await ctx.tick()

        self.assertEqual(ctx.get(a0.i), 0)

    @_simulation_test(
        prepare=_connect_pins(
            ["A0", "A1", "A2"],
            pulls={"A0": PullState.Low, "A1": PullState.Low, "A2": PullState.Float},
        )
    )
    async def test_jumper_pull_low_low(self, ctx: TestbenchContext, buffers: dict[str, io.Buffer]):
        await ctx.tick()
        # Should not raise.

    def test_jumper_pull_high_low(self):
        assembly = SimulationAssembly()
        assembly.add_port("A0", "A0")
        assembly.add_port("B0", "B0")
        assembly.use_pulls({"A0": PullState.High, "B0": PullState.Low})
        assembly.connect_pins("A0", "B0")

        async def tb(ctx: TestbenchContext):
            await assembly.configure_ports()

        with self.assertRaisesRegex(AssertionError,
            r"indeterminate value on simulation net: "
            r"A0\.weak0=0 A0\.weak1=1 B0\.weak0=1 B0\.weak1=0"
        ):
            assembly.run(tb)

    def test_jumper_contention(self):
        assembly = SimulationAssembly()
        port_a0 = assembly.add_port("A0", "A0")
        port_b0 = assembly.add_port("B0", "B0")

        m = Module()

        a0 = io.Buffer("io", port_a0)
        b0 = io.Buffer("io", port_b0)

        m.submodules["io_A0"] = a0
        m.submodules["io_B0"] = b0

        assembly.add_submodule(m)

        assembly.connect_pins("A0", "B0")

        async def tb(ctx):
            ctx.set(a0.oe, 1)
            ctx.set(a0.o, 0)
            ctx.set(b0.oe, 1)
            ctx.set(b0.o, 0)

            await ctx.tick()

            ctx.set(a0.o, 1)

            await ctx.tick()

        with self.assertRaisesRegex(AssertionError,
            r"electrical contention on simulation net: A0\.oe=1 A0\.o=1 B0\.oe=1 B0\.o=0"
        ):
            assembly.run(tb)
