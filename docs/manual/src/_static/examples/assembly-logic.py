# assembly-logic.py
#
# Instantiate internal logic on Glasgow to blink the programmable LEDs.

import asyncio
import logging

from amaranth import *
from amaranth.lib import io
from glasgow.hardware.assembly import HardwareAssembly

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger()

class BlinkLEDs(Elaboratable):
    def elaborate(self, platform) -> Module:
        # The returned Module encapsulates all of the logic that we will
        # define.  It also contains any submodules that we will instantiate.
        m = Module()
        
        # In the future, we will pass I/O pins into a module using
        # Amaranth's Wiring subsystem, but for now, we use the Amaranth
        # Platform object that we were passed (which represents the Glasgow
        # board we are running on), and we retrieve I/O pads associated with
        # each of the five LEDs directly from there.
        led_outs = []
        for n in range(5):
            pad = platform.request("led", n, dir="-")
            
            # You cannot assign directly to a pad -- if you want to work
            # with a pad, you need to instantiate an I/O buffer for it.  The
            # I/O buffer, in turn, has signals that you can assign later.
            m.submodules[f"led_buffer_{n}"] = pad_buffer = io.Buffer("o", pad)
            
            led_outs.append(pad_buffer.o)
        
        # To make them easier to work with, we can concatenate together the
        # five one-bit-wide LED pad outputs to form a 5-bit-wide singal.
        led_out_bus = Cat(led_outs)
        
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
        #      led_out_bus = counter[27:23];
        #
        # (Note that bit indices in Amaranth follow Python MSB-exclusive
        # array index convention, rather than Verilog MSB-inclusive
        # convention!)
        m.d.comb += led_out_bus.eq(counter[23:28])
        
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
