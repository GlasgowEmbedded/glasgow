"""An example of instantiating several applets without using the CLI.

This can be useful when the overall interaction flow is non-interative and programmatic, or
when embedding the Glasgow toolkit in other Python applications (it is fully usable as a normal
Python library!)

In this demo, your DUT has three interfaces: an SPI Flash with program memory, an UART to
communicate with a CPU in a SoC, and a general purpose pin to reset the SoC (so that the SPI Flash
may be programmed).

Any "new-style" applet (which uses `AbstractAssembly` in its `*Interface` class) can be used in
this fashion. Some applets are "old-style" and haven't been ported to use `AbstractAssembly` yet.
Such applets must be ported first. See the git history for how to do this.

Some examples of applets that can be used in this way are:
    * `jtag-probe`
    * `probe-rs`
    * `uart-analyzer`, `spi-analyzer`, `qspi-analyzer`
"""

import asyncio
import logging
from glasgow.hardware.assembly import HardwareAssembly
from glasgow.applet.memory._25x import Memory25xInterface
from glasgow.applet.interface.uart import UARTInterface
from glasgow.applet.control.gpio import GPIOInterface


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()


async def main():
    assembly = await HardwareAssembly.find_device()
    assembly.use_voltage({"A": 3.3, "B": 3.3})
    spi_rom_iface = Memory25xInterface(logger, assembly,
        cs="A0", sck="A1", io="A2:5")
    uart_iface = UARTInterface(logger, assembly,
        rx="B0", tx="B1")
    gpio_iface = GPIOInterface(logger, assembly,
        pins="B2")

    async with assembly:
        await spi_rom_iface.qspi.clock.set_frequency(1_000_000)
        await uart_iface.set_baud(115200)

        # Pretend to program the Flash.
        # (Actual production code would likely use `.erase_program(...)` here.)
        await gpio_iface.output(0, True)
        mfg_id, dev_id = await spi_rom_iface.read_manufacturer_long_device_id()
        print(f"flash ID: {mfg_id:02x},{dev_id:04x}")
        data = await spi_rom_iface.fast_read(0x1000, 0x10)
        print(f"program memory: {data.hex()}")

        # Talk to the SoC.
        await gpio_iface.output(0, False)
        await asyncio.sleep(10e-3)
        await uart_iface.write(b"INIT?")
        reply = await uart_iface.read(2)
        print(reply.hex()) # b"OK"


if __name__ == "__main__":
    asyncio.run(main())
