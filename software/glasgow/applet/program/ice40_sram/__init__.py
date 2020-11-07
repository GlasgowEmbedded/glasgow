import argparse
import asyncio
import logging
from nmigen.compat import *

from ...interface.spi_controller import SPIControllerApplet
from ... import *


class ProgramICE40SRAMInterface:
    def __init__(self, interface, logger, device, addr_dut_reset, addr_dut_done):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._device = device
        self._addr_dut_reset = addr_dut_reset
        self._addr_dut_done  = addr_dut_done

    async def set_reset(self, reset):
        await self._device.write_register(self._addr_dut_reset, int(reset))

    async def get_done(self):
        if self._addr_dut_reset is not None:
            return await self._device.read_register(self._addr_dut_done)

    async def program(self, bitstream):
        # Pulse reset while setting SS_n low (we use a dummy write to do that)
        await self.set_reset(True)
        await self.lower.write([], hold_ss=True)
        await self.lower.synchronize()
        await self.set_reset(False)

        # Wait at least 1.2ms (spec for 8k devices)
        await self.lower.delay_us(1200)

        # Write bitstream
        while len(bitstream) > 0:
            chunk = bitstream[:255]
            bitstream = bitstream[255:]
            await self.lower.write(chunk, hold_ss=True)

        # Specs says at least 49 dummy bits. Send 128.
        await self.lower.write([0] * 16)


class ProgramICE40SRAMApplet(SPIControllerApplet, name="program-ice40-sram"):
    logger = logging.getLogger(__name__)
    help = "program SRAM of iCE40 FPGAs"
    description = """
    Program the volatile bitstream memory of iCE40 FPGAs.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access, omit_pins=True)

        access.add_pin_argument(parser, "sck",   required=True)
        access.add_pin_argument(parser, "cs",    required=True)
        access.add_pin_argument(parser, "copi",  required=True)
        access.add_pin_argument(parser, "reset", required=True)
        access.add_pin_argument(parser, "done")

    def build(self, target, args):
        subtarget = super().build(target, args, pins=("sck", "cs", "copi"))

        reset_t = self.mux_interface.get_pin(args.pin_reset)
        dut_reset, self.__addr_dut_reset = target.registers.add_rw(1)
        subtarget.comb += [
            reset_t.o.eq(0),
            reset_t.oe.eq(dut_reset),
        ]

        if args.pin_done is not None:
            done_t = self.mux_interface.get_pin(args.pin_done)
            dut_done, self.__addr_dut_done = target.registers.add_ro(1)
            subtarget.comb += [
                dut_done.eq(done_t.i),
            ]
        else:
            self.__addr_dut_done = None

        return subtarget

    @classmethod
    def add_interact_arguments(cls, parser):
        parser.add_argument(
            "bitstream", metavar="BITSTREAM", type=argparse.FileType("rb"),
            help="bitstream file")

    async def run(self, device, args):
        spi_iface = await self.run_lower(ProgramICE40SRAMApplet, device, args)
        return ProgramICE40SRAMInterface(spi_iface, self.logger, device,
                                         self.__addr_dut_reset, self.__addr_dut_done)

    async def interact(self, device, args, ice40_iface):
        bitstream = args.bitstream.read()
        await ice40_iface.program(bitstream)

        if args.pin_done is not None:
            for _ in range(200):    # Wait up to 2s
                await asyncio.sleep(0.010)  # Poll every 10 ms
                done = await ice40_iface.get_done()
                if done:
                    break
            if done:
                self.logger.info("FPGA successfully configured")
            else:
                self.logger.warning("FPGA failed to configure after releasing reset")

# -------------------------------------------------------------------------------------------------

class ProgramICE40SRAMAppletTestCase(GlasgowAppletTestCase, applet=ProgramICE40SRAMApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--pin-reset", "0", "--pin-done", "1",
                                "--pin-sck",   "2", "--pin-cs",   "3",
                                "--pin-copi",  "4"])
