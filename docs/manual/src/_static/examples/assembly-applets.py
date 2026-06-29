# assembly-applets.py
#
# Instantiate two UART applets and add them to an Assembly.  Then, trivially
# interact with them.
#
# To run this example, connect an external jumper cable between pins A0 and
# B0 on Glasgow.

import asyncio
import logging

from glasgow.hardware.assembly import HardwareAssembly
from glasgow.applet.interface.uart import UARTInterface

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()

async def main():
    assembly = await HardwareAssembly.find_device()
    
    assembly.use_voltage({"A": 3.3, "B": 3.3})
    
    # There is no inherent reason why these UARTs need to be on different
    # banks -- you can have multiple applets on a single I/O bank.  We do so
    # in this example because it is convenient using to attach the banks
    # together using Glasgow's included cabling.
    uart_a = UARTInterface(logger, assembly, tx="A0", rx=None)
    uart_b = UARTInterface(logger, assembly, tx=None, rx="B0")
    
    async with assembly:
        logger.info("assembly has started")
        await uart_a.set_baud(115200)
        await uart_b.set_baud(115200)
        
        tx_data = b"Hello, Glasgow!"
        
        # Start these in parallel!
        rx_task = asyncio.create_task(uart_b.read(len(tx_data)))
        tx_task = asyncio.create_task(uart_a.write(tx_data, flush=True))
        
        await tx_task
        logger.info("uart_a transmitted data, waiting for received data")
        
        async with asyncio.timeout(5):
            rx_data = await rx_task
        logger.info(f"uart_b received data {bytes(rx_data)}")
        assert tx_data == rx_data

if __name__ == "__main__":
    asyncio.run(main())
