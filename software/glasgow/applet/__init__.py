import re
import argparse
import functools
from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from contextlib import AbstractAsyncContextManager, asynccontextmanager

from amaranth import *

from ..support.arepl import *
from ..support.plugin import *
from ..gateware.clockgen import *
from ..legacy import DeprecatedDemultiplexer, DeprecatedMultiplexer


__all__ = [
    "GlasgowAppletMetadata", "GlasgowAppletError", "GlasgowApplet", "GlasgowAppletArguments",
    "GlasgowAppletTool"
]


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


# A Glasgow applet is defined by a class; known applets are taken from a
# list of entry points in package metadata.  (In the Glasgow package, they
# are enumerated in the `[project.entry-points."glasgow.applet"]` section of
# the pyproject.toml.

class GlasgowApplet(metaclass=ABCMeta):
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
                raise GlasgowAppletError(f"clock {clock_name}: {e}")

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


@dataclass(frozen=True)
class PinArgument:
    number: int
    invert: bool = False

    def __str__(self):
        return f"{self.number}{'#' if self.invert else ''}"


class GlasgowAppletArguments:
    def _arg_error(self, message):
        raise argparse.ArgumentTypeError(f"applet {self._applet_name!r}: " + message)

    # First, define some state-less methods that just add arguments to an argparse instance.

    def _port_spec(self, arg):
        if not re.match(r"^[A-Z]+$", arg):
            self._arg_error(f"{arg} is not a valid port specification")
        return arg

    def _add_port_argument(self, parser, default):
        help = "bind the applet to port SPEC"
        if default is not None:
            help += " (default: %(default)s)"

        parser.add_argument(
            "--port", dest="port_spec", metavar="SPEC", type=self._port_spec,
            default=default, help=help)

    def _add_port_voltage_arguments(self, parser, default):
        g_voltage = parser.add_mutually_exclusive_group(required=True)
        g_voltage.add_argument(
            "-V", "--voltage", metavar="VOLTS", type=float, nargs="?", default=default,
            help="set I/O port voltage explicitly")
        g_voltage.add_argument(
            "-M", "--mirror-voltage", action="store_true", default=False,
            help="sense and mirror I/O port voltage")
        g_voltage.add_argument(
            "--keep-voltage", action="store_true", default=False,
            help="do not change I/O port voltage")

    def _mandatory_pin_argument(self, arg):
        if m := re.match(r"^[0-9]+#?$", arg):
            return PinArgument(int(arg.replace("#", "")), invert=arg.endswith("#"))
        else:
            self._arg_error(f"{arg} is not a valid pin number")

    def _optional_pin_argument(self, arg):
        if arg == "-":
            return None
        return self._mandatory_pin_argument(arg)

    def _add_pin_argument(self, parser, name, default, required, help):
        if help is None:
            help = f"bind the applet I/O line {name!r} to pin NUM"
        if default is not None:
            default = PinArgument(default)
            help += f" (default: {default})"

        if required:
            type = self._mandatory_pin_argument
            if default is not None:
                required = False
        else:
            type = self._optional_pin_argument

        opt_name = "--" + name.lower().replace("_", "-")
        parser.add_argument(
            opt_name, dest=name, metavar="NUM",
            type=type, default=default, required=required, help=help)

        deprecated_opt_name = "--pin-" + name.lower().replace("_", "-")
        parser.add_argument(
            deprecated_opt_name, dest=name, metavar="NUM",
            type=lambda arg: self._arg_error(f"use {opt_name} {arg} instead"),
            help=argparse.SUPPRESS)

    def _pin_set(self, width, arg):
        if arg == "":
            pin_args = []
        elif re.match(r"^[0-9]+:[0-9]+#?$", arg):
            first, last = map(int, arg.replace("#", "").split(":"))
            pin_args = [PinArgument(int(number), invert=arg.endswith("#"))
                        for number in range(first, last + 1)]
        elif re.match(r"((^|,)[0-9]+#?)+$", arg):
            pin_args = [PinArgument(int(number.replace("#", "")), invert=number.endswith("#"))
                        for number in arg.split(",")]
        else:
            self._arg_error(f"{arg} is not a valid pin number set")
        if len(pin_args) not in width:
            if len(width) == 1:
                width_desc = str(width[0])
            else:
                width_desc = f"{width.start}..{width.stop - 1}"
            self._arg_error(f"set {arg} includes {len(pin_args)} pins, but "
                            f"{width_desc} pins are required")
        return pin_args

    def _add_pin_set_argument(self, parser, name, width, default, required, help):
        if help is None:
            help = f"bind the applet I/O lines {name!r} to pins SET"
        if default is not None:
            default = [PinArgument(number) for number in default]
            if default:
                help += f" (default: {', '.join(map(str, default))})"
            else:
                help += " (default is empty)"
        if required and default is not None:
            required = False

        opt_name = "--" + name.lower().replace("_", "-")
        parser.add_argument(
            opt_name, dest=name, metavar="SET",
            type=functools.partial(self._pin_set, width), default=default, required=required,
            help=help)

        deprecated_opt_name = "--pins-" + name.lower().replace("_", "-")
        parser.add_argument(
            deprecated_opt_name, dest=name, metavar="SET",
            type=lambda arg: self._arg_error(f"use {opt_name} {arg} instead"),
            help=argparse.SUPPRESS)

    # Second, define a stateful interface that has features like automatically assigning
    # default pin numbers.

    def __init__(self, applet_name, default_port, pin_count):
        self._applet_name  = applet_name
        self._default_port = default_port
        self._free_pins    = list(range(pin_count))

    @staticmethod
    def _get_free(free_list):
        if len(free_list) > 0:
            result = free_list[0]
            free_list.remove(result)
            return result

    def add_build_arguments(self, parser):
        self._add_port_argument(parser, self._default_port)

    def add_pin_argument(self, parser, name, default=None, required=False, help=None):
        if default is True:
            default = self._get_free(self._free_pins)
        self._add_pin_argument(parser, name, default, required, help)

    def add_pin_set_argument(self, parser, name, width, default=None, required=False, help=None):
        if isinstance(width, int):
            width = range(width, width + 1)
        if default is True and len(self._free_pins) >= width.start:
            default = [self._get_free(self._free_pins) for _ in range(width.start)]
        elif isinstance(default, int) and len(self._free_pins) >= default:
            default = [self._get_free(self._free_pins) for _ in range(default)]
        self._add_pin_set_argument(parser, name, width, default, required, help)

    def add_run_arguments(self, parser):
        self._add_port_voltage_arguments(parser, default=None)


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
        self.applet = self.applet_cls()

    def assertBuilds(self, args=[]):
        assembly = HardwareAssembly(revision=self.applet_cls.required_revision)
        target = DeprecatedTarget(assembly)

        parser = argparse.ArgumentParser()
        access_args = GlasgowAppletArguments("applet", "AB", 16)
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

            access_args = GlasgowAppletArguments("applet", "AB", 16)
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
                access_args = GlasgowAppletArguments(self.applet, default_port="AB", pin_count=16)
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
