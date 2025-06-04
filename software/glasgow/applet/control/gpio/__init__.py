import re
import argparse
import logging

from amaranth import *
from amaranth.lib import wiring, io, cdc
from amaranth.lib.wiring import In, Out

from glasgow.abstract import AbstractAssembly, PullState
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2, GlasgowPin


__all__ = ["GPIOException", "GPIOComponent", "GPIOInterface"]


class GPIOException(GlasgowAppletError):
    pass


class GPIOComponent(wiring.Component):
    def __init__(self, port):
        self._port = port

        super().__init__({
            "i":  Out(len(port)),
            "o":  In(len(port)),
            "oe": In(len(port)),
        })

    def elaborate(self, platform):
        m = Module()

        for index, (bit, bit_oe, bit_o, bit_i) in \
                enumerate(zip(self._port, self.oe, self.o, self.i)):
            m.submodules[f"buffer_{index}"] = buffer = io.Buffer("io", bit)
            m.submodules[f"i_sync_{index}"] = i_sync = cdc.FFSynchronizer(buffer.i, bit_i)
            m.d.comb += buffer.o.eq(bit_o)
            m.d.comb += buffer.oe.eq(bit_oe)

        return m


class GPIOInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 pins: tuple[GlasgowPin]):
        self._logger   = logger
        self._level    = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._assembly = assembly
        self._pins     = pins

        component = assembly.add_submodule(GPIOComponent(assembly.add_port(pins, name="gpio")))
        self._i   = assembly.add_ro_register(component.i)
        self._o   = assembly.add_rw_register(component.o)
        self._oe  = assembly.add_rw_register(component.oe)

    def _log(self, message: str, *args):
        self._logger.log(self._level, "GPIO: " + message, *args)

    @property
    def count(self):
        return len(self._pins)

    def _check_index(self, index):
        if index not in range(self.count):
            raise IndexError(f"pin {index} out of range [0,{self.count})")

    async def pull(self, index: int, state: PullState | str):
        """Configure pull-up or pull-down for pin ``index``."""
        self._assembly.use_pulls({self._pins[index]: state})
        await self._assembly.configure_ports()

    async def input(self, index: int):
        """Configure pin ``index`` as input."""
        self._check_index(index)
        self._log(f"pin={index} in")
        await self._oe.set((await self._oe) & ~(1 << index))

    async def output(self, index: int, value: bool):
        """Configure pin ``index`` as output, initially driving ``value``."""
        self._check_index(index)
        self._log(f"pin={index} out set={bool(value):b}")
        await self._o.set((await self._o) & ~(1 << index) | (bool(value) << index))
        await self._oe.set((await self._oe) | (1 << index))

    async def get(self, index: int) -> bool:
        """Sample state of pin ``index``."""
        self._check_index(index)
        state = (await self._i >> index) & 1
        self._log(f"pin={index} get={state:b}")
        return bool(state)

    async def set(self, index: int, value: bool):
        """Update value driven by pin ``index`` to be ``value``. If the pin is not currently
        configured as an output, an exception is raised."""
        self._check_index(index)
        self._log(f"pin={index} set={value:b}")
        if not (await self._oe & (1 << index)):
            raise GPIOException(f"pin {index} is not configured as an output")
        await self._o.set((await self._o) & ~(1 << index) | (value << index))

    async def get_all(self) -> int:
        """Sample state of every pin simultaneously. In the returned value, the least significant
        bit corresponds to the first pin in the port provided to the constructor."""
        state = await self._i
        self._log(f"pins get={state:0{self.count}b}")
        return state

    async def set_all(self, value: int):
        """Update value of every pin simultaneously. In ``value``, the least significant bit
        corresponds to the first pin in the port provided to the constructor. The bits
        corresponding to pins that are configured as inputs are ignored."""
        self._log(f"pins set={value:0{self.count}b}")
        await self._o.set(value)


class ControlGPIOApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "control individual I/O pins"
    description = """
    Sample and drive individual I/O pins via the CLI, the REPL, or a script.

    CLI pin actions can be used to configure a pin to be driven strongly (``A0=0`` or ``A0=1``),
    or to be driven weakly using a pull resistor (``A0=H`` or ``A0=L``). The actions are executed
    in the order they are provided on the command line.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "pins", width=range(1, 33), required=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.gpio_iface = GPIOInterface(self.logger, self.assembly, pins=args.pins)

    @classmethod
    def add_run_arguments(cls, parser):
        def pin_action(arg):
            if m := re.match(r"^([A-Z][0-9]+)(?:=([01HL]))?$", arg):
                (pin,), value = GlasgowPin.parse(m[1]), m[2]
                return (pin, value)
            raise argparse.ArgumentTypeError(f"{arg!r} is not a valid pin action")

        parser.add_argument(
            "pin_actions", metavar="PIN-ACTION", nargs="*", type=pin_action,
            help="pins to drive or sample, e.g.: 'A0=1', 'A1=L', 'B5'")

    async def run(self, args):
        for pin, level in args.pin_actions:
            try:
                pin_index = args.pins.index(pin)
            except ValueError:
                raise GlasgowAppletError(f"pin {pin} is not included in the '--pins' argument")

            match level:
                case None:
                    print(f"{pin}={await self.gpio_iface.get(pin_index):b}")
                case '0':
                    await self.gpio_iface.output(pin_index, False)
                case '1':
                    await self.gpio_iface.output(pin_index, True)
                case 'H':
                    await self.gpio_iface.pull(pin_index, PullState.High)
                    await self.gpio_iface.input(pin_index)
                case 'L':
                    await self.gpio_iface.pull(pin_index, PullState.Low)
                    await self.gpio_iface.input(pin_index)
                case _:
                    assert False

    @classmethod
    def tests(cls):
        from . import test
        return test.GPIOAppletTestCase
