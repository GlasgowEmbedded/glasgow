import functools
import logging
import sys
from typing import Any
from collections.abc import Awaitable, Callable, Mapping
import unittest

from amaranth import *
from amaranth.lib import io
from amaranth.sim.pysim import TestbenchContext

from glasgow.simulation.assembly import SimulationAssembly
from glasgow.abstract import PullState

logger = logging.getLogger(__name__)
logger.level = logging.TRACE

stream_handler = logging.StreamHandler(sys.stderr)
logger.addHandler(stream_handler)


def simulation_assembly_test(
    prepare: Callable[[Any, SimulationAssembly], Any] | None = None,
):

    def decorator(
        case: Callable[
            [Any, SimulationAssembly, TestbenchContext, Any], Awaitable[None]
        ],
    ):
        @functools.wraps(case)
        def wrapper(self):
            assembly = SimulationAssembly()
            prepare_res = None
            if prepare is not None:
                prepare_res = prepare(self, assembly)

            async def launch(ctx: TestbenchContext):
                await case(self, assembly, ctx, prepare_res)

            assembly.run(launch)

        return wrapper

    return decorator


def _jump_pins(
    *jumped_pin_groups: list[str],
    pulls: Mapping[str, PullState] = {},
) -> Callable[[Any, SimulationAssembly], dict[str, io.Buffer]]:
    def prepare(self, assembly: SimulationAssembly) -> dict[str, io.Buffer]:
        buffers = {}
        m = Module()

        for pin in {pin for group in jumped_pin_groups for pin in group}:
            pin_without_inv = pin.rstrip("#")
            port = assembly.add_port(pin, pin_without_inv)
            buffers[pin_without_inv] = buffer = io.Buffer("io", port)
            m.submodules[f"io_{pin_without_inv}"] = buffer

        for group in jumped_pin_groups:
            assembly.connect_pins(*(p.rstrip("#") for p in group))
        assembly.add_submodule(m)

        assembly.use_pulls(pulls)

        return buffers

    return prepare


class SimulationAssemblyTestCase(unittest.TestCase):

    @simulation_assembly_test(prepare=_jump_pins(["A0", "B0"]))
    async def test_jumper(
        self,
        assembly: SimulationAssembly,
        ctx: TestbenchContext,
        buffers: dict[str, io.Buffer],
    ):
        a0 = buffers["A0"]
        b0 = buffers["B0"]

        ctx.set(a0.oe, 1)
        ctx.set(a0.o, 0)

        await ctx.tick()

        self.assertEqual(ctx.get(b0.i), 0)

        ctx.set(a0.o, 1)

        await ctx.tick()

        self.assertEqual(ctx.get(b0.i), 1)

    @simulation_assembly_test(prepare=_jump_pins(["A0#", "B0"]))
    async def test_jumper_pin_invert(
        self,
        assembly: SimulationAssembly,
        ctx: TestbenchContext,
        buffers: dict[str, io.Buffer],
    ):
        a0 = buffers["A0"]
        b0 = buffers["B0"]

        ctx.set(a0.oe, 1)
        ctx.set(a0.o, 0)

        await ctx.tick()

        self.assertEqual(ctx.get(b0.i), 1)

        ctx.set(a0.o, 1)

        await ctx.tick()

        self.assertEqual(ctx.get(b0.i), 0)

    @simulation_assembly_test(prepare=_jump_pins(["A0", "A1"], ["A1", "A2"]))
    async def test_jumper_transitivity(
        self,
        assembly: SimulationAssembly,
        ctx: TestbenchContext,
        buffers: dict[str, io.Buffer],
    ):
        a0 = buffers["A0"]
        a2 = buffers["A2"]

        ctx.set(a0.oe, 1)
        ctx.set(a0.o, 0)

        await ctx.tick()

        self.assertEqual(ctx.get(a2.i), 0)

        ctx.set(a0.o, 1)

        await ctx.tick()

        self.assertEqual(ctx.get(a2.i), 1)

    @simulation_assembly_test(
        prepare=_jump_pins(["A0", "B0"], pulls={"A0": PullState.High})
    )
    async def test_jumper_pull_up(
        self,
        assembly: SimulationAssembly,
        ctx: TestbenchContext,
        buffers: dict[str, io.Buffer],
    ):
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

    @simulation_assembly_test(
        prepare=_jump_pins(
            ["A0", "A1", "A2"],
            pulls={"A0": PullState.Low, "A1": PullState.Low, "A2": PullState.Float},
        )
    )
    async def test_jumper_non_conflicting_pulls(
        self,
        assembly: SimulationAssembly,
        ctx: TestbenchContext,
        buffers: dict[str, io.Buffer],
    ):
        await ctx.tick()

    def test_jumper_conflicting_pulls(self):
        assembly = SimulationAssembly()
        assembly.add_port("A0", "A0")
        assembly.add_port("B0", "B0")
        assembly.use_pulls({"A0": PullState.High, "B0": PullState.Low})

        async def tb(ctx: TestbenchContext):
            self.assertFalse(True, "Must not be able to run with conflicting pull-ups")

        with self.assertRaisesRegex(ValueError, r"\bconflict"):
            assembly.connect_pins("A0", "B0")
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

        end_of_allowed_reached = False

        async def tb(
            ctx: TestbenchContext,
        ):
            # get the variables from outside of this function
            nonlocal end_of_allowed_reached
            nonlocal a0
            nonlocal b0

            ctx.set(a0.oe, 1)
            ctx.set(a0.o, 0)
            ctx.set(b0.oe, 1)
            ctx.set(b0.o, 0)

            await ctx.tick()

            end_of_allowed_reached = True

            ctx.set(a0.o, 1)

            await ctx.tick()

        with self.assertRaisesRegex(AssertionError, r"\bcontention"):
            assembly.run(tb)

        self.assertTrue(
            end_of_allowed_reached,
            "Should be able run with two pin outputs set to the same value",
        )
