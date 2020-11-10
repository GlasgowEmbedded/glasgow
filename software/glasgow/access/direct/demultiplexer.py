import math
import usb1
import asyncio

from ...support.logging import *
from ...support.chunked_fifo import *
from ...support.task_queue import *
from .. import AccessDemultiplexer, AccessDemultiplexerInterface


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


class DirectDemultiplexer(AccessDemultiplexer):
    def __init__(self, device, pipe_count):
        super().__init__(device)
        self._claimed = set()

        for config in device.usb_handle.getDevice().iterConfigurations():
            if config.getNumInterfaces() == pipe_count:
                try:
                    device.usb_handle.setConfiguration(config.getConfigurationValue())
                except usb1.USBErrorInvalidParam:
                    # Neither WinUSB, nor libusbK, nor libusb0 allow selecting any configuration
                    # that is not the 1st one. This is a limitation of the KMDF USB target.
                    pass
                break
        else:
            assert False

    async def claim_interface(self, applet, mux_interface, args, pull_low=set(), pull_high=set(),
                              **kwargs):
        assert mux_interface._pipe_num not in self._claimed
        self._claimed.add(mux_interface._pipe_num)

        iface = DirectDemultiplexerInterface(self.device, applet, mux_interface, **kwargs)
        self._interfaces.append(iface)

        if hasattr(args, "mirror_voltage") and args.mirror_voltage:
            for port in args.port_spec:
                await self.device.mirror_voltage(port)
                applet.logger.info("port %s voltage set to %.1f V",
                                   port, await self.device.get_voltage(port))
        elif hasattr(args, "voltage") and args.voltage is not None:
            await self.device.set_voltage(args.port_spec, args.voltage)
            applet.logger.info("port(s) %s voltage set to %.1f V",
                               ", ".join(sorted(args.port_spec)), args.voltage)
        elif hasattr(args, "keep_voltage") and args.keep_voltage:
            applet.logger.info("port voltage unchanged")

        if self.device.has_pulls:
            if self.device.revision == "C0":
                if pull_low or pull_high:
                    applet.logger.error("Glasgow revC0 has severe restrictions on use of configurable "
                                        "pull resistors; device may require power cycling")
                    await self.device.set_pulls(args.port_spec, pull_low, pull_high)
                else:
                    # Don't touch the pulls; they're either in the power-on reset high-Z state, or
                    # they have been touched by the user, and we've warned about that above.
                    pass

            elif hasattr(args, "port_spec"):
                await self.device.set_pulls(args.port_spec, pull_low, pull_high)
                if pull_low or pull_high:
                    applet.logger.info("port(s) %s pull resistors configured",
                                       ", ".join(sorted(args.port_spec)))
                else:
                    applet.logger.debug("port(s) %s pull resistors disabled",
                                        ", ".join(sorted(args.port_spec)))

        elif pull_low or pull_high:
            # Some applets request pull resistors for bidirectional pins (e.g. I2C). Such applets
            # cannot work on revA/B because of the level shifters and the applet should require
            # an appropriate revision.
            # Some applets, though, request pull resistors for unidirectional, DUT-controlled pins
            # (e.g. NAND flash). Such applets can still work on revA/B with appropriate external
            # pull resistors, so we spend some additional effort to allow for that.
            if pull_low:
                applet.logger.warn("port(s) %s requires external pull-down resistors on pins %s",
                                   ", ".join(sorted(args.port_spec)),
                                   ", ".join(map(str, pull_low)))
            if pull_high:
                applet.logger.warn("port(s) %s requires external pull-up resistors on pins %s",
                                   ", ".join(sorted(args.port_spec)),
                                   ", ".join(map(str, pull_high)))

        await iface.reset()
        return iface


