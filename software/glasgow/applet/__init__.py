from abc import ABCMeta, abstractmethod
import os
import shlex
import unittest
import argparse
import functools
import asyncio
import threading

from ..support.plugin import PluginMetadata
from ..support.arepl import AsyncInteractiveConsole
from ..support.mock import MockRecorder, MockReplayer
from ..abstract import GlasgowVio, GlasgowPin, AbstractAssembly
from ..hardware.toolchain import find_toolchain
from ..hardware.device import GlasgowDevice
from ..hardware.assembly import HardwareAssembly
from ..simulation.assembly import SimulationAssembly
from ..gateware.clockgen import ClockGen


__all__ = [
    "GlasgowAppletError",
    "GlasgowAppletMetadata", "GlasgowAppletArguments", "GlasgowAppletV2",
    "GlasgowAppletToolMetadata", "GlasgowAppletTool",
    "synthesis_test", "async_test",
    "GlasgowAppletV2TestCase", "applet_v2_simulation_test", "applet_v2_hardware_test",
    # deprecated:
    "GlasgowApplet", "GlasgowAppletTestCase", "applet_simulation_test", "applet_hardware_test"
]


class GlasgowAppletMetadata(PluginMetadata):
    # A Glasgow applet is defined by a class; known applets are taken from a
    # list of entry points in package metadata.  (In the Glasgow package, they
    # are enumerated in the `[project.entry-points."glasgow.applet"]` section of
    # the pyproject.toml.
    GROUP_NAME = "glasgow.applet"


class GlasgowAppletToolMetadata(PluginMetadata):
    # A Glasgow applet tool is defined by a class; known applets are taken from a
    # list of entry points in package metadata.  (In the Glasgow package, they
    # are enumerated in the `[project.entry-points."glasgow.applet.tool"]` section of
    # the pyproject.toml.
    GROUP_NAME = "glasgow.applet.tool"


class GlasgowAppletError(Exception):
    """An exception raised when an applet encounters an error."""


class GlasgowAppletV2(metaclass=ABCMeta):
    preview = False
    help = "applet help missing"
    description = "applet description missing"
    required_revision = "A0"

    def __init__(self, assembly: AbstractAssembly):
        self._assembly = assembly

        if isinstance(assembly, HardwareAssembly):
            if assembly.revision < self.required_revision:
                self.logger.warning(f"applet requires a rev{self.required_revision}+ device, "
                                    f"use on a rev{assembly.revision} device is unsupported")
            if self.preview:
                self.logger.warning(f"applet is PREVIEW QUALITY and may CORRUPT DATA")

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

    @classmethod
    def _get_argparser_for_sphinx(cls, name):
        parser = argparse.ArgumentParser(name, description=cls.description)
        cls.add_build_arguments(parser, GlasgowAppletArguments(name))
        cls.add_setup_arguments(parser)
        cls.add_run_arguments(parser)
        return parser


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


class GlasgowAppletTool:
    def __init_subclass__(cls, applet, **kwargs):
        super().__init_subclass__(**kwargs)

        cls.logger = applet.logger

    @classmethod
    def add_arguments(cls, parser):
        pass

    async def run(self, args):
        pass

    @classmethod
    def _get_argparser_for_sphinx(cls, name):
        parser = argparse.ArgumentParser(name, description=cls.description)
        cls.add_arguments(parser)
        return parser


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


def synthesis_test(case):
    synthesis_available = find_toolchain(quiet=True) is not None
    return unittest.skipUnless(synthesis_available, "synthesis not available")(case)


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


def applet_v2_simulation_test(*, prepare=None, args=None):
    def decorator(case):
        @functools.wraps(case)
        def wrapper(self):
            parsed_args = self._parse_args(args)
            assembly = SimulationAssembly()
            if prepare is not None:
                prepare(self, assembly)
            applet: GlasgowAppletV2 = self.applet_cls(assembly)
            applet.build(parsed_args)
            async def launch(ctx):
                await applet.setup(parsed_args)
                await case(self, applet, ctx)
            assembly.run(launch)
        return wrapper
    return decorator


def applet_v2_hardware_test(*, prepare=None, args=None, mock):
    def decorator(case):
        @functools.wraps(case)
        @async_test
        async def wrapper(self):
            *mock_path, mock_attr = mock.split(".")
            parsed_args = self._parse_args(args)
            fixture_path = os.path.join(
                os.path.dirname(case.__code__.co_filename), "fixtures",
                case.__name__ + ".json")
            if not os.path.exists(fixture_path):
                # Record mode
                device = GlasgowDevice()
                assembly = HardwareAssembly(device=device)
                applet: GlasgowAppletV2 = self.applet_cls(assembly)
                applet.build(parsed_args)
                async with assembly:
                    os.makedirs(os.path.dirname(fixture_path), exist_ok=True)
                    with open(f"{fixture_path}.new", "w") as fixture:
                        await applet.setup(parsed_args)
                        if prepare is not None:
                            await prepare(self, assembly)
                        mock_obj = applet
                        for attr in mock_path:
                            mock_obj = getattr(mock_obj, attr)
                        setattr(mock_obj, mock_attr,
                            MockRecorder(self, fixture, getattr(mock_obj, mock_attr)))
                        await case(self, applet)
                    os.rename(f"{fixture_path}.new", fixture_path)
                device.close()
            else:
                # Replay mode
                assembly = HardwareAssembly(revision=self.applet_cls.required_revision)
                applet: GlasgowAppletV2 = self.applet_cls(assembly)
                applet.build(parsed_args)
                with open(fixture_path, "r") as fixture:
                    mock_obj = applet
                    for attr in mock_path:
                        mock_obj = getattr(mock_obj, attr)
                    setattr(mock_obj, mock_attr, MockReplayer(self, fixture))
                    await case(self, applet)
        return wrapper
    return decorator


from ._legacy import *
