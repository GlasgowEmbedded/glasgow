import re
import shlex
import unittest
import argparse
import functools
from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Optional

from amaranth import *

from ..support.arepl import AsyncInteractiveConsole
from ..support.plugin import PluginMetadata
from ..abstract import GlasgowPin, AbstractAssembly
from ..hardware.device import GlasgowDevice
from ..gateware.clockgen import *
from ..abstract import GlasgowVio, GlasgowPin
from ..legacy import DeprecatedDemultiplexer, DeprecatedMultiplexer


__all__ = [
    "GlasgowAppletMetadata", "GlasgowAppletError",
    "GlasgowApplet", "GlasgowAppletV2", "GlasgowAppletArguments",
    "GlasgowAppletTool",
    "GlasgowAppletV2TestCase", "async_test", "applet_v2_simulation_test",
]


class GlasgowAppletError(Exception):
    """An exception raised when an applet encounters an error."""


class GlasgowAppletMetadata(PluginMetadata):
    GROUP_NAME = "glasgow.applet"

    @property
    def applet_cls(self):
        return self.load()

    @property
    def tool_cls(self):
        return self.load().tool_cls


class GlasgowAppletError(Exception):
    """An exception raised when an applet encounters an error."""


class GlasgowAppletArguments:
    def __init__(self, applet_name):
        self._applet_name  = applet_name
        self._free_pins    = "A0 A1 A2 A3 A4 A5 A6 A7 B0 B1 B2 B3 B4 B5 B6 B7".split()

    def _arg_error(self, message):
        raise argparse.ArgumentTypeError(f"applet {self._applet_name!r}: " + message)

    def add_pins_argument(self, parser, name, width=None, default=None, required=False, help=None):
        def get_free_pin():
            if len(self._free_pins) > 0:
                result = self._free_pins[0]
                del self._free_pins[0]
                return GlasgowPin.parse(result)[0]

        if width is None:
            match default:
                case None:
                    pass
                case True:
                    default = get_free_pin()
                case _:
                    default = GlasgowPin.parse(default)[0]

            metavar = "PIN"
            if help is None:
                help = f"bind the applet I/O line {name!r} to {metavar}"
            if default:
                help += f" (default: {default})"

            def pin_arg(arg):
                try:
                    result = GlasgowPin.parse(arg)
                except ValueError as e:
                    self._arg_error(str(e))
                if required:
                    if len(result) != 1:
                        self._arg_error(f"expected a single pin, got {len(result)} pins")
                    return result[0]
                else:
                    if len(result) not in (0, 1):
                        self._arg_error(f"expected zero or one pins, got {len(result)} pins")
                    if result:
                        return result[0]

        else:
            if type(width) is int:
                width = range(width, width + 1)

            match default:
                case None:
                    pass
                case True:
                    default = []
                    while len(default) < width.start:
                        if pin := get_free_pin():
                            default.append(pin)
                        else:
                            break
                    default = tuple(default)
                case int():
                    default = tuple(get_free_pin() for _ in range(default))
                case _:
                    default = GlasgowPin.parse(default)

            metavar = "PINS"
            if help is None:
                help = f"bind the applet I/O lines {name!r} to {metavar}"
            if default:
                help += f" (default: {','.join(str(pin) for pin in default)})"
            else:
                help += " (default is empty)"

            def pin_arg(arg):
                try:
                    result = GlasgowPin.parse(arg)
                except ValueError as e:
                    self._arg_error(str(e))
                if len(result) not in width:
                    if len(width) == 1:
                        width_desc = f"{width.start}"
                    else:
                        width_desc = f"{width.start}..{width.stop - width.step}"
                    self._arg_error(f"expected {width_desc} pins, got {len(result)} pins")
                return result

        if required and default is not None:
            required = False

        parser.add_argument(
            f"--{name.lower().replace('_', '-')}", dest=name, metavar=metavar,
            type=pin_arg, default=default, required=required, help=help)

    def add_voltage_argument(self, parser):
        def voltage_arg(arg):
            return GlasgowVio.parse(arg)
        parser.add_argument(
            "-V", "--voltage", metavar="SPEC", type=voltage_arg, default={},
            help="configure I/O port voltage to SPEC (e.g.: '3.3', 'A=5.0,B=3.3', 'A=SA')")

    def add_build_arguments(self, parser):
        pass

    def add_run_arguments(self, parser):
        self.add_voltage_argument(parser)


# A Glasgow applet is defined by a class; known applets are taken from a
# list of entry points in package metadata.  (In the Glasgow package, they
# are enumerated in the `[project.entry-points."glasgow.applet"]` section of
# the pyproject.toml.

