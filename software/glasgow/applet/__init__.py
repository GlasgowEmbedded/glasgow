import re
import argparse
import functools
from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Optional

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
class VoltArgument:
    ports: str          # e.g. "A" or "AB"
    value: float = None # e.g. 5.0 or 3.3 for that many volts
    sense: str   = None # e.g. "A" for measuring voltage on S input of port A

    @classmethod
    def from_str(cls, value) -> list['VoltArgument']:
        result = []
        for clause in value.split(","):
            if m := re.match(r"^([0-9]+(\.[0-9]+)?)$", value):
                volts = float(m.group(1))
                result.append(VoltArgument(ports="AB", value=volts))
            elif m := re.match(r"^([A-Z]+)=([0-9]+(\.[0-9]+)?)$", value):
                ports, volts = m.group(1), float(m.group(2))
                result.append(VoltArgument(ports=ports, value=volts))
            elif m := re.match(r"^([A-Z]+)=S([A-Z])$", value):
                ports, sense = m.group(1), m.group(2)
                result.append(VoltArgument(ports=ports, sense=sense))
            else:
                raise ValueError(f"{clause!r} is not a valid voltage argument")
        return result

    def __str__(self):
        if self.sense is not None:
            return f"{self.ports}=S{self.sense}"
        else:
            return f"{self.ports}={self.value:.2f}"


@dataclass(frozen=True)
class PinArgument:
    port:   str
    pin:    int
    invert: bool = False

    @classmethod
    def from_str(cls, value) -> list['PinArgument']:
        result = []
        for clause in value.split(","):
            if clause == "-":
                pass
            elif m := re.match(r"^([A-Z])([0-9]+)(#)?$", clause):
                port, pin, invert = m.group(1), int(m.group(2)), bool(m.group(3))
                result.append(cls(port=port, pin=pin, invert=invert))
            elif m := re.match(r"^([A-Z])([0-9]+):([0-9]+)(#)?$", clause):
                port, pin_first, pin_last, invert = \
                    m.group(1), int(m.group(2)), int(m.group(3)), bool(m.group(4))
                if pin_last >= pin_first:
                    for pin in range(pin_first, pin_last + 1, +1):
                        result.append(cls(port=port, pin=pin, invert=invert))
                else:
                    for pin in range(pin_first, pin_last - 1, -1):
                        result.append(cls(port=port, pin=pin, invert=invert))
            else:
                raise ValueError(f"{clause!r} is not a valid pin argument")
        return result

    @property
    def _legacy_number(self):
        match self.port:
            case "A": return 0 + self.pin
            case "B": return 8 + self.pin
            case _: assert False

    def __str__(self):
        return f"{self.port}{self.pin}{'#' if self.invert else ''}"


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
                return PinArgument.from_str(result)[0]

        if width is None:
            match default:
                case None:
                    pass
                case True:
                    default = get_free_pin()
                case _:
                    default = PinArgument.from_str(default)[0]

            metavar = "PIN"
            if help is None:
                help = f"bind the applet I/O line {name!r} to {metavar}"
            if default:
                help += f" (default: {default})"

            def pin_arg(arg):
                try:
                    result = PinArgument.from_str(arg)
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
                case int():
                    default = [get_free_pin() for _ in range(default)]
                case _:
                    default = PinArgument.from_str(default)

            metavar = "PINS"
            if help is None:
                help = f"bind the applet I/O lines {name!r} to {metavar}"
            if default:
                help += f" (default: {','.join(str(pin) for pin in default)})"
            else:
                help += " (default is empty)"

            def pin_arg(arg):
                try:
                    result = PinArgument.from_str(arg)
                except ValueError as e:
                    self._arg_error(str(e))
                if len(result) not in width:
                    if len(width) == 1:
                        width_desc = f"{width.start}"
                    else:
                        width_desc = f"{width.start}..{width.stop - 1}"
                    self._arg_error(f"expected {width_desc} pins, got {len(result)} pins")
                return result

        if required and default is not None:
            required = False

        parser.add_argument(
            f"--{name.lower().replace('_', '-')}", dest=name, metavar=metavar,
            type=pin_arg, default=default, required=required, help=help)

    def add_voltage_argument(self, parser):
        parser.add_argument(
            "-V", "--voltage", metavar="SPEC",
            type=VoltArgument.from_str, default=[], action="extend",
            help="configure I/O port voltage to SPEC (e.g.: '3.3', 'A=5.0,B=3.3', 'A=SA')")

    def add_build_arguments(self, parser):
        pass

    def add_run_arguments(self, parser):
        self.add_voltage_argument(parser)


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
