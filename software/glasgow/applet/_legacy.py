from abc import ABCMeta, abstractmethod
import os
import unittest
import argparse
import functools
import asyncio
import threading

from ..support.arepl import AsyncInteractiveConsole
from ..support.mock import MockRecorder, MockReplayer
from ..simulation.assembly import SimulationAssembly
from ..abstract import AbstractAssembly
from ..hardware.assembly import HardwareAssembly
from ..hardware.device import GlasgowDevice
from ..hardware.platform.rev_ab import GlasgowRevABPlatform
from ..gateware.clockgen import ClockGen
from ..legacy import DeprecatedTarget, DeprecatedDevice, DeprecatedDemultiplexer
from . import GlasgowAppletError, GlasgowAppletArguments


__all__ = [
    "GlasgowApplet",
    "GlasgowAppletTestCase", "applet_simulation_test", "applet_hardware_test"
]


class GlasgowApplet(metaclass=ABCMeta):
    preview = False
    help = "applet help missing"
    description = "applet description missing"
    required_revision = "A0"

    def __init__(self, assembly: AbstractAssembly):
        if isinstance(assembly, HardwareAssembly):
            if assembly.revision < self.required_revision:
                self.logger.warning(f"applet requires a rev{self.required_revision}+ device, "
                                    f"use on a rev{assembly.revision} device is unsupported")
            if self.preview:
                self.logger.warning(f"applet is PREVIEW QUALITY and may CORRUPT DATA")

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_build_arguments(parser)

    def derive_clock(self, *args, clock_name=None, **kwargs):
        try:
            return ClockGen.derive(*args, **kwargs, logger=self.logger, clock_name=clock_name)
        except ValueError as e:
            if clock_name is None:
                raise GlasgowAppletError(e)
            else:
                raise GlasgowAppletError(f"clock {clock_name}: {e}")

    @abstractmethod
    def build(self, target, args):
        pass

    @classmethod
    def add_run_arguments(cls, parser, access):
        access.add_run_arguments(parser)

    async def run_lower(self, cls, device, args, **kwargs):
        return await super(cls, self).run(device, args, **kwargs)

    @abstractmethod
    async def run(self, device, args):
        pass

    @classmethod
    def add_interact_arguments(cls, parser):
        pass

    async def interact(self, device, args, iface):
        raise GlasgowAppletError("This applet can only be used in REPL mode.")

    @classmethod
    def add_repl_arguments(cls, parser):
        pass

    async def repl(self, device, args, iface):
        self.logger.info("dropping to REPL; use 'help(iface)' to see available APIs")
        await AsyncInteractiveConsole(locals={"device":device, "iface":iface, "args":args},
            run_callback=device.demultiplexer.flush).interact()

    @classmethod
    def tests(cls):
        return None


class GlasgowAppletTestCase(unittest.TestCase):
    def __init_subclass__(cls, applet, **kwargs):
        super().__init_subclass__(**kwargs)

        cls.applet_cls  = applet

    def setUp(self):
        self.assembly = HardwareAssembly(revision=self.applet_cls.required_revision)
        self.applet = self.applet_cls(self.assembly)

    def assertBuilds(self, args=[]):
        target = DeprecatedTarget(self.assembly)

        parser = argparse.ArgumentParser()
        access_args = GlasgowAppletArguments("applet")
        self.applet.add_build_arguments(parser, access_args)

        try:
            parsed_args = parser.parse_args(args)
        except SystemExit:
            raise AssertionError("argument parsing failed") from None
        self.applet.build(target, parsed_args)

        target.build_plan().get_bitstream()

    def _prepare_applet_args(self, args, access_args, interact=False):
        parser = argparse.ArgumentParser()
        self.applet.add_build_arguments(parser, access_args)
        self.applet.add_run_arguments(parser, access_args)
        if interact:
            self.applet.add_interact_arguments(parser)
        self._parsed_args = parser.parse_args(args)
        return self._parsed_args

    async def run_simulated_applet(self):
        return await self.applet.run(self.device, self._parsed_args)

    def _prepare_hardware_target(self, case, fixture, mode):
        assert mode in ("record", "replay")

        if mode == "record":
            self.device = None # in case the next line raises
            self.device = GlasgowDevice()
            self.device.demultiplexer = DeprecatedDemultiplexer(self.device, pipe_count=1)
            revision = self.device.revision
        else:
            self.device = None
            revision = "A0"

        self.assembly = HardwareAssembly(revision=revision)
        self.target = DeprecatedTarget(self.assembly)
        self.applet.build(self.target, self._parsed_args)

        self._recording = False
        self._recorders = []

        old_run_lower = self.applet.run_lower

        async def run_lower(cls, device, args):
            if mode == "record":
                lower_iface = await old_run_lower(cls, device, args)
                recorder = MockRecorder(case,  fixture, lower_iface)
                self._recorders.append(recorder)
                return recorder

            if mode == "replay":
                return MockReplayer(case, fixture)

        self.applet.run_lower = run_lower

    async def run_hardware_applet(self, mode):
        if mode == "record":
            await self.device.download_target(self.target.build_plan())

        return await self.applet.run(self.device, self._parsed_args)


def applet_simulation_test(setup, args=[]):
    def decorator(case):
        @functools.wraps(case)
        def wrapper(self):
            assembly = SimulationAssembly()

            access_args = GlasgowAppletArguments("applet")
            parsed_args = self._prepare_applet_args(args, access_args)

            target = DeprecatedTarget(assembly)
            device = DeprecatedDevice(target)
            device.demultiplexer = DeprecatedDemultiplexer(device, 1)

            getattr(self, setup)(target, parsed_args)

            async def launch(ctx):
                await case(self, device, parsed_args, ctx)
            vcd_name = f"{case.__name__}.vcd"
            assembly.run(launch, vcd_file=vcd_name)
            os.remove(vcd_name)

        return wrapper

    return decorator


def applet_hardware_test(setup="run_hardware_applet", args=[]):
    def decorator(case):
        @functools.wraps(case)
        def wrapper(self):
            fixture_path = os.path.join(os.path.dirname(case.__code__.co_filename), "fixtures",
                                        case.__name__ + ".json")
            os.makedirs(os.path.dirname(fixture_path), exist_ok=True)
            if os.path.exists(fixture_path):
                fixture = open(fixture_path)
                mode = "replay"
            else:
                fixture = open(fixture_path, "w")
                mode = "record"

            try:
                access_args = GlasgowAppletArguments(self.applet)
                self._prepare_applet_args(args, access_args)
                self._prepare_hardware_target(self, fixture, mode)

                exception = None
                def run_test():
                    try:
                        loop = asyncio.new_event_loop()
                        iface = loop.run_until_complete(getattr(self, setup)(mode))

                        self._recording = True
                        loop.run_until_complete(case(self, iface))

                    except Exception as e:
                        nonlocal exception
                        exception = e

                    finally:
                        if self.device is not None:
                            loop.run_until_complete(self.device.demultiplexer.cancel())
                        loop.close()

                thread = threading.Thread(target=run_test)
                thread.start()
                thread.join()
                if exception is not None:
                    raise exception

            except:
                if mode == "record":
                    os.remove(fixture_path)
                raise

            finally:
                if mode == "record":
                    if self.device is not None:
                        self.device.close()
                fixture.close()

        return wrapper

    return decorator
