import re
from dataclasses import dataclass
from typing import Literal, Self

from amaranth import *
from amaranth.lib import wiring, io, cdc
from amaranth.lib.wiring import In, Out

from glasgow.support import logging
from glasgow.abstract import AbstractAssembly, PullState
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2, GlasgowPin
from glasgow.support.endpoint import ServerEndpoint, endpoint


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
                 pins: tuple[GlasgowPin], name="gpio"):
        self._logger   = logger
        self._level    = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._assembly = assembly
        self._pins     = pins

        port_pins = pins[0] if len(pins) == 1 else pins
        component = assembly.add_submodule(GPIOComponent(assembly.add_port(port_pins, name=name)))
        self._i   = assembly.add_ro_register(component.i)
        self._o   = assembly.add_rw_register(component.o)
        self._oe  = assembly.add_rw_register(component.oe)

    def _log(self, message: str, *args):
        self._logger.log(self._level, "GPIO: " + message, *args)

    @property
    def count(self) -> int:
        """Number of pins."""
        return len(self._pins)

    def _check_index(self, index: int):
        if index not in range(self.count):
            raise IndexError(f"pin {index} out of range [0,{self.count})")

    async def pull(self, index: int, state: PullState | str):
        """Configure pull-up or pull-down for pin :py:`index`."""
        self._assembly.use_pulls({self._pins[index]: state})
        await self._assembly.configure_ports()

    async def input(self, index: int):
        """Configure pin :py:`index` as input.

        Raises
        ------
        IndexError
            If :py:`index` does not specify a valid pin index.
        """
        self._check_index(index)
        self._log(f"pin={index} in")
        await self._oe.set((await self._oe) & ~(1 << index))

    async def output(self, index: int, value: bool):
        """Configure pin :py:`index` as output, initially driving :py:`value`.

        Raises
        ------
        IndexError
            If :py:`index` does not specify a valid pin index.
        """
        self._check_index(index)
        self._log(f"pin={index} out set={bool(value):b}")
        await self._o.set((await self._o) & ~(1 << index) | (bool(value) << index))
        await self._oe.set((await self._oe) | (1 << index))

    async def get(self, index: int) -> bool:
        """Sample state of pin :py:`index`.

        Raises
        ------
        IndexError
            If :py:`index` does not specify a valid pin index.
        """
        self._check_index(index)
        state = (await self._i >> index) & 1
        self._log(f"pin={index} get={state:b}")
        return bool(state)

    async def set(self, index: int, value: bool):
        """Update value driven by pin :py:`index` to be :py:`value`.

        Raises
        ------
        IndexError
            If :py:`index` does not specify a valid pin index.
        GPIOException
            If pin :py:`index` is not configured as an ouptut.
        """
        self._check_index(index)
        self._log(f"pin={index} set={value:b}")
        if not (await self._oe & (1 << index)):
            raise GPIOException(f"pin {index} is not configured as an output")
        await self._o.set((await self._o) & ~(1 << index) | (value << index))

    async def get_all(self) -> int:
        """Sample state of every pin simultaneously.

        In the returned value, the least significant bit corresponds to the first pin in the port
        provided to the constructor.
        """
        state = await self._i
        self._log(f"pins get={state:0{self.count}b}")
        return state

    async def set_all(self, value: int):
        """Update value of every pin simultaneously.

        In :py:`value`, the least significant bit corresponds to the first pin in the port provided
        to the constructor. The bits corresponding to pins that are configured as inputs, as well
        as the bits that do not correspond to any pins, are ignored.
        """
        self._log(f"pins set={value:0{self.count}b}")
        await self._o.set(value)


@dataclass(kw_only=True)
class PinAction:
    pin:   GlasgowPin
    level: Literal["0", "1", "H", "L", "Z"] | None

    @classmethod
    def parse(cls, action: str) -> Self:
        if m := re.match(r"^([A-Z][0-9]+)(?:=([01HLZ]))?$", action):
            pins, level = GlasgowPin.parse(m[1]), m[2]
            return cls(pin=pins[0], level=level)
        else:
            raise ValueError(f"{action!r} is not a valid pin action")

    async def apply(self, gpio_iface: GPIOInterface, *, all_pins: list[GlasgowPin]) -> str | None:
        try:
            pin_index = all_pins.index(self.pin)
        except ValueError:
            raise ValueError(f"pin {self.pin} is not a part of the GPIO interface") from None

        match self.level:
            case None:
                return f"{self.pin}={await gpio_iface.get(pin_index):b}"
            case "0":
                await gpio_iface.output(pin_index, False)
            case "1":
                await gpio_iface.output(pin_index, True)
            case "H":
                await gpio_iface.pull(pin_index, PullState.High)
                await gpio_iface.input(pin_index)
            case "L":
                await gpio_iface.pull(pin_index, PullState.Low)
                await gpio_iface.input(pin_index)
            case "Z":
                await gpio_iface.pull(pin_index, PullState.Float)
                await gpio_iface.input(pin_index)
            case _:
                assert False
        return None


class ControlGPIOApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "control individual I/O pins"
    description = """
    Sample and drive individual I/O pins via the CLI, the REPL, or a script.

    CLI pin actions can be used to configure a pin to be driven strongly (``A0=0`` or ``A0=1``),
    to be driven weakly using a pull resistor (``A0=H`` or ``A0=L``), undriven (``A0=Z``), or
    specified without a value (``A0``) to sample a pin. The actions are executed in the order they
    are provided on the command line.

    Socket pin actions may be used to interface with the applet from an external application.
    Send each action over the socket in the same format as the CLI pin action described above,
    terminating with a ``\\n``. (Spaces are ignored.) When sampling a pin, the value is sent back
    over the socket terminated with a `\\n``, otherwise no response is provided.
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
        parser.add_argument(
            "--socket", type=endpoint,
            help="listen at ENDPOINT, either unix:PATH or tcp:HOST:PORT")
        parser.add_argument(
            "pin_actions", metavar="PIN-ACTION", nargs="*", type=PinAction.parse,
            help="pins to drive or sample, e.g.: 'A0=1', 'A1=L', 'B5'")

    async def run(self, args):
        for action in args.pin_actions:
            if output := await action.apply(self.gpio_iface, all_pins=args.pins):
                print(output)

        if args.socket:
            endpoint = await ServerEndpoint("gpio", self.logger, args.socket)
            while True:
                try:
                    line = await endpoint.recv_until(b"\n")
                    if line := line.decode().replace(" ", ""):
                        action = PinAction.parse(line)
                        if output := await action.apply(self.gpio_iface, all_pins=args.pins):
                            await endpoint.send(output.encode() + b"\n")
                except ValueError as e:
                    self.logger.error(str(e))
                except EOFError:
                    continue

    @classmethod
    def tests(cls):
        from . import test
        return test.GPIOAppletTestCase
