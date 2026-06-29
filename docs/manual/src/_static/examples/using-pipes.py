# using-pipes.py
#
# Instantiate a higher bandwidth external-loopback path on Glasgow, using
# input and output buffers that are connected to pipes.
import asyncio
import logging

from amaranth import *
from amaranth.lib import wiring, io, stream
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.wiring import In, Out
from glasgow.hardware.assembly import HardwareAssembly

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()

class PipesToPorts(wiring.Component):
    tx_stream: In(stream.Signature(8)) # Pipes are always 8-bits.
    rx_stream: Out(stream.Signature(8))
    
    rx_received: Out(16)
    rx_overflow_count: Out(16)

    _tx_port: io.PortLike
    _rx_port: io.PortLike
    
    def __init__(self, tx_port, rx_port):
        assert len(tx_port) == 4
        assert len(rx_port) == 4
        
        self._tx_port = tx_port
        self._rx_port = rx_port
        
        super().__init__()
    
    def elaborate(self, platform) -> Module:
        m = Module()
        
        m.submodules.tx_buf = tx_buf = io.Buffer("o", self._tx_port)
        
        m.d.comb += self.tx_stream.ready.eq(1)
        
        m.d.sync += tx_buf.o[0].eq(self.tx_stream.valid)
        m.d.sync += tx_buf.o[1:4].eq(~self.tx_stream.payload[0:3])

        m.submodules.rx_buf = rx_buf = io.Buffer("i", self._rx_port)

        rx_data = Signal(4)
        m.submodules.sync_rx = FFSynchronizer(rx_buf.i, rx_data)
        
        m.d.comb += self.rx_stream.valid.eq(rx_data[0])
        m.d.comb += self.rx_stream.payload.eq(rx_data[1:4])
        
        with m.If(self.rx_stream.valid):
            m.d.sync += self.rx_received.eq(self.rx_received + 1)
            
            with m.If(~self.rx_stream.ready):
                m.d.sync += self.rx_overflow_count.eq(self.rx_overflow_count + 1)
        
        return m

async def main():
    assembly = await HardwareAssembly.find_device()
    
    # Again, there is no inherent reason why these need to be on different
    # ports; we do so in this example to make it easier to connect Glasgow
    # in the specified way using the wiring in the package.
    assembly.use_voltage({"A": 3.3, "B": 3.3})

    driver = PipesToPorts(
        tx_port=assembly.add_port(pins=("A0", "A1", "A2", "A3"), name="tx"),
        rx_port=assembly.add_port(pins=("B0", "B1", "B2", "B3"), name="rx")
    )
    assembly.add_submodule(driver)

    rx_received = assembly.add_ro_register(driver.rx_received)
    rx_overflow_count = assembly.add_ro_register(driver.rx_overflow_count)
    
    tx_pipe = assembly.add_out_pipe(driver.tx_stream, fifo_depth = 8)
    rx_pipe = assembly.add_in_pipe(driver.rx_stream, fifo_depth = 16, buffer_size = 32)
    
    async with assembly:
        logger.info("assembly has started")
        
        # The applet might not have been reset, if it was cached and
        # previously running on Glasgow, so these registers may have a
        # nonzero initialization value.
        rx_received_initial = await rx_received.get()
        rx_overflow_count_initial = await rx_overflow_count.get()
        
        logger.info("pipes: testing the good case of receiving the number of bytes we send")
        rx_task = asyncio.create_task(rx_pipe.recv(8))
        await tx_pipe.send(b'\x00\x01\x02\x03\x04\x05\x06\x07')
        await tx_pipe.flush()
        rx_data = await rx_task
        
        assert rx_data == b'\x07\x06\x05\x04\x03\x02\x01\x00'
        assert (await rx_received.get() - rx_received_initial) == 8
        assert (await rx_overflow_count.get() - rx_overflow_count_initial) == 0
        
        logger.info("pipes: testing the bad case: sending too much data, and too quickly!")
        await tx_pipe.send(b'\x00' * 256)
        await tx_pipe.flush()
        
        assert (await rx_received.get() - rx_received_initial) == (8 + 256)
        
        # There are a few valid options here.  There should be, at most,
        # 256-16 words that got overflowed -- that would happen if the
        # fifo_depth filled up immediately, and no words got popped out by
        # the host before we finished pushing.  Or, at the very least, we
        # should have sent not more than the buffer_size + fifo_depth worth
        # of words, when the host would fill up its software buffer and stop
        # receiving.
        #
        # On implementations current as of the time of this writing, the USB
        # flush logic results in 256-16 words beint dropped.
        overflowed = await rx_overflow_count.get() - rx_overflow_count_initial
        assert overflowed >= 256 - 16 - 32 and overflowed <= 256 - 16
            
        # Flush all remaining data in the internal buffer (happens
        # immediately), and any data in the Glasgow hardware FIFO (which
        # might take a little bit to come in, since there may have been data
        # still in Glasgow's FIFO waiting for space in the software buffer).
        try:
            while True:
                async with asyncio.timeout(0.25):
                    await rx_pipe.recv(rx_pipe.readable or 1)
        except TimeoutError:
            pass
        
        logger.info("pipes: testing to be sure we are back in sync")
        rx_task = asyncio.create_task(rx_pipe.recv(4))
        await tx_pipe.send(b'\x07\x00\x07\x00')
        await tx_pipe.flush()
        rx_data = await rx_task
        assert rx_data == b'\x00\x07\x00\x07'
        
        tx_pipe.statistics()
        rx_pipe.statistics()

if __name__ == "__main__":
    asyncio.run(main())
