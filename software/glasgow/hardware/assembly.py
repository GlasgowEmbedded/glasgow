from typing import Any, Optional, Generator
from collections.abc import Mapping
from collections import defaultdict
from contextlib import contextmanager, asynccontextmanager
import asyncio
import logging

from amaranth import *
from amaranth.hdl import ShapeCastable
from amaranth.lib import wiring, io
from amaranth.build import ResourceError
import usb1

from ..support.logging import dump_hex
from ..support.task_queue import TaskQueue
from ..support.chunked_fifo import ChunkedFIFO
from ..gateware.i2c import I2CTarget
from ..gateware.registers import I2CRegisters
from ..gateware.fx2_crossbar import FX2Crossbar
from ..gateware.stream import StreamFIFO
from ..abstract import *
from .platform import GlasgowPlatformPort
from .platform.rev_ab import GlasgowRevABPlatform
from .platform.rev_c import GlasgowRevC0Platform, GlasgowRevC123Platform
from .toolchain import find_toolchain
from .build_plan import GlasgowBuildPlan
from .device import GlasgowDevice


__all__ = ["HardwareAssembly"]


logger = logging.getLogger(__name__)


# On Linux, the total amount of in-flight USB requests for the entire system is limited
# by usbfs_memory_mb parameter of the module usbcore; it is 16 MB by default. This
# limitation was introduced in commit add1aaeabe6b08ed26381a2a06e505b2f09c3ba5, with
# the following (bullshit) justification:
#
#   While it is generally a good idea to avoid large transfer buffers
#   (because the data has to be bounced to/from a contiguous kernel-space
#   buffer), it's not the kernel's job to enforce such limits.  Programs
#   should be allowed to submit URBs as large as they like; if there isn't
#   sufficient contiguous memory available then the submission will fail
#   with a simple ENOMEM error.
#
#   On the other hand, we would like to prevent programs from submitting a
#   lot of small URBs and using up all the DMA-able kernel memory. [...]
#
# In other words, there is a platform-specific limit for USB I/O size, which is not discoverable
# via libusb, and hitting which does not result in a sensible error returned  from libusb
# (it returns LIBUSB_ERROR_IO even though USBDEVFS_SUBMITURB ioctl correctly returns -ENOMEM),
# so it is not even possible to be optimistic and back off after hitting it.
#
# To deal with this, use requests of at most 1024 EP buffer sizes (512 KiB with the FX2) as
# an arbitrary cutoff, and hope for the best.
_max_packets_per_ep = 1024

# USB has the limitation that all transactions are host-initiated. Therefore, if we do not queue
# reads for the IN endpoints quickly enough, the HC will not even poll the device, and the buffer
# will quickly overflow (provided it is being filled with data). To address this, we issue many
# pipelined reads, to compensate for the non-realtime nature of Python and the host OS.
#
# This, however, has an inherent tradeoff. If we submit small reads (down to a single EP buffer
# size), we get the data back as early as possible, but the CPU load is much higher, and we have
# to submit many more buffers to tolerate the same amount of scheduling latency. If we submit large
# reads, it's much easier to service the device quickly enough, but the maximum latency of reads
# rises.
#
# The relationship between buffer size and latency is quite complex. If only one 512-byte buffer
# is available but a 10240-byte read is requested, the read will finish almost immediately with
# those 512 bytes. On the other hand, if 20 512-byte buffers are available and the HC can read one
# each time it sends an IN token, they will all be read before the read finishes; if we request
# a read of dozens of megabytes, this can take seconds.
#
# To try and balance these effects, we choose a medium buffer size that should work well with most
# applications. It's possible that this will need to become customizable later, but for now
# a single fixed value works.
_packets_per_xfer = 32

