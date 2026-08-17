# assembly-skeleton.py

import asyncio
import logging

from glasgow.hardware.assembly import HardwareAssembly

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()

async def main():
    assembly = await HardwareAssembly.find_device()
    async with assembly:
        logger.info("Glasgow is alive!")
        await asyncio.sleep(5)

if __name__ == "__main__":
    asyncio.run(main())
