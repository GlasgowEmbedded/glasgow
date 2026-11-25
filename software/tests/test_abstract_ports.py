import argparse
import asyncio
import dataclasses
import unittest
from dataclasses import dataclass
from types import SimpleNamespace

from amaranth import Signal
from amaranth.lib import io, stream

from glasgow.support import logging
from glasgow.abstract import *
from glasgow.applet import GlasgowAppletArguments
from glasgow.hardware.assembly import HardwareAssembly
from glasgow.hardware import assembly as assembly_module
from glasgow.simulation.assembly import SimulationAssembly


@glasgow_ports
class I2CPorts:
    supply: GlasgowSupply = GlasgowSupply.field(voltage_min=1.8, voltage_max=3.3)
    """device power"""
    scl: io.PortLike = GlasgowPin.field(power=supply, default="A0")
    """I2C clock"""
    sda: io.PortLike = GlasgowPin.field(power=supply, default="A1")
    """I2C data"""
    int: io.PortLike | None = GlasgowPin.field(power=supply, invert=True)
    """interrupt (active low)"""


@glasgow_ports
class TwoSupplyPorts:
    i2c_supply: GlasgowSupply = GlasgowSupply.field(voltage_min=1.8, voltage_max=3.3)
    spi_supply: GlasgowSupply = GlasgowSupply.field(voltage_min=3.0, voltage_max=3.6)
    scl: io.PortLike = GlasgowPin.field(power=i2c_supply)
    sda: io.PortLike = GlasgowPin.field(power=i2c_supply)
    clk: io.PortLike = GlasgowPin.field(power=spi_supply)


@glasgow_ports
class FixedSupplyPorts:
    supply: GlasgowSupply = GlasgowSupply(voltage=3.3)
    data: io.PortLike = GlasgowPin.field(power=supply, width=range(1, 5), default="B0")


def parse(cls, argv):
    parser = argparse.ArgumentParser(exit_on_error=False)
    GlasgowAppletArguments("test").add_ports_arguments(parser, cls)
    return parser, parser.parse_args(argv)


class GlasgowSupplyTestCase(unittest.TestCase):
    def test_exclusive(self):
        with self.assertRaises(ValueError):
            GlasgowSupply(voltage=3.3, sense="A")

    def test_sense_port_without_supply(self):
        with self.assertRaises(ValueError):
            GlasgowSupply(sense="LED")

    def test_parse(self):
        self.assertEqual(GlasgowSupply.parse("3.3"), GlasgowSupply(voltage=3.3))
        self.assertEqual(GlasgowSupply.parse("SA"), GlasgowSupply(sense=GlasgowPort.A))
        with self.assertRaises(ValueError):
            GlasgowSupply.parse("A=3.3")

    def test_field_bad_range(self):
        with self.assertRaises(ValueError):
            GlasgowSupply.field(voltage_min=3.3, voltage_max=1.8)

    def test_pin_field_bad_width(self):
        with self.assertRaises(ValueError):
            GlasgowPin.field(width=0)