class GlasgowApplet(metaclass=ABCMeta):
    preview = False
    help = "applet help missing"
    description = "applet description missing"
    required_revision = "A0"

    def __init__(self, assembly):
        pass

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


class GlasgowAppletV2(metaclass=ABCMeta):
    preview = False
    help = "applet help missing"
    description = "applet description missing"
    required_revision = "A0"

    def __init__(self, assembly):
        self._assembly = assembly

    @property
    def assembly(self) -> AbstractAssembly:
        return self._assembly

    @property
    def device(self) -> GlasgowDevice:
        return self._assembly.device

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)

    def derive_clock(self, *args, clock_name=None, **kwargs):
        try:
            return ClockGen.derive(*args, **kwargs, logger=self.logger, clock_name=clock_name)
        except ValueError as e:
            if clock_name is None:
                raise GlasgowAppletError(e)
            else:
                raise GlasgowAppletError(f"clock {clock_name}: {e}")

    @abstractmethod
    def build(self, args):
        self.assembly.use_voltage(args.voltage)

    @classmethod
    def add_setup_arguments(cls, parser):
        pass

    async def setup(self, args):
        pass

    @classmethod
    def add_run_arguments(cls, parser):
        pass

    async def run(self, args):
        raise GlasgowAppletError("This applet can only be used in REPL mode.")

    @classmethod
    def add_repl_arguments(cls, parser):
        pass

    @property
    def _iface_attrs(self):
        for attr in dir(self):
            if attr.endswith("iface"):
                yield attr

    def _code_locals(self, args):
        return {
            "asyncio": asyncio,
            "self": self,
            "args": args,
            "device": self.device,
            **{attr: getattr(self, attr) for attr in self._iface_attrs}
        }

    async def repl(self, args):
        self.logger.info("dropping to REPL; use %s to see available APIs",
            ", ".join(f"'help({attr})'" for attr in self._iface_attrs))
        await AsyncInteractiveConsole(
            locals=self._code_locals(args),
            run_callback=self.assembly.flush_pipes
        ).interact()

    async def script(self, args, code):
        result = eval(code, self._code_locals(args))
        if asyncio.iscoroutine(result):
            await result

    @classmethod
    def tests(cls):
        return None


class GlasgowAppletV2TestCase(unittest.TestCase):
    def __init_subclass__(cls, applet, **kwargs):
        super().__init_subclass__(**kwargs)

        cls.applet_cls = applet

    @classmethod
    def _parse_args(cls, args, *, mode=None):
        access = GlasgowAppletArguments("applet")
        parser = argparse.ArgumentParser()
        cls.applet_cls.add_build_arguments(parser, access)
        if mode != "build":
            cls.applet_cls.add_setup_arguments(parser)
        match mode:
            case "run":
                cls.applet_cls.add_run_arguments(parser)
            case "repl":
                cls.applet_cls.add_repl_arguments(parser)
        match args:
            case None:
                return parser.parse_args([])
            case list():
                return parser.parse_args(args)
            case str():
                return parser.parse_args(shlex.split(args))
            case _:
                assert False

    def assertBuilds(self, args=None, *, revision=None):
        parsed_args = self._parse_args(args, mode="build")
        assembly = HardwareAssembly(revision=revision or self.applet_cls.required_revision)
        applet = self.applet_cls(assembly)
        applet.build(parsed_args)
        assembly.artifact().get_bitstream()


def applet_v2_simulation_test(*, prepare=None, args=None):
    def decorator(case):
        @functools.wraps(case)
        def wrapper(self):
            parsed_args = self._parse_args(args)
            assembly = SimulationAssembly()
            if prepare is not None:
                prepare(self, assembly)
            applet = self.applet_cls(assembly)
            applet.build(parsed_args)
            async def launch(ctx):
                await applet.setup(parsed_args)
                await case(self, applet, ctx)
            assembly.run(launch)
        return wrapper
    return decorator


def async_test(case):
    @functools.wraps(case)
    def wrapper(*args, **kwargs):
        thread_exn = None
        def run_case():
            nonlocal thread_exn
            loop = asyncio.new_event_loop()
            try:
                loop.run_until_complete(case(*args, **kwargs))
            except Exception as exn:
                thread_exn = exn
            finally:
                loop.close()

        thread = threading.Thread(target=run_case)
        thread.start()
        thread.join()
        if thread_exn is not None:
            raise thread_exn
    return wrapper


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
import sys
import unittest
import functools
import asyncio
import types
import threading
import inspect
import json
from amaranth.sim import *