# Queue as many transfers as we can, but no more than 16, as the returns beyond that point
# are diminishing.
_xfers_per_queue = min(16, _max_packets_per_ep // _packets_per_xfer)


class HardwareRORegister(AbstractRORegister):
    def __init__(self, logger, parent, address, *, shape=None, name=None):
        self._logger  = logger
        self._parent  = parent
        self._address = address
        self._shape   = shape
        self._name    = name or f"{address:#x}"
        self._width   = (Shape.cast(self._shape).width + 7) // 8

    async def get(self):
        value = await self._parent.device.read_register(self._address, self._width)
        if isinstance(self._shape, ShapeCastable):
            value = self._shape.from_bits(value)
        return value


class HardwareRWRegister(HardwareRORegister, AbstractRWRegister):
    async def set(self, value):
        if isinstance(self._shape, ShapeCastable):
            value = Const.cast(self._shape.const(value)).value
        await self._parent.device.write_register(self._address, value, self._width)


class HardwareInPipe(AbstractInPipe):
    def __init__(self, logger, parent, *, buffer_size=None):
        self._logger            = logger
        self._parent            = parent

        self._in_ep_address     = None # allocated later
        self._in_packet_size    = None

        self._in_buffer_size    = buffer_size
        self._in_pushback       = asyncio.Condition()
        self._in_tasks          = TaskQueue()
        self._in_buffer         = ChunkedFIFO()
        self._in_stalls         = 0

    async def _start(self):
        # Pipeline reads before deasserting reset, so that if the applet immediately starts
        # streaming data, there are no overflows. (This is perhaps not the best way to implement
        # an applet, but we can support it easily enough, and it avoids surprise overflows.)
        self._logger.trace("IN pipe: pipelining")
        for _ in range(_xfers_per_queue):
            self._in_tasks.submit(self._in_task())
        # Give the IN tasks a chance to submit their transfers before deasserting reset.
        await asyncio.sleep(0)

    async def _stop(self):
        self._logger.trace("IN pipe: clearing")
        await self._in_tasks.cancel()
        self._in_buffer.clear()

    async def _in_task(self):
        if self._in_buffer_size is not None:
            async with self._in_pushback:
                while len(self._in_buffer) > self._in_buffer_size:
                    self._logger.trace("IN pipe: read pushback")
                    await self._in_pushback.wait()

        size = self._in_packet_size * _packets_per_xfer
        data = await self._parent.device.bulk_read(self._in_ep_address, size)
        self._in_buffer.write(data)

        self._in_tasks.submit(self._in_task())

    @property
    def readable(self) -> int:
        return len(self._in_buffer)

    async def recv(self, length):
        assert length > 0

        # Return exactly the requested length.
        while len(self._in_buffer) < length:
            self._logger.trace("IN pipe: need %d bytes", length - len(self._in_buffer))
            self._in_stalls += 1
            assert self._in_tasks
            await self._in_tasks.wait_one()

        async with self._in_pushback:
            result = self._in_buffer.read(length)
            self._in_pushback.notify_all()

        if len(result) < length:
            chunks  = [result]
            length -= len(result)
            while length > 0:
                async with self._in_pushback:
                    chunk = self._in_buffer.read(length)
                    self._in_pushback.notify_all()
                chunks.append(chunk)
                length -= len(chunk)
            # Always return a memoryview object, to avoid hard to detect edge cases downstream.
            result = memoryview(b"".join(chunks))

        self._logger.trace("IN pipe: read <%s>", dump_hex(result))
        return result

    def statistics(self):
        self._logger.info("IN pipe statistics:")
        self._logger.info("  total   : %d B",   self._in_buffer.total_read_bytes)
        self._logger.info("  waited  : %.3f s", self._in_tasks.total_wait_time)
        self._logger.info("  stalls  : %d",     self._in_stalls)
        self._logger.info("  wakeups : %d",     self._in_tasks.total_wait_count)


class HardwareOutPipe(AbstractOutPipe):
    def __init__(self, logger, parent, *, buffer_size=None):
        self._logger            = logger
        self._parent            = parent

        self._out_ep_address    = None # allocated later
        self._out_packet_size   = None

        self._out_buffer_size   = buffer_size
        self._out_inflight      = 0
        self._out_tasks         = TaskQueue()
        self._out_buffer        = ChunkedFIFO()
        self._out_stalls        = 0

    async def _start(self):
        pass

    async def _stop(self):
        self._logger.trace("OUT pipe: clearing")
        await self._out_tasks.cancel()
        self._out_buffer.clear()

    def _out_slice(self):
        # Fast path: read as much contiguous data as possible, up to our transfer size.
        size = self._out_packet_size * _packets_per_xfer
        data = self._out_buffer.read(size)

        if len(data) < self._out_packet_size:
            # Slow path: USB is very inefficient with small packets, so if we only got a few
            # bytes from the FIFO, and there is more in it, spend CPU time to aggregate that
            # into a larger transfer, as this is likely to result in overall speedup.
            data = bytearray(data)
            while len(data) < self._out_packet_size and self._out_buffer:
                data += self._out_buffer.read(self._out_packet_size - len(data))

        self._out_inflight += len(data)
        return data

    @property
    def _out_threshold(self):
        out_xfer_size = self._out_packet_size * _packets_per_xfer
        if self._out_buffer_size is None:
            return out_xfer_size
        else:
            return min(self._out_buffer_size, out_xfer_size)

    async def _out_task(self, data):
        assert len(data) > 0

        try:
            await self._parent.device.bulk_write(self._out_ep_address, data)
        finally:
            self._out_inflight -= len(data)

        # See the comment in `write` below for an explanation of the following code.
        if len(self._out_buffer) >= self._out_threshold:
            self._out_tasks.submit(self._out_task(self._out_slice()))

    @property
    def writable(self) -> Optional[int]:
        if self._out_buffer_size is None:
            return None
        return self._out_buffer_size - self._out_inflight

    async def send(self, data):
        if self._out_buffer_size is not None:
            # If write buffer is bounded, and we have more inflight requests than the configured
            # write buffer size, then wait until the inflight requests arrive before continuing.
            if self._out_inflight >= self._out_buffer_size:
                self._out_stalls += 1
            while self._out_inflight >= self._out_buffer_size:
                self._logger.trace("OUT pipe: write pushback")
                await self._out_tasks.wait_one()

        # Eagerly check if any of our previous queued writes errored out.
        await self._out_tasks.poll()

        self._logger.trace("OUT pipe: write <%s>", dump_hex(data))
        self._out_buffer.write(data)

        # The write scheduling algorithm attempts to satisfy several partially conflicting goals:
        #  * We want to schedule writes as early as possible, because this reduces buffer bloat and
        #    can dramatically improve responsiveness of the system.
        #  * We want to schedule writes that are as large as possible, up to _packets_per_xfer,
        #    because this reduces CPU utilization and improves latency.
        #  * We never want to automatically schedule writes smaller than _out_packet_size,
        #    because they occupy a whole microframe anyway.
        #
        # We use an approach that performs well when fed with a steady sequence of very large
        # FIFO chunks, yet scales down to packet-size and byte-size FIFO chunks as well.
        #  * We only submit a write automatically once the buffer level crosses the threshold of
        #    `_out_packet_size * _packets_per_xfer`. In this case, _slice_packet always returns
        #    `_out_packet_size * n` bytes, where n is between 1 and _packet_per_xfer.
        #  * We submit enough writes that there is at least one write for each transfer worth
        #    of data in the buffer, up to _xfers_per_queue outstanding writes.
        #  * We submit another write once one finishes, if the buffer level is still above
        #    the threshold, even if no more explicit write calls are performed.
        #
        # This provides predictable write behavior; only _packets_per_xfer packet writes are
        # automatically submitted, and only the minimum necessary number of tasks are scheduled on
        # calls to `write`.
        while len(self._out_tasks) < _xfers_per_queue and \
                    len(self._out_buffer) >= self._out_threshold:
            self._out_tasks.submit(self._out_task(self._out_slice()))

    # TODO: we should not in principle need `_wait=False` as flushes of large batches of data
    # should happen automatically as data is sent
    async def flush(self, *, _wait=True):
        self._logger.trace("OUT pipe: flush")

        # First, we ensure we can submit one more task. (There can be more tasks than
        # _xfers_per_queue because a task may spawn another one just before it terminates.)
        if len(self._out_tasks) >= _xfers_per_queue:
            self._out_stalls += 1
        while len(self._out_tasks) >= _xfers_per_queue:
            await self._out_tasks.wait_one()

        # At this point, the buffer can contain at most _packets_per_xfer packets worth
        # of data, as anything beyond that crosses the threshold of automatic submission.
        # So, we can simply submit the rest of data, which by definition fits into a single
        # transfer.
        assert len(self._out_buffer) <= self._out_packet_size * _packets_per_xfer
        if self._out_buffer:
            data = bytearray()
            while self._out_buffer:
                data += self._out_buffer.read()
            self._out_inflight += len(data)
            self._out_tasks.submit(self._out_task(data))

        if _wait:
            self._logger.trace("OUT pipe: wait for flush")
            if self._out_tasks:
                self._out_stalls += 1
            while self._out_tasks:
                await self._out_tasks.wait_all()

    def statistics(self):
        self._logger.info("OUT pipe statistics:")
        self._logger.info("  total   : %d B",   self._out_buffer.total_written_bytes)
        self._logger.info("  waited  : %.3f s", self._out_tasks.total_wait_time)
        self._logger.info("  stalls  : %d",     self._out_stalls)
        self._logger.info("  wakeups : %d",     self._out_tasks.total_wait_count)


class HardwareInOutPipe(HardwareInPipe, HardwareOutPipe, AbstractInOutPipe):
    def __init__(self, logger, parent, *, in_buffer_size, out_buffer_size):
        HardwareInPipe.__init__(self, logger, parent, buffer_size=in_buffer_size)
        HardwareOutPipe.__init__(self, logger, parent, buffer_size=out_buffer_size)

    def statistics(self):
        HardwareInPipe.statistics(self)
        HardwareOutPipe.statistics(self)


class HardwareAssembly(AbstractAssembly):
    _HEALTH_CHECK_ADDR = 0x00
    _GLOBAL_RESET_ADDR = 0x01

    @staticmethod
    def _create_platform(revision: str):
        match revision:
            case "A0" | "B0":
                return GlasgowRevABPlatform()
            case "C0":
                return GlasgowRevC0Platform()
            case "C1" | "C2" | "C3":
                return GlasgowRevC123Platform()
            case _:
                assert False, f"invalid revision {revision}"

    def __init__(self, *,
            device: Optional[GlasgowDevice] = None,
            revision: Optional[str] = None):
        if device is not None:
            assert revision is None or revision == device.revision
            self._device    = device
            self._revision  = device.revision
        elif revision is not None:
            self._device    = None
            self._revision  = revision
        else:
            self._device    = GlasgowDevice()
            self._revision  = self._device.revision

        self._platform      = self._create_platform(self._revision)
        self._modules       = [] # (elaboratable, name)
        self._registers     = [] # (register, signal)
        self._in_streams    = [] # (in_stream, in_flush, fifo_depth)
        self._out_streams   = [] # (out_stream, fifo_depth)
        self._pipes         = [] # in_pipe|out_pipe|inout_pipe
        self._voltages      = {} # {port: vio}
        self._pulls         = {} # {(port, number): state}

        self._scope         = None
        self._scope_logger  = None

        self._artifact      = None
        self._running       = False

    @property
    def sys_clk_period(self) -> float:
        match self._revision:
            case "A0" | "B0":
                return 1/36e6
            case "C0" | "C1" | "C2" | "C3":
                return 1/48e6

    @contextmanager
    def add_applet(self, applet: Any) -> Generator[None, None, None]:
        assert self._scope is None

        self._scope, self._scope_logger = applet, applet.logger
        try:
            yield
        finally:
            self._scope = self._scope_logger = None

    def add_submodule(self, elaboratable, *, name=None) -> Elaboratable:
        assert self._artifact is None, "cannot add a submodule to a sealed assembly"
        self._modules.append((elaboratable, name))
        elaboratable._MustUse__used = True
        return elaboratable

    def add_platform_pin(self, pin_name: str, port_name: str) -> io.PortLike:
        assert self._artifact is None, "cannot add a port to a sealed assembly"
        # TODO: make this a proper error and not an assertion
        assert pin_name in self._platform.glasgow_pins, f"unknown or already used pin {pin_name}"
        (self._scope_logger or logger).debug(f"assigning pin {port_name!r} to {pin_name}")
        return self._platform.glasgow_pins.pop(pin_name)

    def add_ro_register(self, signal) -> AbstractRORegister:
        assert self._artifact is None, "cannot add a register to a sealed assembly"
        register = HardwareRORegister(self._scope_logger or logger, self,
            address=2 + len(self._registers), shape=signal.shape(), name=signal.name)
        self._registers.append((register, signal))
        return register

    def add_rw_register(self, signal) -> AbstractRWRegister:
        assert self._artifact is None, "cannot add a register to a sealed assembly"
        register = HardwareRWRegister(self._scope_logger or logger, self,
            address=2 + len(self._registers), shape=signal.shape(), name=signal.name)
        self._registers.append((register, signal))
        return register

    def add_in_pipe(self, in_stream, *, in_flush=C(1),
                    fifo_depth=None, buffer_size=None) -> AbstractInPipe:
        assert self._artifact is None, "cannot add a pipe to a sealed assembly"
        in_pipe = HardwareInPipe(self._scope_logger or logger, self, buffer_size=buffer_size)
        self._in_streams.append((in_stream, in_flush, fifo_depth))
        self._pipes.append(in_pipe)
        return in_pipe

    def add_out_pipe(self, out_stream, *,
                     fifo_depth=None, buffer_size=None) -> AbstractOutPipe:
        assert self._artifact is None, "cannot add a pipe to a sealed assembly"
        out_pipe = HardwareOutPipe(self._scope_logger or logger, self, buffer_size=buffer_size)
        self._out_streams.append((out_stream, fifo_depth))
        self._pipes.append(out_pipe)
        return out_pipe

    def add_inout_pipe(self, in_stream, out_stream, *, in_flush=C(1),
                       in_fifo_depth=None, in_buffer_size=None,
                       out_fifo_depth=None, out_buffer_size=None) -> AbstractInOutPipe:
        assert self._artifact is None, "cannot add a pipe to a sealed assembly"
        inout_pipe = HardwareInOutPipe(self._scope_logger or logger, self,
            in_buffer_size=in_buffer_size, out_buffer_size=out_buffer_size)
        self._in_streams.append((in_stream, in_flush, in_fifo_depth))
        self._out_streams.append((out_stream, out_fifo_depth))
        self._pipes.append(inout_pipe)
        return inout_pipe

    def use_voltage(self, ports: Mapping[GlasgowPort, GlasgowVio | float]):
        for port, vio in ports.items():
            port = GlasgowPort(port)
            if isinstance(vio, float):
                vio = GlasgowVio(vio)
            (self._scope_logger or logger).debug("setting port %s voltage to %s V", port, vio)
            self._voltages[port] = vio

    def use_pulls(self, pulls: Mapping[GlasgowPin | tuple[GlasgowPin] | str, PullState | str]):
        for pins, state in pulls.items():
            match pins:
                case str():
                    pins = GlasgowPin.parse(pins)
                case GlasgowPin():
                    pins = [pins]
            match state:
                case str():
                    state = PullState(state)
            for pin in pins:
                if pin.invert:
                    state = ~state
                if state.enabled():
                    (self._scope_logger or logger).debug("pulling pin %s%s %s%s",
                        pin.port, pin.number, state, " (inverted)" if pin.invert else "")
                self._pulls[pin.port, pin.number] = state

    def artifact(self):
        if self._artifact is not None:
            return self._artifact

        m = Module()

        i2c_pins = self._platform.request("i2c", dir={"scl": "-", "sda": "-"})
        fx2_pins = self._platform.request("fx2", dir={
            "sloe": "-", "slrd": "-", "slwr": "-", "pktend": "-", "fifoadr": "-",
            "flag": "-", "fd": "-"
        })

        m.submodules.i2c_target = i2c_target = I2CTarget(i2c_pins)
        m.submodules.i2c_registers = i2c_registers = I2CRegisters(i2c_target)
        m.d.comb += i2c_target.address.eq(0b0001000)

        # always add a register at address 0x00, to be able to check that the FPGA configuration
        # succeeded and that I2C communication works; some 1b2 production devices fail this check
        health_check_addr = i2c_registers.add_existing_ro(C(0xa5))
        assert health_check_addr == self._HEALTH_CHECK_ADDR

        # always add a global reset register at address 0x01; eventually this might be replaced
        # with per-pipe resets
        global_reset, global_reset_addr = i2c_registers.add_rw(1)
        assert global_reset_addr == self._GLOBAL_RESET_ADDR

        for register, signal in self._registers:
            if isinstance(register, HardwareRWRegister):
                register_addr = i2c_registers.add_existing_rw(Value.cast(signal))
            elif isinstance(register, HardwareRORegister):
                register_addr = i2c_registers.add_existing_ro(Value.cast(signal))
            assert register_addr == register._address

        m.submodules.fx2_crossbar = fx2_crossbar = FX2Crossbar(fx2_pins)

        for idx, (in_ep, (in_stream, in_flush, depth)) in \
                enumerate(zip(fx2_crossbar.in_eps, self._in_streams)):
            m.submodules[f"in_fifo_{idx}"] = in_fifo = ResetInserter(in_ep.reset)(
                StreamFIFO(shape=8, depth=self.DEFAULT_FIFO_DEPTH if depth is None else depth))
            wiring.connect(m, in_fifo.w, in_stream)
            wiring.connect(m, in_ep.data, in_fifo.r)
            m.d.comb += in_ep.flush.eq(in_flush)
            m.d.comb += in_ep.reset.eq(global_reset)

        for idx, (out_ep, (out_stream, depth)) in \
                enumerate(zip(fx2_crossbar.out_eps, self._out_streams)):
            m.submodules[f"out_fifo_{idx}"] = out_fifo = ResetInserter(out_ep.reset)(
                StreamFIFO(shape=8, depth=self.DEFAULT_FIFO_DEPTH if depth is None else depth))
            wiring.connect(m, out_fifo.w, out_ep.data)
            wiring.connect(m, out_stream, out_fifo.r)
            m.d.comb += out_ep.reset.eq(global_reset)

        for elaboratable, name in self._modules:
            m.submodules[name] = ResetInserter(global_reset)(elaboratable)

        # /!\ IMPORTANT /!\
        # tie off output enables of unused pins to zero, or they will strongly drive high
        for idx, unused_pins in enumerate(self._platform.glasgow_pins.values()):
            m.submodules[f"unused_pin_{idx}"] = io.Buffer("io", unused_pins)

        try:
            # See note in `rev_c.py`.
            unused_balls = self._platform.request("unused", dir="-")
            m.submodules["unused_balls"] = io.Buffer("io", unused_balls)
        except ResourceError:
            pass

        self._artifact = GlasgowBuildPlan(self._platform.prepare(m,
            # always emit complete build log to stdout; whether it's displayed is controlled by
            # the usual logging options, e.g. `-vv` or `-v -F build`
            verbose=True,
            # don't invalidate cache if all that's changed is the location of a Signal; nobody
            # really looks at the RTLIL src attributes anyway
            emit_src=False,
            # latest yosys and nextpnr versions default to this configuration, but we support some
            # older ones in case yowasp isn't available and this keeps the configuration consistent
            synth_opts="-abc9",
            nextpnr_opts="--placer heap",
        ), find_toolchain())
        return self._artifact

    @property
    def device(self):
        if not self._running:
            raise Exception("runtime features may be used only while a bitstream is loaded")
        return self._device

    async def configure_ports(self):
        for port, vio in self._voltages.items():
            if vio.sense is not None:
                sensed = await self.device.mirror_voltage(port, vio.sense)
                logger.info(
                    "port %s voltage set to %.1f V (sensed on port %s)", port, sensed, vio.sense)
            if vio.value is not None:
                await self.device.set_voltage(port, vio.value)
                logger.info("port %s voltage set to %.1f V", port, vio.value)

        port_pulls = defaultdict(lambda: (set(), set()))
        for (port, number), state in self._pulls.items():
            low, high = port_pulls[port]
            match state:
                case PullState.Low:  low .add(number)
                case PullState.High: high.add(number)
        for port, (low, high) in port_pulls.items():
            voltage = await self.device.get_voltage(str(port))
            if voltage == 0.0:
                logger.error("cannot configure pulls for port %s: Vio is off", port)
                continue
            await self.device.set_pulls(str(port), low, high)

    @property
    def _iface_count(self):
        # TODO: this isn't really accurate, but requires rework of the firmware to fix
        return max(len(self._in_streams), len(self._out_streams))

    async def __aenter__(self):
        return await self.start()

    async def start(self, device=None, *, reload_bitstream=False, _bitstream_file=None):
        assert not self._running, "only a stopped assembly can be started"

        if self._device is None:
            self._device = device
        elif device is not None:
            assert self._device == device
        if self._device is None:
            raise Exception("no device provided")

        for config in self._device.usb_handle.getDevice().iterConfigurations():
            if config.getNumInterfaces() >= self._iface_count:
                try:
                    # Neither WinUSB, nor libusbK, nor libusb0 allow selecting any configuration
                    # that is not the 1st one. This is a limitation of the KMDF USB target.
                    self._device.usb_handle.setConfiguration(config.getConfigurationValue())
                    break
                # Some libusb versions report InvalidParam and some NotSupported.
                except (usb1.USBErrorInvalidParam, usb1.USBErrorNotSupported):
                    pass
        else:
            assert False, "cannot find a suitable interface"

        active_config = self._device.usb_handle.getConfiguration()
        for config in self._device.usb_handle.getDevice().iterConfigurations():
            if config.getConfigurationValue() == active_config:
                break

        # TODO: the assignment of endpoints to interfaces needs to be reworked, here and
        # in the firmware, to reflect the more flexible allocation of pipes we have nowadays
        in_pipe_iter = iter([pipe for pipe in self._pipes if isinstance(pipe, HardwareInPipe)])
        out_pipe_iter = iter([pipe for pipe in self._pipes if isinstance(pipe, HardwareOutPipe)])
        for interface in config.iterInterfaces():
            settings = list(interface.iterSettings())
            active_setting = settings[1] # alt-setting 1 has the actual endpoints
            for endpoint in active_setting.iterEndpoints():
                ep_address = endpoint.getAddress()
                packet_size = endpoint.getMaxPacketSize()
                try:
                    if ep_address & usb1.ENDPOINT_DIR_MASK == usb1.ENDPOINT_IN:
                        next_in_pipe = next(in_pipe_iter)
                        next_in_pipe._in_ep_address = ep_address
                        next_in_pipe._in_packet_size = packet_size
                    if ep_address & usb1.ENDPOINT_DIR_MASK == usb1.ENDPOINT_OUT:
                        next_out_pipe = next(out_pipe_iter)
                        next_out_pipe._out_ep_address = ep_address
                        next_out_pipe._out_packet_size = packet_size
                except StopIteration:
                    pass
        assert len(list(in_pipe_iter)) == 0 and len(list(out_pipe_iter)) == 0

        for index in range(self._iface_count):
            self._device.usb_handle.claimInterface(index)

        if _bitstream_file is not None:
            await self._device.download_prebuilt(self.artifact(), _bitstream_file)
        else:
            await self._device.download_target(self.artifact(), reload=reload_bitstream)

        self._running = True # can access `self.device` after this point
        await self.configure_ports()
        await self.reset_pipes()

    async def reset_pipes(self):
        logger.trace("asserting reset")
        await self.device.write_register(self._GLOBAL_RESET_ADDR, 1)

        logger.trace("clearing hardware buffers")
        for index in range(self._iface_count):
            self.device.usb_handle.setInterfaceAltSetting(index, 1)

        for pipe in self._pipes:
            await pipe._stop()
            await pipe._start()

        logger.trace("deasserting reset")
        await self.device.write_register(self._GLOBAL_RESET_ADDR, 0)

    async def flush_pipes(self):
        for pipe in self._pipes:
            if isinstance(pipe, HardwareOutPipe):
                await pipe.flush()

    async def stop(self):
        for pipe in self._pipes:
            await pipe._stop()

        for index in range(self._iface_count):
            self.device.usb_handle.releaseInterface(index)

        self._running = False

    async def __aexit__(self, exc_type, exc_value, traceback):
        if exc_type is None:
            await self.flush_pipes()
        await self.stop()

    def statistics(self):
        for pipe in self._pipes:
            pipe.statistics()