class AddPortsArgumentsTestCase(unittest.TestCase):
    def test_single_supply_is_voltage(self):
        _, args = parse(I2CPorts, ["-V", "3.3", "--int", "A2"])
        self.assertEqual(args.supply, GlasgowSupply(voltage=3.3))
        _parser, args = parse(I2CPorts, ["--voltage", "SB", "--int", "A2"])
        self.assertEqual(args.supply, GlasgowSupply(sense=GlasgowPort.B))

    def test_defaults(self):
        _, args = parse(I2CPorts, ["--int", "NC"])
        self.assertEqual(args.scl, (GlasgowPin("A", 0),))
        self.assertEqual(args.int, ())
        self.assertIsNone(args.supply)

    def test_required_vs_optional(self):
        with self.assertRaises(SystemExit):
            parser = argparse.ArgumentParser()
            GlasgowAppletArguments("test").add_ports_arguments(parser, TwoSupplyPorts)
            parser.parse_args([])
        # `int` is optional because of its annotation, `scl` is required (no default).
        parser = argparse.ArgumentParser()
        GlasgowAppletArguments("test").add_ports_arguments(parser, I2CPorts)
        actions = {action.dest: action for action in parser._actions}
        self.assertFalse(actions["int"].required)

    def test_multiple_supplies(self):
        _, args = parse(TwoSupplyPorts, [
            "--i2c-voltage", "1.8", "--spi-voltage", "3.3",
            "--scl", "A0", "--sda", "A1", "--clk", "B0"])
        self.assertEqual(args.i2c_supply.voltage, 1.8)
        self.assertEqual(args.spi_supply.voltage, 3.3)

    def test_voltage_out_of_range(self):
        parser = argparse.ArgumentParser(exit_on_error=False)
        GlasgowAppletArguments("test").add_ports_arguments(parser, I2CPorts)
        with self.assertRaisesRegex(argparse.ArgumentError, "supports 1.80..3.30 V"):
            parser.parse_args(["-V", "5.0", "--int", "A2"])

    def test_fixed_supply_has_no_option(self):
        parser, args = parse(FixedSupplyPorts, [])
        self.assertNotIn("--voltage", [flag for a in parser._actions for flag in a.option_strings])
        self.assertFalse(hasattr(args, "supply"))

    def test_width(self):
        parser = argparse.ArgumentParser(exit_on_error=False)
        GlasgowAppletArguments("test").add_ports_arguments(parser, FixedSupplyPorts)
        self.assertEqual(len(parser.parse_args(["--data", "B0:3"]).data), 4)
        with self.assertRaisesRegex(argparse.ArgumentError, "expected 1..4 pins, got 5"):
            parser.parse_args(["--data", "B0:4"])

    def test_help_from_docstring(self):
        parser = argparse.ArgumentParser()
        GlasgowAppletArguments("test").add_ports_arguments(parser, I2CPorts)
        helps = {action.dest: action.help for action in parser._actions}
        self.assertIn("I2C clock", helps["scl"])
        self.assertIn("interrupt (active low)", helps["int"])
        self.assertIn("device power", helps["supply"])

    def test_help_from_inherited_docstring(self):
        # The pins of a subclass reuse the supply of the base class, as `ProgramICE40FlashPorts`
        # does with `Memory25QPorts`; both the inherited and the new fields have documentation.
        supply_field = I2CPorts.__dataclass_fields__["supply"]

        @glasgow_ports
        class Extended(I2CPorts):
            reset: io.PortLike = GlasgowPin.field(power=supply_field, default="A2")
            """target reset"""

        parser, _ = parse(Extended, [])
        helps = {action.dest: action.help for action in parser._actions}
        self.assertIn("I2C clock", helps["scl"])
        self.assertIn("target reset", helps["reset"])

    def test_foreign_supply_rejected(self):
        foreign_supply = I2CPorts.__dataclass_fields__["supply"]

        @glasgow_ports
        class Bad:
            pin: io.PortLike = GlasgowPin.field(power=foreign_supply)

        with self.assertRaisesRegex(TypeError, "not a \\(previous\\) field"):
            SimulationAssembly().add_ports(Bad, {"pin": "A0"})

    def test_not_kw_only_rejected(self):
        pin_field = GlasgowPin.field(default="A0")

        @dataclass
        class Bad:
            pin: io.PortLike = pin_field

        with self.assertRaisesRegex(TypeError, "not keyword-only"):
            SimulationAssembly().add_ports(Bad, {"pin": "A0"})
        with self.assertRaisesRegex(TypeError, "not keyword-only"):
            GlasgowAppletArguments("test").add_ports_arguments(argparse.ArgumentParser(), Bad)

    def test_decorator_is_kw_only_dataclass(self):
        @glasgow_ports
        class Good:
            a: io.PortLike | None = GlasgowPin.field()
            b: io.PortLike = GlasgowPin.field(default="A0")

        with self.assertRaises(TypeError):
            Good(None, None) # positional arguments are rejected
        self.assertEqual(Good(a=None, b=None).a, None)

    def test_decorator_forwards_arguments(self):
        @glasgow_ports(frozen=True)
        class Frozen:
            a: io.PortLike | None = GlasgowPin.field()

        ports = Frozen(a=None)
        with self.assertRaises(dataclasses.FrozenInstanceError):
            ports.a = None
        self.assertEqual(SimulationAssembly().add_ports(Frozen, {"a": None}), ports)

        @glasgow_ports(kw_only=True) # explicitly redundant, but harmless
        class Redundant:
            a: io.PortLike | None = GlasgowPin.field()

        Redundant(a=None)

    def test_decorator_rejects_kw_only_false(self):
        with self.assertRaisesRegex(TypeError, "kw_only=False"):
            glasgow_ports(kw_only=False)

    def test_undeclared_field_rejected(self):
        @dataclass(kw_only=True)
        class Bad:
            pin: io.PortLike

        with self.assertRaisesRegex(TypeError, "not declared"):
            SimulationAssembly().add_ports(Bad, {"pin": "A0"})


