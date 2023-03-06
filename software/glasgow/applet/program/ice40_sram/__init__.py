import argparse
import asyncio
import logging
from amaranth import *

from ...interface.spi_controller import SPIControllerApplet
from ... import *


class ProgramICE40SRAMSubtarget:
    def __init__(self, controller, reset_t, dut_reset, done_t, dut_done):
        self.controller = controller
        self.reset_t = reset_t
        self.dut_reset = dut_reset
        self.done_t = done_t
        self.dut_done = dut_done

    def elaborate(self, platform):
        m = Module()

        m.submodules.controller = self.controller

        m.d.comb += [
            self.reset_t.o.eq(0),
            self.reset_t.oe.eq(self.dut_reset)
        ]

        if self.done_t is not None:
            m.d.comb += self.dut_done.eq(self.done_t.i)

        return m


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

    def build_subtarget(self, target, args):
        subtarget = super().build_subtarget(target, args, pins=("sck", "cs", "copi"))

        reset_t = self.mux_interface.get_pin(args.pin_reset)
        dut_reset, self.__addr_dut_reset = target.registers.add_rw(1)

        if args.pin_done is not None:
            done_t = self.mux_interface.get_pin(args.pin_done)
            dut_done, self.__addr_dut_done = target.registers.add_ro(1)
        else:
            done_t = None
            dut_done = None
            self.__addr_dut_done = None

        return ProgramICE40SRAMSubtarget(subtarget, reset_t, dut_reset, done_t, dut_done)

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
