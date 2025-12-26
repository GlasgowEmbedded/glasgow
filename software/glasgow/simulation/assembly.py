from typing import Any
from collections.abc import Generator
from contextlib import contextmanager
import itertools
import logging

from amaranth import *
from amaranth.lib import io
from amaranth.sim import Simulator

from ..abstract import *


__all__ = ["SimulationPipe", "SimulationRegister", "SimulationAssembly"]


logger = logging.getLogger(__name__)


class SimulationPipe(AbstractInOutPipe):
    def __init__(self, parent, *, i_buffer, o_buffer):
        self._parent   = parent
        self._i_buffer = i_buffer
        self._o_buffer = o_buffer

    @property
    def readable(self) -> int | None:
        return len(self._i_buffer)

    async def recv(self, length) -> memoryview:
        assert self._i_buffer is not None, "recv() called on an out pipe"
        while len(self._i_buffer) < length:
            _clk_hit, rst_hit = await self._parent._context.tick()
            assert not rst_hit
        data = self._i_buffer[:length]
        del self._i_buffer[:length]
        return memoryview(data)

    async def recv_until(self, delimiter: bytes) -> bytes:
        assert self._i_buffer is not None, "recv_until() called on an out pipe"
        assert len(delimiter) >= 1
        while delimiter not in self._i_buffer:
            _clk_hit, rst_hit = await self._parent._context.tick()
            assert not rst_hit
        length = self._i_buffer.index(delimiter) + len(delimiter)
        data = self._i_buffer[:length]
        del self._i_buffer[:length]
        return bytes(data)

    @property
    def writable(self) -> int | None:
        return None

    async def send(self, data: bytes | bytearray | memoryview):
        assert self._o_buffer is not None, "send() called on an in pipe"
        self._o_buffer.extend(data)

    async def flush(self, *, _wait=True):
        assert self._o_buffer is not None, "flush() called on an in pipe"
        while len(self._o_buffer) > 0:
            _clk_hit, rst_hit = await self._parent._context.tick()
            assert not rst_hit

    async def reset(self):
        self._i_buffer.clear()
        self._o_buffer.clear()

    async def detach(self) -> tuple[int, int]:
        raise NotImplementedError


class SimulationRORegister(AbstractRORegister):
    def __init__(self, parent, signal):
        self._parent = parent
        self._signal = signal

    async def get(self):
        return self._parent._context.get(self._signal)

    @property
    def shape(self):
        return self._signal.shape()


class SimulationRWRegister(SimulationRORegister, AbstractRWRegister):
    async def set(self, value):
        self._parent._context.set(self._signal, value)


class SimulationPin:
    _logger: logging.Logger
    _name: str
    _pin: GlasgowPin
    _port: io.SimulationPort  | None
    _pull_state: PullState | None

    def __init__(self, logger: logging.Logger, pin: GlasgowPin, name: str):
        self._logger = logger
        self._name = name
        self._pin = pin
        self._port = None
        self._port_taken = False
        self._pull_state = None

    @property
    def name(self) -> str:
        return self._name

    def bind_port(self) -> io.SimulationPort:
        assert self._port is None, "Pin has already been used"
        self._port = io.SimulationPort("io", 1, name=self._name, invert=self.pin.invert)
        return self._port

    @property
    def port(self) -> io.SimulationPort:
        assert self._port is not None, "Pin has not had a port bound to it yet"
        return self._port

    @property
    def pin(self) -> GlasgowPin:
        return self._pin

    @pin.setter
    def pin(self, new_config: GlasgowPin):
        if self._pin != new_config:
            if self._port is not None:
                raise ValueError(
                    f"Attempted to change pin configuration from {self._pin} to {new_config} "
                    "after a port has already been bound to it"
                )
            self._logger.debug(f"Changing pin config from {self._pin} to {new_config}")
        self._pin = new_config

    @property
    def pull_state(self) -> PullState | None:
        return self._pull_state

    @pull_state.setter
    def pull_state(self, new_state: PullState):
        if self._pull_state is None:
            self._logger.debug(f"Setting pull state to {new_state} for {self.name}")
            self._pull_state = new_state
        else:
            self._logger.debug(
                f"Changing pull state from {self._pull_state} to {new_state} for {self.name}"
            )
            self._pull_state = new_state

    @property
    def effective_pull_state(self) -> PullState:
        non_inverted = PullState.Float if self._pull_state is None else self._pull_state
        return ~non_inverted if self._pin.invert else non_inverted

    def __repr__(self) -> str:
        return (
            "SimulationPin("
            f"name={self._name}, pin={self._pin}, port={self._port}, pull_state={self._pull_state}"
            ")"
        )