class RecordingAssembly(SimulationAssembly):
    """A simulation assembly that records the voltages and pulls that were requested."""

    def __init__(self):
        super().__init__()
        self.voltages = [] # (port, vio, limits)
        self.pulls    = [] # (str(pin), state)

    def set_port_voltage(self, port, vio, *, limits=None):
        self.voltages.append((port, vio, limits))

    def set_pin_pull(self, pin, state):
        self.pulls.append((str(pin), state))


class AddPortsTestCase(unittest.TestCase):
    def test_simulation(self):
        assembly = SimulationAssembly()
        _, args = parse(I2CPorts, ["-V", "3.3", "--int", "A2"])
        ports = assembly.add_ports(I2CPorts, args)
        self.assertIsInstance(ports, I2CPorts)
        self.assertIsInstance(ports.scl, io.PortLike)
        self.assertEqual(ports.supply.voltage, 3.3)
        self.assertEqual(len(ports.int), 1)

    def test_optional_absent(self):
        ports = SimulationAssembly().add_ports(I2CPorts, {"scl": "A0", "sda": "A1", "int": None})
        self.assertIsNone(ports.int)
        self.assertIsNone(ports.supply.voltage)

    def test_multi_pin_width(self):
        ports = SimulationAssembly().add_ports(FixedSupplyPorts, {"data": "B0:2"})
        self.assertEqual(len(ports.data), 3)
        self.assertEqual(ports.supply, GlasgowSupply(voltage=3.3))

    def test_wrong_width(self):
        with self.assertRaisesRegex(ValueError, "got 5"):
            SimulationAssembly().add_ports(FixedSupplyPorts, {"data": "B0:4"})

    def test_missing_required(self):
        with self.assertRaisesRegex(ValueError, "required"):
            SimulationAssembly().add_ports(FixedSupplyPorts, {})

    def test_programmatic_range_check(self):
        with self.assertRaises(VoltageConflictError):
            SimulationAssembly().add_ports(I2CPorts,
                {"scl": "A0", "sda": "A1", "int": None, "supply": "5.0"})

    def test_voltage_requested_per_port(self):
        assembly = RecordingAssembly()
        assembly.add_ports(TwoSupplyPorts, {
            "i2c_supply": "1.8", "spi_supply": GlasgowSupply(voltage=3.3),
            "scl": "A0", "sda": "A1", "clk": "B0"})
        self.assertEqual([(port, vio) for port, vio, _ in assembly.voltages], [
            (GlasgowPort.A, GlasgowVio(1.8)),
            (GlasgowPort.B, GlasgowVio(3.3)),
        ])

    def test_unspecified_supply_requests_nothing(self):
        assembly = RecordingAssembly()
        assembly.add_ports(I2CPorts, {"scl": "A0", "sda": "A1", "int": None})
        self.assertEqual(assembly.voltages, [])

    def test_sense(self):
        assembly = RecordingAssembly()
        assembly.add_ports(TwoSupplyPorts, {
            "i2c_supply": "SA", "spi_supply": "3.3",
            "scl": "A0", "sda": "B0", "clk": "B1"})
        # Both ports follow the sense input of A; port A follows its own.
        # (The SPI supply also requests a fixed voltage for B; detecting that conflict is up to the
        # hardware assembly.)
        requested = [(port, vio) for port, vio, _ in assembly.voltages]
        self.assertIn((GlasgowPort.A, GlasgowVio(sense=GlasgowPort.A)), requested)
        self.assertIn((GlasgowPort.B, GlasgowVio(sense=GlasgowPort.A)), requested)

    def test_sense_passes_limits(self):
        assembly = RecordingAssembly()
        assembly.add_ports(I2CPorts, {"scl": "B0", "sda": "B1", "int": None, "supply": "SA"})
        self.assertEqual(assembly.voltages, [
            (GlasgowPort.B, GlasgowVio(sense=GlasgowPort.A), (1.8, 3.3))
        ])

    def test_pull(self):
        @glasgow_ports
        class Pulled:
            a: io.PortLike = GlasgowPin.field(pull="high")
            b: io.PortLike = GlasgowPin.field(pull=PullState.Low, invert=True)
            c: io.PortLike | None = GlasgowPin.field(pull="high")
            d: io.PortLike = GlasgowPin.field(width=2, pull="low")

        assembly = RecordingAssembly()
        assembly.add_ports(Pulled, {"a": "A0", "b": "A1", "c": None, "d": "A2,A3"})
        # inversion is reflected in the pin handed to `set_pin_pull`, which flips the state
        self.assertEqual(assembly.pulls, [
            ("A0", PullState.High), ("A1#", PullState.Low),
            ("A2", PullState.Low), ("A3", PullState.Low)
        ])

    def test_use_supply(self):
        assembly = RecordingAssembly()
        pins = GlasgowPin.parse("B1,A0,A3")
        assembly.use_supply(GlasgowSupply(voltage=1.8), pins)
        assembly.use_supply(GlasgowSupply(), pins) # unspecified: nothing to request
        assembly.use_supply(GlasgowSupply(sense="A"), pins, limits=(1.8, 3.3))
        self.assertEqual(assembly.voltages, [
            (GlasgowPort.A, GlasgowVio(1.8), None),
            (GlasgowPort.B, GlasgowVio(1.8), None),
            (GlasgowPort.A, GlasgowVio(sense=GlasgowPort.A), (1.8, 3.3)),
            (GlasgowPort.B, GlasgowVio(sense=GlasgowPort.A), (1.8, 3.3)),
        ])

    def test_invert(self):
        assembly = HardwareAssembly(revision="C3")
        with assembly.add_applet(SimpleNamespace(logger=logging.getLogger("test"))):
            ports = assembly.add_ports(I2CPorts, {"scl": "A0", "sda": "A1", "int": "A2"})
            self.assertEqual(ports.scl.io_port.invert, (False,))
            self.assertEqual(ports.int.io_port.invert, (True,))
            # inverting at the field level composes with inverting in the pin specification
            ports = assembly.add_ports(I2CPorts, {"scl": "B0", "sda": "B1", "int": "B2#"})
            self.assertEqual(ports.int.io_port.invert, (False,))