class DirectDemultiplexerInterface(AccessDemultiplexerInterface):
    def __init__(self, device, applet, mux_interface,
                 read_buffer_size=None, write_buffer_size=None):
        super().__init__(device, applet)

        self._write_buffer_size = write_buffer_size
        self._read_buffer_size  = read_buffer_size
        self._in_pushback  = asyncio.Condition()
        self._out_inflight = 0

        self._pipe_num   = mux_interface._pipe_num
        self._addr_reset = mux_interface._addr_reset

        config_num = self.device.usb_handle.getConfiguration()
        for config in self.device.usb_handle.getDevice().iterConfigurations():
            if config.getConfigurationValue() == config_num:
                break

        interfaces = list(config.iterInterfaces())
        assert self._pipe_num < len(interfaces)
        interface = interfaces[self._pipe_num]

        settings = list(interface.iterSettings())
        setting = settings[1] # alt-setting 1 has the actual endpoints
        for endpoint in setting.iterEndpoints():
            address = endpoint.getAddress()
            packet_size = endpoint.getMaxPacketSize()
            if address & usb1.ENDPOINT_DIR_MASK == usb1.ENDPOINT_IN:
                self._endpoint_in = address
                self._in_packet_size = packet_size
            if address & usb1.ENDPOINT_DIR_MASK == usb1.ENDPOINT_OUT:
                self._endpoint_out = address
                self._out_packet_size = packet_size
        assert self._endpoint_in != None and self._endpoint_out != None

        self._interface  = self.device.usb_handle.claimInterface(self._pipe_num)
        self._in_tasks   = TaskQueue()
        self._in_buffer  = ChunkedFIFO()
        self._out_tasks  = TaskQueue()
        self._out_buffer = ChunkedFIFO()

        self._in_stalls  = 0
        self._out_stalls = 0

    async def cancel(self):
        if self._in_tasks or self._out_tasks:
            self.logger.trace("FIFO: cancelling operations")
            await self._in_tasks .cancel()
            await self._out_tasks.cancel()

    async def reset(self):
        await self.cancel()

        self.logger.trace("asserting reset")
        await self.device.write_register(self._addr_reset, 1)

        self.logger.trace("FIFO: synchronizing buffers")
        self.device.usb_handle.setInterfaceAltSetting(self._pipe_num, 1)
        self._in_buffer .clear()
        self._out_buffer.clear()

        # Pipeline reads before deasserting reset, so that if the applet immediately starts
        # streaming data, there are no overflows. (This is perhaps not the best way to implement
        # an applet, but we can support it easily enough, and it avoids surprise overflows.)
        self.logger.trace("FIFO: pipelining reads")
        for _ in range(_xfers_per_queue):
            self._in_tasks.submit(self._in_task())
        # Give the IN tasks a chance to submit their transfers before deasserting reset.
        await asyncio.sleep(0)

        self.logger.trace("deasserting reset")
        await self.device.write_register(self._addr_reset, 0)

    async def _in_task(self):
        if self._read_buffer_size is not None:
            async with self._in_pushback:
                while len(self._in_buffer) > self._read_buffer_size:
                    self.logger.trace("FIFO: read pushback")
                    await self._in_pushback.wait()

        size = self._in_packet_size * _packets_per_xfer
        data = await self.device.bulk_read(self._endpoint_in, size)
        self._in_buffer.write(data)

        self._in_tasks.submit(self._in_task())

    async def read(self, length=None, *, flush=True):
        if flush and len(self._out_buffer) > 0:
            # Flush the buffer, so that everything written before the read reaches the device.
            await self.flush(wait=False)

        if length is None and len(self._in_buffer) > 0:
            # Just return whatever is in the buffer.
            length = len(self._in_buffer)
        elif length is None:
            # Return whatever is received in the next transfer, even if it's nothing.
            # (Gateware doesn't normally submit zero-length packets, so, unless that changes
            # or customized gateware is used, we'll always get some data here.)
            self._in_stalls += 1
            await self._in_tasks.wait_one()
            length = len(self._in_buffer)
        else:
            # Return exactly the requested length.
            self._in_stalls += 1
            while len(self._in_buffer) < length:
                self.logger.trace("FIFO: need %d bytes", length - len(self._in_buffer))
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

        self.logger.trace("FIFO: read <%s>", dump_hex(result))
        return result

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
        if self._write_buffer_size is None:
            return out_xfer_size
        else:
            return min(self._write_buffer_size, out_xfer_size)

    async def _out_task(self, data):
        assert len(data) > 0

        try:
            await self.device.bulk_write(self._endpoint_out, data)
        finally:
            self._out_inflight -= len(data)

        # See the comment in `write` below for an explanation of the following code.
        if len(self._out_buffer) >= self._out_threshold:
            self._out_tasks.submit(self._out_task(self._out_slice()))

    async def write(self, data):
        if self._write_buffer_size is not None:
            # If write buffer is bounded, and we have more inflight requests than the configured
            # write buffer size, then wait until the inflight requests arrive before continuing.
            if self._out_inflight >= self._write_buffer_size:
                self._out_stalls += 1
            while self._out_inflight >= self._write_buffer_size:
                self.logger.trace("FIFO: write pushback")
                await self._out_tasks.wait_one()

        # Eagerly check if any of our previous queued writes errored out.
        await self._out_tasks.poll()

        self.logger.trace("FIFO: write <%s>", dump_hex(data))
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

    async def flush(self, wait=True):
        self.logger.trace("FIFO: flush")

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

        if wait:
            self.logger.trace("FIFO: wait for flush")
            if self._out_tasks:
                self._out_stalls += 1
            while self._out_tasks:
                await self._out_tasks.wait_all()

    def statistics(self):
        self.logger.info("FIFO statistics:")
        self.logger.info("  read total    : %d B",
                         self._in_buffer.total_read_bytes)
        self.logger.info("  written total : %d B",
                         self._out_buffer.total_written_bytes)
        self.logger.info("  reads waited  : %.3f s",
                         self._in_tasks.total_wait_time)
        self.logger.info("  writes waited : %.3f s",
                         self._out_tasks.total_wait_time)
        self.logger.info("  read stalls   : %d",
                         self._in_stalls)
        self.logger.info("  write stalls  : %d",
                         self._out_stalls)
        self.logger.info("  read wakeups  : %d",
                         self._in_tasks.total_wait_count)
        self.logger.info("  write wakeups : %d",
                         self._out_tasks.total_wait_count)
