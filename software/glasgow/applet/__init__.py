import re
import argparse
from abc import ABCMeta, abstractmethod

from ..support.arepl import *
from ..gateware.clockgen import *


__all__ = ["GlasgowAppletError", "GlasgowApplet", "GlasgowAppletTool"]


class GlasgowAppletError(Exception):
    """An exception raised when an applet encounters an error."""


class GlasgowAppletMeta(ABCMeta):
    all_applets = {}

    def __new__(metacls, clsname, bases, namespace, name=None, **kwargs):
        if name is not None:
            if name in metacls.all_applets:
                raise NameError(f"Applet {name!r} already exists")
            namespace["name"] = name

        cls = ABCMeta.__new__(metacls, clsname, bases, namespace, **kwargs)
        if name is not None:
            metacls.all_applets[name] = cls
        return cls


class GlasgowApplet(metaclass=GlasgowAppletMeta):
    preview = False
    help = "applet help missing"
    description = "applet description missing"
    required_revision = "A0"

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
                raise GlasgowAppletError("clock {}: {}".format(clock_name, e))

    @abstractmethod
    def build(self, target):
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
        pass

    @classmethod
    def add_repl_arguments(cls, parser):
        pass

    async def repl(self, device, args, iface):
        self.logger.info("dropping to REPL; use 'help(iface)' to see available APIs")
        await AsyncInteractiveConsole(locals={"device":device, "iface":iface},
            run_callback=device.demultiplexer.flush).interact()


class GlasgowAppletTool:
    def __init_subclass__(cls, applet, **kwargs):
        super().__init_subclass__(**kwargs)

        applet.tool_cls = cls
        cls.applet_cls  = applet
        cls.logger      = applet.logger

    @classmethod
    def add_arguments(cls, parser):
        pass

    async def run(self, args):
        pass

# -------------------------------------------------------------------------------------------------

import os
import unittest
import functools
import asyncio
import threading
import inspect
import json
from nmigen.back.pysim import *

from ..access.simulation import *
from ..access.direct import *
from ..target.simulation import *
from ..target.hardware import *
from ..device.simulation import *
from ..device.hardware import *
from ..platform.all import GlasgowPlatformRevAB


__all__ += ["GlasgowAppletTestCase", "synthesis_test", "applet_simulation_test",
            "applet_hardware_test"]


class MockRecorder:
    def __init__(self, case, mocked, fixture):
        self.__case    = case
        self.__mocked  = mocked
        self.__fixture = fixture

    @staticmethod
    def __dump_object(obj):
        if isinstance(obj, bytes):
            return {"__class__": "bytes", "hex": obj.hex()}
        if isinstance(obj, bytearray):
            return {"__class__": "bytearray", "hex": obj.hex()}
        raise TypeError("%s is not serializable" % type(obj))

    def __dump_stanza(self, stanza):
        if not self.__case._recording:
            return
        json.dump(fp=self.__fixture, default=self.__dump_object, obj=stanza)
        self.__fixture.write("\n")

    def __dump_method(self, method, args, kwargs, result, coro):
        self.__dump_stanza({
            "method": method,
            "async":  coro,
            "args":   args,
            "kwargs": kwargs,
            "result": result
        })

    def __getattr__(self, attr):
        mocked = getattr(self.__mocked, attr)
        if inspect.ismethod(mocked):
            def wrapper(*args, **kwargs):
                result = mocked(*args, **kwargs)
                if inspect.isawaitable(result):
                    async def coro_wrapper():
                        coro_result = await result
                        self.__dump_method(attr, args, kwargs, coro_result, coro=True)
                        return coro_result
                    return coro_wrapper()
                else:
                    self.__dump_method(attr, args, kwargs, result, coro=False)
                    return result
            return wrapper

        return mocked


class MockReplayer:
    def __init__(self, case, fixture):
        self.__case    = case
        self.__fixture = fixture

    @staticmethod
    def __load_object(obj):
        if "__class__" not in obj:
            return obj
        if obj["__class__"] == "bytes":
            return bytes.fromhex(obj["hex"])
        if obj["__class__"] == "bytearray":
            return bytearray.fromhex(obj["hex"])
        assert False

    def __load(self):
        json_str = self.__fixture.readline()
        return json.loads(s=json_str, object_hook=self.__load_object)

    def __getattr__(self, attr):
        json_obj = self.__load()
        self.__case.assertEqual(attr, json_obj["method"])
        if json_obj["async"]:
            async def mock(*args, **kwargs):
                self.__case.assertEqual(args, tuple(json_obj["args"]))
                self.__case.assertEqual(kwargs, json_obj["kwargs"])
                return json_obj["result"]
        else:
            def mock(*args, **kwargs):
                self.__case.assertEqual(args, tuple(json_obj["args"]))
                self.__case.assertEqual(kwargs, json_obj["kwargs"])
                return json_obj["result"]
        return mock