class VoltageConflictTestCase(unittest.TestCase):
    def applet(self, name):
        return SimpleNamespace(logger=logging.getLogger(name))

    def test_conflicting_applets(self):
        assembly = HardwareAssembly(revision="C3")
        with assembly.add_applet(self.applet("foo")):
            assembly.add_ports(FixedSupplyPorts, {"data": "A0"})
        with assembly.add_applet(self.applet("bar")):
            with self.assertRaisesRegex(VoltageConflictError, "foo"):
                assembly.add_ports(I2CPorts, {
                    "scl": "A1", "sda": "A2", "int": None, "supply": "1.8"
                })

    def test_agreeing_applets(self):
        assembly = HardwareAssembly(revision="C3")
        with assembly.add_applet(self.applet("foo")):
            assembly.add_ports(FixedSupplyPorts, {"data": "A0"})
        with assembly.add_applet(self.applet("bar")):
            assembly.add_ports(I2CPorts, {
                "scl": "A1", "sda": "A2", "int": None, "supply": "3.3"
            })


class FakeDevice:
    def __init__(self, voltages):
        self.voltages = voltages
        self.calls = []

    async def measure_voltage(self, port):
        self.calls.append(("measure", port))
        return self.voltages[port]

    async def mirror_voltage(self, port, sense):
        self.calls.append(("mirror", port, sense))
        self.voltages[port] = self.voltages[sense]
        return self.voltages[sense]

    async def get_voltage(self, port):
        return self.voltages.get(port, 0.0)

    async def set_voltage(self, spec, value):
        self.calls.append(("set", spec, value))

    all_ports = "ABCD"