class SimulationAssembly(AbstractAssembly):
    _pins: dict[str, SimulationPin]

    def __init__(self):
        self._logger    = logger
        self._pins      = {}
        self._modules   = [] # (elaboratable, name)
        self._benches   = [] # (constructor, background)
        self._jumpers   = [] # (pin_name...)
        self.__context  = None

    @property
    def sys_clk_period(self) -> "Period":
        # Reduced from 36 or 48 MHz to 1 MHz to improve test performance.
        return 1/1000000

    @contextmanager
    def add_applet(self, applet: Any) -> Generator[None, None, None]:
        self._logger = applet.logger
        try:
            yield
        finally:
            self._logger = logger

    def add_platform_pin(self, pin: GlasgowPin, port_name: str) -> io.PortLike:
        # TODO: do we want to support use case of multiple buffers attaching to the same pin?
        #       (mustn't output at the same time at different levels)
        pin_name = pin.loc_name

        sim_pin: SimulationPin
        if pin_name in self._pins:
            sim_pin = self._pins[pin_name]
            # Update pin inversion if set differently by e.g. set_pin_pull
            sim_pin.pin = pin
        else:
            sim_pin = SimulationPin(self._logger, pin, pin_name)
            self._pins[pin_name] = sim_pin

        return sim_pin.bind_port()

    def get_pin(self, pin_name: str) -> io.SimulationPort:
        return self._pins[pin_name].port

    def connect_pins(self, *pin_names: str):
        self._jumpers.append(pin_names)

    def add_in_pipe(self, in_stream, *, in_flush=C(0),
                    fifo_depth=None, buffer_size=None) -> AbstractInPipe:
        return self.add_inout_pipe(
            in_stream=in_stream, out_stream=None, in_flush=in_flush,
            in_fifo_depth=fifo_depth, in_buffer_size=buffer_size)

    def add_out_pipe(self, out_stream, *,
                     fifo_depth=None, buffer_size=None) -> AbstractOutPipe:
        return self.add_inout_pipe(
            in_stream=None, out_stream=out_stream,
            out_fifo_depth=fifo_depth, out_buffer_size=buffer_size)

    def add_inout_pipe(self, in_stream, out_stream, *, in_flush=C(0),
                       in_fifo_depth=None, in_buffer_size=None,
                       out_fifo_depth=None, out_buffer_size=None) -> AbstractInOutPipe:
        if in_stream is None:
            i_buffer = None
        else:
            i_buffer = bytearray()
            async def i_testbench(ctx):
                nonlocal i_buffer
                timer = 0
                packet = bytearray()
                ctx.set(in_stream.ready, 1)
                while True:
                    clk_hit, rst_hit, payload_smp, valid_smp, flush_smp = \
                        await ctx.tick().sample(in_stream.payload, in_stream.valid, in_flush)
                    assert not rst_hit
                    if clk_hit:
                        if valid_smp:
                            packet.append(payload_smp)
                            timer = 0
                        if len(packet) >= 512 or flush_smp or timer >= 100:
                            i_buffer += packet
                            packet.clear()
                        elif len(packet) > 0:
                            timer += 1
            self._benches.append((i_testbench, True))

        if out_stream is None:
            o_buffer = None
        else:
            o_buffer = bytearray()
            async def o_testbench(ctx):
                while True:
                    ctx.set(out_stream.valid, len(o_buffer) > 0)
                    if o_buffer:
                        ctx.set(out_stream.payload, o_buffer[0])
                    _clk_hit, _rst_hit, xfer_smp = \
                        await ctx.tick().sample(out_stream.ready & out_stream.valid)
                    if xfer_smp:
                        del o_buffer[0]
            self._benches.append((o_testbench, True))

        return SimulationPipe(self, i_buffer=i_buffer, o_buffer=o_buffer)

    def add_ro_register(self, signal) -> AbstractRORegister:
        return SimulationRORegister(self, signal)

    def add_rw_register(self, signal) -> AbstractRWRegister:
        return SimulationRWRegister(self, signal)

    def add_submodule(self, elaboratable, *, name=None) -> Elaboratable:
        self._modules.append((elaboratable, name))
        return elaboratable

    def add_testbench(self, constructor, *, background=False):
        self._benches.append((constructor, background))

    def set_port_voltage(self, port: GlasgowPort, vio: GlasgowVio):
        pass

    def set_pin_pull(self, pin: GlasgowPin, state: PullState):
        # NOTE: Currently only works with pins connected to each other via a jumper
        #       Implemented below in jumper elaboration
        pin_name = pin.loc_name
        if pin_name not in self._pins:
            self._pins[pin_name] = SimulationPin(self._logger, pin, pin_name)
        self._pins[pin_name].pull_state = state

    async def configure_ports(self):
        if self.__context is not None:
            raise NotImplementedError(
                "Runtime modification of ports has not yet been implemented for simulations"
            )

        pass

    @property
    def _context(self):
        if self.__context is None:
            raise RuntimeError("runtime features can be used only while simulation is running")
        return self.__context

    def run(self, fn, *, vcd_file=None, gtkw_file=None):
        m = Module()

        dummy = Signal()
        m.d.sync += dummy.eq(0) # make sure the domain exists

        for jumper in self._jumpers:
            net = Signal(name=f"jumper_{'_'.join(jumper)}")
            pins = [self._pins[name] for name in jumper]
            pull_state = PullState.Float
            for pin in pins:
                pull_state = pull_state.combine(pin.effective_pull_state)

                m.d.comb += pin.port.i.eq(net)
                with m.If(pin.port.oe):
                    m.d.comb += net.eq(pin.port.o)

            any_zero = Cat((pin.port.o == 0) & pin.port.oe for pin in pins).any()
            any_one = Cat((pin.port.o == 1) & pin.port.oe for pin in pins).any()

            m.d.comb += Assert(
                ~(any_zero & any_one),
                Format(
                    f"electrical contention on a jumper: "
                    f"{' '.join(f'{name}(oe={{}}, o={{}})' for name in jumper)}",
                    *itertools.chain.from_iterable(
                        (self._pins[name].port.oe, self._pins[name].port.o)
                        for name in jumper
                    ),
                ),
            )

            if pull_state != PullState.Float:
                with m.If(Cat(pin.port.oe for pin in pins) == 0):
                    m.d.comb += net.eq(pull_state.to_bit())

        for elaboratable, name in self._modules:
            m.submodules[name] = elaboratable

        sim = Simulator(m)
        sim.add_clock(self.sys_clk_period)

        async def wrap_fn(ctx):
            self.__context = ctx
            await ctx.delay(1e-5)
            await fn(ctx)
        sim.add_testbench(wrap_fn)

        # Add other testbenches second, so that they can depend on the context being available.
        for constructor, background in self._benches:
            sim.add_testbench(constructor, background=background)

        try:
            assert self.__context is None
            if vcd_file:
                with sim.write_vcd(vcd_file, gtkw_file):
                    sim.run()
            else:
                sim.run()
        finally:
            self.__context = None
