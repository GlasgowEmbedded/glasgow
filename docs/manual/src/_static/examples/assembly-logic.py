# assembly-logic.py
#
# Instantiate internal logic on Glasgow to blink the programmable LEDs.

import asyncio
import logging

from amaranth import *
from glasgow.hardware.assembly import HardwareAssembly

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()

class BlinkLEDs(Elaboratable):
    def elaborate(self, platform) -> Module:
        # The returned Module encapsulates all of the logic that we will
        # define.
        m = Module()
        
        # In the future, we will pass I/O pins into a module using
        # Amaranth's Wiring subsystem, but for now, we use the Amaranth
        # Platform object that we were passed (which represents the Glasgow
        # board we are running on), and we retrieve I/O pads associated with
        # each of the five LEDs directly from there.
        led_pads = [platform.request("led", n) for n in range(5)]
        
        # You cannot assign directly to a pad -- if you want to work with a
        # pad, you need to assign to its output buffer (or assign from its
        # input buffer).
        led_outs = Cat(pin.o for pin in led_pads)
        
        # Experienced digital logic designers will realize that this infers
        # a flipflop; in Glasgow's mental model, we are creating a signal,
        # and then adding an assignment to that signal into the list for the
        # synchronous control domain.  In Verilog, this would be roughly
        # equivalent to:
        #
        #   reg [31:0] counter;
        #   always @(posedge sync_clk)
        #       counter <= counter + 1;
        counter = Signal(32)
        m.d.sync += counter.eq(counter + 1)
        
        # The "combinational" control domain is special, and statements
        # added to that control domain take effect continuously.  In
        # Verilog, this would be roughly equivalent to:
        #
        #  always @(*)
        #      led_outs = counter[27:23];
        #
        # (Note that bit indices in Amaranth follow Python MSB-exclusive
        # array index convention, rather than Verilog MSB-inclusive
        # convention.)
        m.d.comb += led_outs.eq(counter[23:28])
        
        return m

async def main():
    assembly = await HardwareAssembly.find_device()
    
    assembly.add_submodule(BlinkLEDs())
    
    async with assembly:
        logger.info("assembly has started")
        while True:
            await asyncio.sleep(1)

if __name__ == "__main__":
    asyncio.run(main())