class SenseRangeTestCase(unittest.TestCase):
    def configure(self, device, pin="B"):
        assembly = HardwareAssembly(revision="C3")
        assembly._running = True
        assembly._device = device
        with assembly.add_applet(SimpleNamespace(logger=logging.getLogger("test"))):
            assembly.add_ports(I2CPorts, {
                "scl": f"{pin}0", "sda": f"{pin}1", "int": None, "supply": "SA"
            })
        asyncio.run(assembly.configure_ports())

    def test_in_range(self):
        device = FakeDevice({"A": 3.3})
        self.configure(device)
        self.assertEqual(device.calls, [("measure", "A"), ("mirror", "B", "A")])

    def test_follow_own_sense_input(self):
        device = FakeDevice({"A": 3.3})
        self.configure(device, pin="A")
        self.assertEqual(device.calls, [("measure", "A"), ("mirror", "A", "A")])

    def test_unpowered_bank_warns(self):
        device = FakeDevice({"A": 3.3})
        assembly = HardwareAssembly(revision="C3")
        assembly._running = True
        assembly._device = device
        with assembly.add_applet(SimpleNamespace(logger=logging.getLogger("test"))):
            assembly.add_ports(I2CPorts, {"scl": "B0", "sda": "B1", "int": None, "supply": None})
        with self.assertLogs(assembly_module.logger, "WARNING"):
            asyncio.run(assembly.configure_ports())

    def test_follow_sense_on_all_ports(self):
        device = FakeDevice({"A": 3.3})
        assembly = HardwareAssembly(revision="C3")
        assembly._running = True
        assembly._device = device
        with assembly.add_applet(SimpleNamespace(logger=logging.getLogger("test"))):
            assembly.set_port_voltage(GlasgowPort.ALL, GlasgowVio(sense="A"), limits=(3.0, 3.6))
        asyncio.run(assembly.configure_ports())
        self.assertEqual(device.calls, [("measure", "A"), ("mirror", "ABCD", "A")])

    def test_within_margin(self):
        self.configure(FakeDevice({"A": 3.35}))

    def test_out_of_range_is_rejected_before_mirroring(self):
        device = FakeDevice({"A": 5.0})
        with self.assertRaisesRegex(VoltageConflictError, "5.00 V"):
            self.configure(device)
        self.assertEqual(device.calls, [("measure", "A")])

    def test_unpowered_sense_port_is_rejected(self):
        device = FakeDevice({"A": 0.0})
        with self.assertRaisesRegex(VoltageConflictError, "0.00 V"):
            self.configure(device)
        self.assertEqual(device.calls, [("measure", "A")])


class InputValidationTestCase(unittest.TestCase):
    def test_pin_all_port(self):
        with self.assertRaisesRegex(ValueError, "cannot identify a pin"):
            GlasgowPin(GlasgowPort.ALL, 0)
        self.assertEqual(GlasgowPin("A", 3), GlasgowPin(GlasgowPort.A, 3))

    def test_pin_without_legacy_number(self):
        with self.assertRaisesRegex(ValueError, "legacy number"):
            _ = GlasgowPin(GlasgowPort.SYN, 0)._legacy_number

    def test_analog_all_port(self):
        with self.assertRaisesRegex(ValueError, "cannot identify an analog channel"):
            GlasgowAnalog(GlasgowPort.ALL, GlasgowAnalog.Nodes.Differential)

    def test_clock_divisor_round_mode(self):
        with self.assertRaisesRegex(ValueError, "round_mode"):
            ClockDivisor(logging.getLogger("test"), None, ref_period=1e-6, tolerance=0.01,
                         round_mode="ceil", name="test")

    def test_use_voltage(self):
        assembly = RecordingAssembly()
        assembly.use_voltage({"A": 3, "B": 1.8, GlasgowPort.C: GlasgowVio(sense="A")})
        self.assertEqual(assembly.voltages, [
            (GlasgowPort.A, GlasgowVio(3.0), None),
            (GlasgowPort.B, GlasgowVio(1.8), None),
            (GlasgowPort.C, GlasgowVio(sense=GlasgowPort.A), None),
        ])

    def test_use_voltage_invalid(self):
        assembly = RecordingAssembly()
        for bad in ("3.3", None, True, [3.3]):
            with self.assertRaisesRegex(TypeError, "cannot use"):
                assembly.use_voltage({"A": bad})
        with self.assertRaises(ValueError):
            assembly.use_voltage({"Q": 3.3})
        self.assertEqual(assembly.voltages, [])

    def test_use_pulls(self):
        assembly = RecordingAssembly()
        pin = GlasgowPin(GlasgowPort.B, 0)
        assembly.use_pulls({"A0:1": "high", pin: PullState.Low, (pin, ~pin): "float"})
        self.assertEqual(assembly.pulls, [
            ("A0", PullState.High), ("A1", PullState.High), ("B0", PullState.Low),
            ("B0", PullState.Float), ("B0#", PullState.Float),
        ])

    def test_use_pulls_invalid(self):
        assembly = RecordingAssembly()
        pin = GlasgowPin(GlasgowPort.A, 0)
        with self.assertRaisesRegex(TypeError, "selection of pins"):
            assembly.use_pulls({42: "high"})
        with self.assertRaisesRegex(TypeError, "selection of pins"):
            assembly.use_pulls({(pin, "A1"): "high"})
        with self.assertRaisesRegex(TypeError, "pull state"):
            assembly.use_pulls({pin: 1})
        with self.assertRaises(ValueError):
            assembly.use_pulls({pin: "sideways"})
        self.assertEqual(assembly.pulls, [])

    def test_add_port(self):
        assembly = RecordingAssembly()
        port = io.SimulationPort("io", 2, name="p")
        self.assertIs(assembly.add_port(port, "x"), port)
        self.assertIsNone(assembly.add_port(None, "x"))
        self.assertIsNone(assembly.add_port("NC", "x"))
        with self.assertRaisesRegex(TypeError, "cannot add a port"):
            assembly.add_port(object(), "x")


