from unittest.mock import AsyncMock, PropertyMock, patch

from glasgow.applet import (
    GlasgowAppletError, GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test,
    async_test,
)
from glasgow.simulation.assembly import SimulationAssembly
from . import SelfTestApplet


class SelfTestAppletTestCase(GlasgowAppletV2TestCase, applet=SelfTestApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    @synthesis_test
    def test_build_rev_c3(self):
        self.assertBuilds(revision="C3")

    @applet_v2_simulation_test()
    async def test_pin_registers(self, applet, ctx):
        for port, oe, output, inputs in (
            ("A", applet._oe_a, applet._o_a, applet._i_a),
            ("B", applet._oe_b, applet._o_b, applet._i_b),
        ):
            pins = [applet.assembly.get_pin(f"{port}{bit}") for bit in range(8)]
            for pin in pins:
                self.assertEqual(ctx.get(pin.oe), 0)
            await output.set(0xa5)
            await oe.set(0x3c)
            for bit, pin in enumerate(pins):
                self.assertEqual(ctx.get(pin.o), (0xa5 >> bit) & 1)
                self.assertEqual(ctx.get(pin.oe), (0x3c >> bit) & 1)
            await oe.set(0)
            for bit, pin in enumerate(pins):
                ctx.set(pin.i, (0x96 >> bit) & 1)
            self.assertEqual(await inputs.get(), 0x96)
            for pin in pins:
                self.assertEqual(ctx.get(pin.oe), 0)

    @applet_v2_simulation_test()
    async def test_loopback(self, applet, ctx):
        data = bytes(range(256)) * 3
        pipe_1, pipe_2 = applet._loopback_pipes
        await pipe_1.send(data)
        await pipe_2.send(data[::-1])
        await pipe_1.flush()
        await pipe_2.flush()
        self.assertEqual(await pipe_1.recv(len(data)), data)
        self.assertEqual(await pipe_2.recv(len(data)), data[::-1])

    @async_test
    async def test_default_mode(self):
        applet = SelfTestApplet(SimulationAssembly())
        pipes = [AsyncMock(), AsyncMock()]
        applet._loopback_pipes = pipes
        for pipe in pipes:
            pipe.send.side_effect = lambda data, pipe=pipe: setattr(pipe.recv, "return_value", data)
        with patch.object(SelfTestApplet, "device", new_callable=PropertyMock):
            await applet.run(self._parse_args([], mode="run"))
        for pipe in pipes:
            pipe.send.assert_awaited_once()
            pipe.flush.assert_awaited_once()
            pipe.recv.assert_awaited_once()

    @async_test
    async def test_loopback_failures(self):
        for failure in ("send", "flush", "recv", "mismatch"):
            with self.subTest(failure=failure):
                applet = SelfTestApplet(SimulationAssembly())
                pipes = [AsyncMock(), AsyncMock()]
                applet._loopback_pipes = pipes
                for pipe in pipes:
                    pipe.send.side_effect = lambda data, pipe=pipe: setattr(
                        pipe.recv, "return_value", data)
                if failure == "mismatch":
                    pipes[0].recv.side_effect = lambda length: b"\x00" * length
                else:
                    getattr(pipes[0], failure).side_effect = TimeoutError
                with patch.object(SelfTestApplet, "device", new_callable=PropertyMock):
                    with self.assertLogs(applet.logger, level="ERROR"):
                        with self.assertRaisesRegex(GlasgowAppletError, "self-test: FAIL"):
                            await applet.run(self._parse_args(["loopback"], mode="run"))
                pipes[1].recv.assert_awaited_once()
