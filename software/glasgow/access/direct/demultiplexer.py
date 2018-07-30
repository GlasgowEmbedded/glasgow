import usb1

from .. import AccessDemultiplexer, AccessDemultiplexerInterface


class DirectDemultiplexer(AccessDemultiplexer):
    def __init__(self, device):
        super().__init__(device)
        self._claimed    = set()

    async def claim_interface(self, applet, mux_interface, args):
        assert mux_interface._fifo_num not in self._claimed
        self._claimed.add(mux_interface._fifo_num)

        iface = DirectDemultiplexerInterface(self.device, applet, mux_interface)
        self._interfaces.append(iface)

        if hasattr(args, "mirror_voltage") and args.mirror_voltage:
            for port in args.port_spec:
                await self.device.mirror_voltage(port)
                applet.logger.info("port %s voltage set to %.1f V",
                                   port, self.device.get_voltage(port))
        elif hasattr(args, "voltage") and args.voltage is not None:
            await self.device.set_voltage(args.port_spec, args.voltage)
            applet.logger.info("port(s) %s voltage set to %.1f V",
                               ", ".join(sorted(args.port_spec)), args.voltage)
        elif hasattr(args, "keep_voltage") and args.keep_voltage:
            applet.logger.info("port voltage unchanged")

        return iface


class DirectDemultiplexerInterface(AccessDemultiplexerInterface):
    def __init__(self, device, applet, mux_interface):
        super().__init__(device, applet)

        config_num = self.device.usb.getConfiguration()
        for config in self.device.usb.getDevice().iterConfigurations():
            if config.getConfigurationValue() == config_num:
                break

        interfaces = list(config.iterInterfaces())
        assert mux_interface._fifo_num <= len(interfaces)
        interface = interfaces[mux_interface._fifo_num]

        settings = list(interface.iterSettings())
        setting = settings[0] # we use the same endpoints in all alternative settings
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

        self._interface  = self.device.usb.claimInterface(mux_interface._fifo_num)
        self._buffer_in  = bytearray()
        self._buffer_out = bytearray()

    async def _read_packet(self):
        packet = await self.device.bulk_read(self._endpoint_in, self._in_packet_size)
        self._buffer_in += packet

    async def read(self, length=None):
        if len(self._buffer_out) > 0:
            # Flush the buffer, so that everything written before the read reaches the device.
            await self.flush()

        if length is None and len(self._buffer_in) > 0:
            # Just return whatever is in the buffer.
            length = len(self._buffer_in)
        elif length is None:
            # Return whatever is received in the next transfer, even if it's nothing.
            await self._read_packet()
            length = len(self._buffer_in)
        else:
            # Return exactly the requested length.
            while len(self._buffer_in) < length:
                await self._read_packet()

        result = self._buffer_in[:length]
        self._buffer_in = self._buffer_in[length:]
        self.logger.trace("FIFO: read <%s>", result.hex())
        return result

    async def _write_packet(self):
        packet = self._buffer_out[:self._out_packet_size]
        self._buffer_out = self._buffer_out[self._out_packet_size:]
        await self.device.bulk_write(self._endpoint_out, packet)

    async def write(self, data):
        if not isinstance(data, (bytes, bytearray)):
            data = bytes(data)

        self.logger.trace("FIFO: write <%s>", data.hex())
        self._buffer_out += data

        if len(self._buffer_out) > self._out_packet_size:
            await self._write_packet()

    async def flush(self):
        self.logger.trace("FIFO: flush")
        while len(self._buffer_out) > 0:
            await self._write_packet()