class AssemblyErrorsTestCase(unittest.TestCase):
    def hardware(self, revision="C3"):
        return HardwareAssembly(revision=revision)

    def applet(self, name="test"):
        return SimpleNamespace(logger=logging.getLogger(name))

    def test_invalid_revision(self):
        with self.assertRaisesRegex(AssertionError, "invalid revision"):
            HardwareAssembly(revision="Z9")

    def test_nested_applet(self):
        assembly = self.hardware()
        with assembly.add_applet(self.applet()):
            with self.assertRaisesRegex(RuntimeError, "nested"):
                with assembly.add_applet(self.applet()):
                    pass

    def test_pin_already_used(self):
        assembly = self.hardware()
        with assembly.add_applet(self.applet()):
            assembly.add_port("A0", "x")
            with self.assertRaisesRegex(ValueError, "unknown or already used pin A0"):
                assembly.add_port("A0", "y")
            with self.assertRaisesRegex(ValueError, "unknown or already used pin"):
                assembly.add_port("B9", "y")

    def test_sealed(self):
        assembly = self.hardware()
        assembly._artifact = object()
        with assembly.add_applet(self.applet()):
            with self.assertRaisesRegex(AssemblyBuildError, "sealed"):
                assembly.add_port("A0", "x")
            with self.assertRaisesRegex(AssemblyBuildError, "sealed"):
                assembly.add_rw_register(Signal())

    def test_dynamic_memory_limits(self):
        assembly = self.hardware("D0")
        with assembly.add_applet(self.applet()):
            with self.assertRaisesRegex(ValueError, "64 MB"):
                assembly.add_dynamic_memory(DRAMOptions(size=65 * 0x100000))
            assembly.add_dynamic_memory()
            assembly.add_dynamic_memory()
            with self.assertRaisesRegex(AssemblyBuildError, "two memory channels"):
                assembly.add_dynamic_memory()

    def test_follow_sense_on_all_ports(self):
        assembly = self.hardware()
        with assembly.add_applet(self.applet()):
            assembly.set_port_voltage(GlasgowPort.ALL, GlasgowVio(sense="A"))

    def test_pipe_arguments(self):
        for assembly in (self.hardware(), SimulationAssembly()):
            with assembly.add_applet(self.applet()):
                pipe = assembly.add_in_pipe(stream.Signature(8).create())
            with self.assertRaisesRegex(ValueError, "positive"):
                asyncio.run(pipe.recv(0))
            with self.assertRaisesRegex(ValueError, "empty"):
                asyncio.run(pipe.recv_until(b""))

    def test_simulation_pipe_direction(self):
        assembly = SimulationAssembly()
        with assembly.add_applet(self.applet()):
            in_pipe = assembly.add_in_pipe(stream.Signature(8).create())
            out_pipe = assembly.add_out_pipe(stream.Signature(8).flip().create())
        with self.assertRaisesRegex(TypeError, "in pipe"):
            asyncio.run(in_pipe.send(b"x"))
        with self.assertRaisesRegex(TypeError, "out pipe"):
            asyncio.run(out_pipe.recv(1))