from ..simulation.assembly import SimulationAssembly
from ..hardware.assembly import HardwareAssembly
from ..hardware.device import GlasgowDevice
from ..hardware.toolchain import find_toolchain
from ..hardware.platform.rev_ab import GlasgowRevABPlatform
from ..legacy import DeprecatedTarget, DeprecatedDevice


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
        if isinstance(obj, memoryview):
            return {"__class__": "memoryview", "hex": obj.hex()}
        raise TypeError("%s is not serializable" % type(obj))

    def __dump_stanza(self, stanza):
        if not self.__case._recording:
            return
        json.dump(fp=self.__fixture, default=self.__dump_object, obj=stanza)
        self.__fixture.write("\n")

    def __dump_method(self, call, kind, args, kwargs, result):
        self.__dump_stanza({
            "call":   call,
            "kind":   kind,
            "args":   args,
            "kwargs": kwargs,
            "result": result
        })

    def __getattr__(self, attr):
        mocked = getattr(self.__mocked, attr)
        if inspect.ismethod(mocked):
            def wrapper(*args, **kwargs):
                result = mocked(*args, **kwargs)
                if isinstance(result, AbstractAsyncContextManager):
                    @asynccontextmanager
                    async def cmgr_wrapper():
                        value = await result.__aenter__()
                        self.__dump_method(attr, "asynccontext.enter", (), {}, value)
                        try:
                            yield value
                        finally:
                            exc_type, exc_value, traceback = sys.exc_info()
                            self.__dump_method(attr, "asynccontext.exit", (exc_value,), {}, None)
                            await result.__aexit__(exc_type, exc_value, traceback)
                    return cmgr_wrapper()
                elif inspect.isawaitable(result):
                    async def coro_wrapper():
                        coro_result = await result
                        self.__dump_method(attr, "asyncmethod", args, kwargs, coro_result)
                        return coro_result
                    return coro_wrapper()
                else:
                    self.__dump_method(attr, "method", args, kwargs, result)
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
        if obj["__class__"] == "memoryview":
            return memoryview(bytes.fromhex(obj["hex"]))
        assert False

    def __load(self):
        json_str = self.__fixture.readline()
        return json.loads(s=json_str, object_hook=self.__load_object)

    @staticmethod
    def __upgrade(stanza):
        """Upgrade an object to the latest schema."""
        if "method" in stanza:
            stanza["call"] = stanza.pop("method")
            if stanza.pop("async"):
                stanza["kind"] = "asyncmethod"
            else:
                stanza["kind"] = "method"
        return stanza

    def __getattr__(self, attr):
        stanza = self.__upgrade(self.__load())
        self.__case.assertEqual(attr, stanza["call"])
        if stanza["kind"] == "asynccontext.enter":
            @asynccontextmanager
            async def mock():
                assert () == tuple(stanza["args"])
                assert {} == stanza["kwargs"]
                try:
                    yield stanza["result"]
                finally:
                    exc_type, exc_value, traceback = sys.exc_info()
                    exit_stanza = self.__load()
                    self.__case.assertEqual(attr, exit_stanza["call"])
                    self.__case.assertEqual("asynccontext.exit", exit_stanza["kind"])
                    self.__case.assertEqual((exc_value,), tuple(exit_stanza["args"]))
                    assert {} == exit_stanza["kwargs"]
                    assert None == exit_stanza["result"]
        elif stanza["kind"] == "asyncmethod":
            async def mock(*args, **kwargs):
                self.__case.assertEqual(args, tuple(stanza["args"]))
                self.__case.assertEqual(kwargs, stanza["kwargs"])
                return stanza["result"]
        elif stanza["kind"] == "method":
            def mock(*args, **kwargs):
                self.__case.assertEqual(args, tuple(stanza["args"]))
                self.__case.assertEqual(kwargs, stanza["kwargs"])
                return stanza["result"]
        else:
            assert False, f"unknown stanza {stanza['kind']}"
        return mock


class GlasgowAppletTestCase(unittest.TestCase):
    def __init_subclass__(cls, applet, **kwargs):
        super().__init_subclass__(**kwargs)

        cls.applet_cls  = applet

    def setUp(self):
        self.applet = self.applet_cls(None)

    def assertBuilds(self, args=[]):
        assembly = HardwareAssembly(revision=self.applet_cls.required_revision)
        target = DeprecatedTarget(assembly)

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
    synthesis_available = find_toolchain(quiet=True) is not None
    return unittest.skipUnless(synthesis_available, "synthesis not available")(case)


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
