from abc import ABCMeta, abstractmethod
import asyncio

import usb1
from amaranth import *
from amaranth import Module, ResetInserter, Signal
from amaranth.lib import wiring, stream, io

from .support.chunked_fifo import ChunkedFIFO
from .support.logging import dump_hex
from .support.task_queue import TaskQueue
from .gateware.stream import StreamFIFO
from .gateware.ports import PortGroup
from .hardware.platform import GlasgowPlatformPort


__all__ = [
    "DeprecatedTarget", "DeprecatedMultiplexer",
    "DeprecatedDevice", "DeprecatedDemultiplexer"
]


class DeprecatedTarget:
    def __init__(self, assembly):
        self.assembly     = assembly
        self._registers   = DeprecatedRegisters(self.assembly)
        self._multiplexer = DeprecatedMultiplexer(self.assembly)

    @property
    def platform(self):
        return self.assembly._platform

    @property
    def sys_clk_freq(self):
        return 1 / self.assembly.sys_clk_period

    def add_submodule(self, elaboratable):
        self.assembly.add_submodule(elaboratable)

    @property
    def registers(self):
        return self._registers

    @property
    def multiplexer(self):
        return self._multiplexer

    def build_plan(self):
        return self.assembly.artifact()


class DeprecatedRegisters:
    def __init__(self, assembly):
        self.assembly   = assembly
        self._registers = {}

    def add_ro(self, *args, src_loc_at=0, **kwargs):
        signal = Signal(*args, src_loc_at=1 + src_loc_at, **kwargs)
        register = self.assembly.add_ro_register(signal)
        return signal, register

    def add_rw(self, *args, src_loc_at=0, **kwargs):
        signal = Signal(*args, src_loc_at=1 + src_loc_at, **kwargs)
        register = self.assembly.add_rw_register(signal)
        return signal, register


class DeprecatedFIFOReadPort:
    def __init__(self, stream):
        self.stream = stream
        self.r_data = stream.payload
        self.r_rdy  = stream.valid
        self.r_en   = stream.ready


class DeprecatedFIFOWritePort:
    def __init__(self, stream, auto_flush):
        self.stream = stream
        self.w_data = stream.payload
        self.w_en   = stream.valid
        self.w_rdy  = stream.ready
        self.flush  = Signal(init=auto_flush)


class DeprecatedMultiplexer:
    def __init__(self, assembly):
        self.assembly    = assembly
        self._interfaces = []

    @property
    def pipe_count(self):
        return self.assembly._iface_count

    def claim_interface(self, applet, args):
        pins = []
        for port in "AB":
            pins += [f"{port}{number}" for number in range(8)]

        interface = DeprecatedMultiplexerInterface(
            applet, self.assembly, pins, len(self._interfaces))
        self._interfaces.append(interface)
        return interface


class DeprecatedMultiplexerInterface:
    def __init__(self, applet, assembly, pins, pipe_num):
        self.applet    = applet
        self.logger    = applet.logger
        self.assembly  = assembly
        self._pins     = pins
        self._pipe_num = pipe_num
        self._in_pipe  = None
        self._out_pipe = None

    def add_subtarget(self, subtarget):
        return self.assembly.add_submodule(subtarget)

    def get_port(self, pins, *, name=None):
        return self.assembly.add_port(pins, name=name)

    def get_port_group(self, **kwargs):
        return self.assembly.add_port_group(**kwargs)

    def get_in_fifo(self, depth=512, *, auto_flush=True):
        assert self._in_pipe is None
        in_stream = stream.Signature(8).flip().create()
        in_port = DeprecatedFIFOWritePort(in_stream, auto_flush)
        self._in_pipe = self.assembly.add_in_pipe(
            wiring.flipped(in_stream), in_flush=in_port.flush, fifo_depth=depth)
        return in_port

    def get_out_fifo(self, depth=512):
        assert self._out_pipe is None
        out_stream = stream.Signature(8).create()
        out_port = DeprecatedFIFOReadPort(out_stream)
        self._out_pipe = self.assembly.add_out_pipe(
            wiring.flipped(out_stream), fifo_depth=depth)
        return out_port


class DeprecatedDevice:
    def __init__(self, target):
        self.assembly = target.assembly
        self._target  = target

    async def read_register(self, register, width=1):
        return await register

    async def write_register(self, register, value, width=1):
        await register.set(value)

    def __getattr__(self, name):
        return getattr(self.assembly._device, name)


