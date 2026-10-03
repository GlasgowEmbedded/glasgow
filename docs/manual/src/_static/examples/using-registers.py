# assembly-logic.py
#
# Instantiate internal logic on Glasgow to blink the programmable LEDs.

import asyncio
import logging

from amaranth import *
from amaranth.lib import wiring, io
from amaranth.lib.wiring import In, Out
from glasgow.hardware.assembly import HardwareAssembly

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()

class DriveLEDs(wiring.Component):
    led_data: In(5)

    def elaborate(self, platform) -> Module:
        # Components are just Elaboratables -- they still return a Module
        # that encapsulates their logic.
        m = Module()

        # We build the LED pad buffers in the same way as we did in the
        # previous example.
        led_outs = []
        for n in range(5):
            pad = platform.request("led", n, dir="-")
            m.submodules[f"led_buffer_{n}"] = pad_buffer = io.Buffer("o", pad)
            led_outs.append(pad_buffer.o)
        led_out_bus = Cat(led_outs)
        
        # Now that we're controlling the LEDs from the host side, we don't
        # need to instantiate a counter of our own -- instead, we just
        # instantiate a flop stage between the data driven into this
        # Component and the LED output.
        m.d.sync += led_out_bus.eq(self.led_data)
        
        return m

async def main():
    assembly = await HardwareAssembly.find_device()
    
    # Now that the module has properties that we care about, we need to keep
    # a name for the module around!
    leds = DriveLEDs()
    assembly.add_submodule(leds)
    
    # Because the "led_data" input of our module just turns into a Signal,
    # we can pass that to anything else that will assign to it.  Here, we
    # use the Assembly's mechanism for connecting signals through to the
    # host -- a `RWRegister`, and we hand it the signal from our module to
    # drive bits onto.
    data_port = assembly.add_rw_register(leds.led_data)
    
    async with assembly:
        logger.info("assembly has started")
        while True:
            # Now, in our inner loop, we can update the contents of the data
            # register -- which then get sent to the data signal inside our
            # module, and in turn to the LEDs.
            await data_port.set(await data_port.get() + 1)
            await asyncio.sleep(0.1)

if __name__ == "__main__":
    asyncio.run(main())
