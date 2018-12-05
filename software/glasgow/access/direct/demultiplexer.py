import usb1
import math

from ...support.logging import *
from ...support.chunked_fifo import *
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
# In other words, there is be a platform-specific limit for USB I/O size, which is not
# discoverable via libusb, and hitting which does not result in a sensible error returned
# from libusb (it returns LIBUSB_ERROR_IO even though USBDEVFS_SUBMITURB ioctl correctly
# returns -ENOMEM, so it is not even possible to be optimistic and back off after hitting it.
#
# To deal with this, use requests of at most 1024 EP buffer sizes (512 KiB with the FX2) as
# an arbitrary cutoff, and hope for the best.
_max_buffers_per_io = 1024


class DirectDemultiplexer(AccessDemultiplexer):
    def __init__(self, device):
        super().__init__(device)
        self._claimed = set()

    async def claim_interface(self, applet, mux_interface, args):
        assert mux_interface._pipe_num not in self._claimed
        self._claimed.add(mux_interface._pipe_num)

        iface = DirectDemultiplexerInterface(self.device, applet, mux_interface)
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

        await iface.reset()
        return iface


class DirectDemultiplexerInterface(AccessDemultiplexerInterface):
    def __init__(self, device, applet, mux_interface):
        super().__init__(device, applet)

        self._pipe_num   = mux_interface._pipe_num
        self._addr_reset = mux_interface._addr_reset

        config_num = self.device.usb.getConfiguration()
        for config in self.device.usb.getDevice().iterConfigurations():
            if config.getConfigurationValue() == config_num:
                break

        interfaces = list(config.iterInterfaces())
        assert self._pipe_num <= len(interfaces)
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

        self._interface  = self.device.usb.claimInterface(self._pipe_num)
        self._buffer_in  = ChunkedFIFO()
        self._buffer_out = ChunkedFIFO()

    async def reset(self):
        self.logger.trace("asserting reset")
        await self.device.write_register(self._addr_reset, 1)
        self.logger.trace("synchronizing FIFOs")
        self.device.usb.setInterfaceAltSetting(self._pipe_num, 1)
        self.logger.trace("deasserting reset")
        await self.device.write_register(self._addr_reset, 0)

    async def _read_packet(self, hint=0):
        buffers = min(_max_buffers_per_io, max(1, math.ceil(hint / self._endpoint_in)))
        packet  = await self.device.bulk_read(self._endpoint_in, self._in_packet_size * buffers)
        self._buffer_in.write(packet)

    async def read(self, length=None, hint=0):
        # Always try to allocate at least as many USB buffers as the amount of data we know we're
        # going to read from the FIFO. The real value is capped to avoid hitting platform-specific
        # limits for USB I/O size (see above).
        if length is not None:
            hint = max(hint, length)

        if len(self._buffer_out) > 0:
            # Flush the buffer, so that everything written before the read reaches the device.
            await self.flush()

        if length is None and len(self._buffer_in) > 0:
            # Just return whatever is in the buffer.
            length = len(self._buffer_in)
        elif length is None:
            # Return whatever is received in the next transfer, even if it's nothing.
            await self._read_packet(hint)
            length = len(self._buffer_in)
        else:
            # Return exactly the requested length.
            while len(self._buffer_in) < length:
                self.logger.trace("FIFO: need %d bytes", length - len(self._buffer_in))
                await self._read_packet(hint)

        result = self._buffer_in.read(length)
        if len(result) < length:
            result = bytearray(result)
            while len(result) < length:
                result += self._buffer_in.read(length - len(result))
            # Always return a memoryview object, to avoid hard to detect edge cases downstream.
            result = memoryview(result)

        self.logger.trace("FIFO: read <%s>", dump_hex(result))
        return result

    async def _write_packet(self):
        # Fast path: read as much contiguous data as possible, but not too much, as there might
        # be a platform-specific limit for USB I/O size (see above).
        packet = self._buffer_out.read(self._out_packet_size * _max_buffers_per_io)

        if len(packet) < self._out_packet_size and self._buffer_out:
            # Slow path: USB is annoyingly high latency with small packets, so if we only got a few
            # bytes from the FIFO, and there is much more in it, spend CPU time to aggregate that
            # into at least one EP buffer sized packet, as this is likely to result in overall
            # reduction of runtime.
            packet = bytearray(packet)
            while len(packet) < self._out_packet_size and self._buffer_out:
                packet += self._buffer_out.read(self._out_packet_size)

        await self.device.bulk_write(self._endpoint_out, packet)

    async def write(self, data):
        self.logger.trace("FIFO: write <%s>", dump_hex(data))
        self._buffer_out.write(data)

        if len(self._buffer_out) > self._out_packet_size:
            await self._write_packet()

    async def flush(self):
        self.logger.trace("FIFO: flush")
        while self._buffer_out:
            await self._write_packet()