class DeprecatedDemultiplexer:
    def __init__(self, device, pipe_count):
        self.device      = device
        self._pipe_count = pipe_count
        self._claimed    = set()
        self._interfaces = []

    async def claim_interface(self, applet, mux_interface, args, pull_low=set(), pull_high=set(),
                              **kwargs):
        assert mux_interface._pipe_num not in self._claimed
        self._claimed.add(mux_interface._pipe_num)

        iface = DeprecatedDemultiplexerInterface(self.device, applet, mux_interface, **kwargs)
        self._interfaces.append(iface)

        for port, vio in getattr(args, "voltage", {}).items():
            if vio.sense is not None:
                voltage = await self.device.mirror_voltage(port, vio.sense)
                applet.logger.info("port %s voltage set to %.1f V (sensed on port %s)",
                    port, voltage, vio.sense)
            if vio.value is not None:
                await self.device.set_voltage(port, vio.value)
                applet.logger.info("port %s voltage set to %.1f V",
                    port, vio.value)

        device_pull_low  = set()
        device_pull_high = set()
        for pin_arg in pull_low:
            (device_pull_high if pin_arg.invert else device_pull_low).add(pin_arg._legacy_number)
        for pin_arg in pull_high:
            (device_pull_low if pin_arg.invert else device_pull_high).add(pin_arg._legacy_number)

        if not hasattr(self.device, "has_pulls"): # simulation device
            pass

        elif self.device.has_pulls:
            if self.device.revision == "C0":
                if pull_low or pull_high:
                    applet.logger.error(
                        "Glasgow revC0 has severe restrictions on use of configurable "
                        "pull resistors; device may require power cycling")
                    await self.device.set_pulls("AB", device_pull_low, device_pull_high)
                else:
                    # Don't touch the pulls; they're either in the power-on reset high-Z state, or
                    # they have been touched by the user, and we've warned about that above.
                    pass

            else:
                await self.device.set_pulls("AB", device_pull_low, device_pull_high)
                device_pull_desc = []
                if device_pull_high:
                    device_pull_desc.append(f"pull-up on {', '.join(map(str, device_pull_high))}")
                if device_pull_low:
                    device_pull_desc.append(f"pull-down on {', '.join(map(str, device_pull_low))}")
                if not device_pull_desc:
                    device_pull_desc.append("disabled")
                applet.logger.debug("port(s) %s pull resistors: %s",
                                    ", ".join(sorted("AB")),
                                    "; ".join(device_pull_desc))

        elif device_pull_low or device_pull_high:
            # Some applets request pull resistors for bidirectional pins (e.g. I2C). Such applets
            # cannot work on revA/B because of the level shifters and the applet should require
            # an appropriate revision.
            # Some applets, though, request pull resistors for unidirectional, DUT-controlled pins
            # (e.g. NAND flash). Such applets can still work on revA/B with appropriate external
            # pull resistors, so we spend some additional effort to allow for that.
            if device_pull_low:
                applet.logger.warning("port(s) %s requires external pull-down resistors on pins %s",
                                      ", ".join(sorted("AB")),
                                      ", ".join(map(str, device_pull_low)))
            if device_pull_high:
                applet.logger.warning("port(s) %s requires external pull-up resistors on pins %s",
                                      ", ".join(sorted("AB")),
                                      ", ".join(map(str, device_pull_high)))

        return iface

    async def flush(self):
        for iface in self._interfaces:
            await iface.flush()

    def statistics(self):
        self.device.assembly.statistics()


class DeprecatedDemultiplexerInterface:
    def __init__(self, device, applet, mux_interface,
                 read_buffer_size=None, write_buffer_size=None):
        self.device = device
        self.applet = applet
        self.logger = applet.logger

        self._mux_interface = mux_interface
        if self._mux_interface._in_pipe is not None:
            self._mux_interface._in_pipe._in_buffer_size   = read_buffer_size
        if self._mux_interface._out_pipe is not None:
            self._mux_interface._out_pipe._out_buffer_size = write_buffer_size

    async def reset(self):
        if self._mux_interface._in_pipe is not None:
            await self._mux_interface._in_pipe._stop()
        if self._mux_interface._out_pipe is not None:
            await self._mux_interface._out_pipe._stop()
        if self._mux_interface._in_pipe is not None:
            await self._mux_interface._in_pipe._start()
        if self._mux_interface._out_pipe is not None:
            await self._mux_interface._out_pipe._start()

    async def read(self, length=None, *, flush=True):
        if flush:
            if self._mux_interface._out_pipe is not None:
                await self._mux_interface._out_pipe.flush()
        if length == 0:
            return memoryview(b"")
        if length is None:
            length = self._mux_interface._in_pipe.readable or 1
        return await self._mux_interface._in_pipe.recv(length)

    async def write(self, data):
        await self._mux_interface._out_pipe.send(data)

    async def flush(self, wait=True):
        await self._mux_interface._out_pipe.flush(_wait=wait)
