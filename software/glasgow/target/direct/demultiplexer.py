import usb1

from ..access import AccessDemultiplexer, AccessDemultiplexerInterface


class DirectDemultiplexer(AccessDemultiplexer):
    def __init__(self, device, interface_count):
        self._device         = device
        self._claimed_ifaces = 0
        self._iface_count    = interface_count
        self._interfaces     = []

    def claim_raw_interface(self, applet, timeout=None, async=False):
        if self._claimed_ifaces == self._iface_count:
            applet.logger.fatal("cannot claim USB interface: out of interfaces")
            return None
        iface_num = self._claimed_ifaces
        self._claimed_ifaces += 1

        if async:
            self._device.get_poller()

        iface = DirectDemultiplexerInterface(self._device, iface_num, applet, timeout, async)
        self._interfaces.append(iface)
        return iface

    def claim_interface(self, applet, args, timeout=None, async=False):
        iface = self.claim_raw_interface(applet, timeout, async)

        if args.mirror_voltage:
            for port in args.port_spec:
                self._device.mirror_voltage(port)
                applet.logger.info("port %s voltage set to %.1f V",
                                   port, self._device.get_voltage(port))
        elif args.voltage is not None:
            self._device.set_voltage(args.port_spec, args.voltage)
            applet.logger.info("port(s) %s voltage set to %.1f V",
                               ", ".join(sorted(args.port_spec)), args.voltage)
        elif args.keep_voltage:
            applet.logger.info("port voltage unchanged")

        return iface


class DirectDemultiplexerInterface(AccessDemultiplexerInterface):
    def __init__(self, device, interface_num, applet, timeout, async):
        self._device  = device
        self._usb     = device.usb
        self._applet  = applet
        self._logger  = applet.logger
        self._timeout = None if timeout is None else round(timeout * 1000)
        self._async   = async

        config_num = self._usb.getConfiguration()
        for config in self._usb.getDevice().iterConfigurations():
            if config.getConfigurationValue() == config_num:
                break

        interfaces = list(config.iterInterfaces())
        assert interface_num <= len(interfaces)
        interface = interfaces[interface_num]

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

        self._interface  = self._usb.claimInterface(interface_num)
        self._buffer_in  = bytearray()
        self._buffer_out = bytearray()

        if self._async:
            self._in_transfer = self._usb.getTransfer()
            def callback(transfer):
                self._logger.trace("USB: EP%x IN (completed)", self._endpoint_in & 0x7f)
            self._in_transfer.setBulk(self._endpoint_in, self._in_packet_size, callback)
            self._in_transfer.submit()
            self._logger.trace("USB: EP%x IN (submit)", self._endpoint_in & 0x7f)

            self._out_transfer = self._usb.getTransfer()
            def callback(transfer):
                self._logger.trace("USB: EP%x OUT (completed)", self._endpoint_out)
                self._write_packet_async()
            self._out_transfer.setBulk(self._endpoint_out, 0, callback)

    def has_buffered_data(self):
        if len(self._buffer_in) > 0 or len(self._buffer_out) > 0:
            return True
        if self._async:
            return not self._in_transfer.isSubmitted() or self._out_transfer.isSubmitted()
        else:
            return False

    def _append_in_packet(self, packet):
        self._logger.trace("USB: EP%x IN: %s", self._endpoint_in & 0x7f, packet.hex())
        self._buffer_in += packet

    def _read_packet_async(self):
        if self._in_transfer.isSubmitted():
            return False
        elif self._in_transfer.getStatus() != usb1.TRANSFER_COMPLETED:
            usb1.raiseUSBError(self._in_transfer.getStatus())
        else:
            packet = self._in_transfer.getBuffer()[:self._in_transfer.getActualLength()]
            self._append_in_packet(packet)
            self._logger.trace("USB: EP%x IN (submit)", self._endpoint_in & 0x7f)
            self._in_transfer.submit()
            return True

    def _read_packet_sync(self):
        packet = self._usb.bulkRead(self._endpoint_in, self._in_packet_size, self._timeout)
        self._append_in_packet(packet)

    def read(self, length=None):
        if len(self._buffer_out) > 0:
            # Flush the buffer, so that everything written before the read reaches the device.
            self.flush()

        if length is None and len(self._buffer_in) > 0:
            # Just return whatever is in the buffer.
            length = len(self._buffer_in)
        if self._async:
            # Always check if we have new data waiting to be read, and rearm the transfer.
            # This ensures that the poll call will have something to wait on.
            self._read_packet_async()
            if length is None:
                # Return whatever is in the buffer, even if it's nothing.
                length = len(self._buffer_in)
            elif len(self._buffer_in) >= length:
                # Return exactly the requested length if we have it.
                pass
            else:
                # Return None if we can't fulfill the request.
                return None
        else:
            if length is None:
                # Sync reads with no requested length always block if there's nothing
                # in the buffer, or we'll never get a chance to refill the buffer if
                # the application code only issues reads with no requested length.
                self._read_packet_sync()
                length = len(self._buffer_in)
            else:
                # Sync reads always return exactly the requested length, if any.
                while len(self._buffer_in) < length:
                    self._read_packet_sync()

        result = self._buffer_in[:length]
        self._buffer_in = self._buffer_in[length:]
        self._logger.trace("FIFO: read <%s>", result.hex())
        return result

    def _slice_out_packet(self):
        packet = self._buffer_out[:self._out_packet_size]
        self._buffer_out = self._buffer_out[self._out_packet_size:]
        self._logger.trace("USB: EP%x OUT: <%s>", self._endpoint_out, packet.hex())
        return packet

    def _write_packet_async(self):
        if self._out_transfer.isSubmitted():
            pass
        elif self._out_transfer.getStatus() != usb1.TRANSFER_COMPLETED:
            usb1.raiseUSBError(self._out_transfer.getStatus())
        elif len(self._buffer_out) > 0:
            packet = self._slice_out_packet()
            self._out_transfer.setBuffer(packet)
            self._logger.trace("USB: EP%x OUT (submit)", self._endpoint_out)
            self._out_transfer.submit()

    def _write_packet_sync(self):
        packet = self._slice_out_packet()
        self._usb.bulkWrite(self._endpoint_out, packet, self._timeout)

    def write(self, data, async=False):
        data = bytearray(data)

        self._logger.trace("FIFO: write <%s>", data.hex())
        self._buffer_out += data

        if self._async:
            if len(self._buffer_out) > self._out_packet_size:
                self._write_packet_async()
        else:
            while len(self._buffer_out) > self._out_packet_size:
                self._write_packet_sync()

    def flush(self):
        self._logger.trace("FIFO: flush")
        if self._async:
            self._write_packet_async()
        else:
            while len(self._buffer_out) > 0:
                self._write_packet_sync()

    def poll(self):
        if self.has_buffered_data():
            # If we have data in IN endpoint buffers, always return right away, but also
            # peek at what other fds might have become ready, for efficiency.
            return self._device.poll(0)
        else:
            # Otherwise, just wait on USB transfers and any other registered fds.
            return self._device.poll(self._timeout)