class GlasgowAppletTestCase(unittest.TestCase):
    def __init_subclass__(cls, applet, **kwargs):
        super().__init_subclass__(**kwargs)

        applet.test_cls = cls
        cls.applet_cls  = applet

    def setUp(self):
        self.applet = self.applet_cls()

    def assertBuilds(self, access="direct", args=[]):
        if access == "direct":
            target = GlasgowHardwareTarget(revision="A0",
                                           multiplexer_cls=DirectMultiplexer)
            access_args = DirectArguments(applet_name=self.applet.name,
                                          default_port="AB", pin_count=16)
        else:
            raise NotImplementedError

        parser = argparse.ArgumentParser()
        self.applet.add_build_arguments(parser, access_args)

        try:
            parsed_args = parser.parse_args(args)
        except SystemExit:
            raise AssertionError("argument parsing failed") from None
        self.applet.build(target, parsed_args)

        target.build_plan().execute()

    def _prepare_applet_args(self, args, access_args, interact=False):
        parser = argparse.ArgumentParser()
        self.applet.add_build_arguments(parser, access_args)
        self.applet.add_run_arguments(parser, access_args)
        if interact:
            self.applet.add_interact_arguments(parser)
        self._parsed_args = parser.parse_args(args)

    def _prepare_simulation_target(self):
        self.target = GlasgowSimulationTarget()
        self.target.submodules.multiplexer = SimulationMultiplexer()

        self.device = GlasgowSimulationDevice(self.target)
        self.device.demultiplexer = SimulationDemultiplexer(self.device)

    def build_simulated_applet(self):
        self.applet.build(self.target, self._parsed_args)

    async def run_simulated_applet(self):
        return await self.applet.run(self.device, self._parsed_args)

    def _prepare_hardware_target(self, case, fixture, mode):
        assert mode in ("record", "replay")

        if mode == "record":
            self.device = None # in case the next line raises
            self.device = GlasgowHardwareDevice()
            self.device.demultiplexer = DirectDemultiplexer(self.device, pipe_count=1)
            revision = self.device.revision
        else:
            self.device = None
            revision = "A0"

        self.target = GlasgowHardwareTarget(revision=revision,
                                            multiplexer_cls=DirectMultiplexer)
        self.applet.build(self.target, self._parsed_args)

        self._recording = False
        self._recorders = []

        old_run_lower = self.applet.run_lower

        async def run_lower(cls, device, args):
            if mode == "record":
                lower_iface = await old_run_lower(cls, device, args)
                recorder = MockRecorder(case, lower_iface, fixture)
                self._recorders.append(recorder)
                return recorder

            if mode == "replay":
                return MockReplayer(case, fixture)

        self.applet.run_lower = run_lower

    async def run_hardware_applet(self, mode):
        if mode == "record":
            await self.device.download_target(self.target.build_plan())

        return await self.applet.run(self.device, self._parsed_args)


def synthesis_test(case):
    synthesis_available = GlasgowPlatformRevAB().has_required_tools()
    return unittest.skipUnless(synthesis_available, "synthesis not available")(case)


def applet_simulation_test(setup, args=[]):
    def decorator(case):
        @functools.wraps(case)
        def wrapper(self):
            access_args = SimulationArguments(self.applet)
            self._prepare_applet_args(args, access_args)
            self._prepare_simulation_target()

            getattr(self, setup)()
            @asyncio.coroutine
            def run():
                yield from case(self)

            sim = Simulator(self.target)
            sim.add_clock(1e9)
            sim.add_sync_process(run)
            vcd_name = "{}.vcd".format(case.__name__)
            with sim.write_vcd(vcd_name):
                sim.run()
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
                fixture = open(fixture_path, "r")
                mode = "replay"
            else:
                fixture = open(fixture_path, "w")
                mode = "record"

            try:
                access_args = DirectArguments(self.applet, default_port="AB", pin_count=16)
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

        return wrapper

    return decorator
