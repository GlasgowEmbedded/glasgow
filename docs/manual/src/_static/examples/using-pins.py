# using-pins.py
#
# Instantiate an external-loopback path on Glasgow using input and output
# buffers.

import asyncio
import logging

from amaranth import *
from amaranth.lib import wiring, io
from amaranth.lib.cdc import FFSynchronizer
from amaranth.lib.wiring import In, Out
from glasgow.hardware.assembly import HardwareAssembly

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()

class DrivePorts(wiring.Component):
    tx_data: In(4)
    rx_data: Out(4)
    
    # The In- and Out-typed properties in a Component inform the Component's
    # signature, but you can of course have any other type of property in a
    # Component.  Here, we provide a mechanism for the harness to attach
    # pins.
    tx_port: io.PortLike
    rx_port: io.PortLike
    
    def elaborate(self, platform) -> Module:
        m = Module()
        
        # Much like the LED drivers, we instantiate I/O buffers for the pins
        # that we are passed.
        m.submodules.tx_buf = tx_buf = io.Buffer("o", self.tx_port)
        m.submodules.rx_buf = rx_buf = io.Buffer("i", self.rx_port)
        
        # Although the cone of logic is simple here, we generally prefer to
        # drive output pins directly from the output pins of flops
        # (expressed here with the "sync" control domain).  Doing so means
        # that pins that drive external asynchronous devices will change at
        # most once per clock, rather than glitching as internal logic paths
        # propagate.
        m.d.sync += tx_buf.o.eq(~self.tx_data)
    
        # To avoid metastability, it is good practice to synchronize inputs
        # coming from outside the chip into a clock domain.  (In this
        # example, it is not strictly necessary, because the input pins
        # should be connected to the output pins from the same clock domain! 
        # But the pins do leave the physical Glasgow package, and could
        # theoretically be connected to anything, so we synchronize them in
        # to be sure.)
        m.submodules.sync_rx = FFSynchronizer(rx_buf.i, self.rx_data)
        
        return m

async def main():
    assembly = await HardwareAssembly.find_device()
    
    # Again, there is no inherent reason why these need to be on different
    # ports; we do so in this example to make it easier to connect Glasgow
    # in the specified way using the wiring in the package.
    assembly.use_voltage({"A": 3.3, "B": 3.3})
    
    driver = DrivePorts()
    assembly.add_submodule(driver)

    # The usage of "assembly.add_port" in this example is very similar to
    # the "platform.request" API in the previous examples.
    driver.tx_port = assembly.add_port(pins=("A0", "A1", "A2", "A3"), name="tx")
    driver.rx_port = assembly.add_port(pins=("B0", "B1", "B2", "B3"), name="rx")

    # In this example, we instantiate not just a read-write
    # (host-to-Glasgow) register, but a read-only (Glasgow-to-host)
    # register.  We connect them from the harness into the signals in the
    # module.
    tx_reg = assembly.add_rw_register(driver.tx_data)
    rx_reg = assembly.add_ro_register(driver.rx_data)
    
    async with assembly:
        logger.info("assembly has started")
        
        # Write a sequence of four-bit values to the pins by writing their
        # register, and then read back each time to make sure that we
        # receive what we expected.
        for i in range(16):
            await tx_reg.set(i)
            rv = await rx_reg.get()

            expected = i ^ 0xF
            logger.info(f"transmitted {i:x}, received {rv:x} (expected {expected:x})")
            assert rv == expected

if __name__ == "__main__":
    asyncio.run(main())
