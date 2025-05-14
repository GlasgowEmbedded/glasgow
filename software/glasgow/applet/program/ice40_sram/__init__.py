# Ref: iCE40 Programming and Configuration Technical Note
# Document Number: FPGA-TN-02001-3.2
# Accession: G00073

import argparse
import asyncio
import logging
from amaranth import *
from amaranth.lib import io

from ...interface.spi_controller import SPIControllerApplet
from ... import *


class ProgramICE40SRAMSubtarget(Elaboratable):
    def __init__(self, controller, port_reset, dut_reset, port_done, dut_done):
        self.controller = controller
        self.port_reset = port_reset
        self.dut_reset  = dut_reset
        self.port_done  = port_done
        self.dut_done   = dut_done

    def elaborate(self, platform):
        m = Module()

        m.submodules.controller = self.controller

        m.submodules.reset_buffer = reset_buffer = io.Buffer("o", self.port_reset)

        m.d.comb += [
            reset_buffer.o.eq(0),
            reset_buffer.oe.eq(self.dut_reset)
        ]

        if self.port_done is not None:
            m.submodules.done_buffer = done_buffer = io.Buffer("i", self.port_done)
            m.d.comb += self.dut_done.eq(done_buffer.i)

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
        if self._addr_dut_done is not None:
            return await self._device.read_register(self._addr_dut_done)
        else:
            return True

    async def program(self, bitstream):
        async with self.lower.select():
            # Pulse reset while holding SSn low
            await self.lower.synchronize()
            await self.set_reset(True)
            await self.set_reset(False)
            await self.lower.synchronize()

            # Wait at least 1.2ms (spec for 8k devices)
            await self.lower.delay_us(1200)

            # Write bitstream
            await self.lower.write(bitstream)

            # Specs says at least 49 dummy bits. Send 128.
            await self.lower.dummy(128)


class ProgramICE40SRAMApplet(SPIControllerApplet):
    logger = logging.getLogger(__name__)
    help = "program SRAM of iCE40 FPGAs"
    description = """
    Program the volatile bitstream memory of iCE40 FPGAs.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access, omit_pins=True)

        access.add_pins_argument(parser, "sck",   required=True)
        access.add_pins_argument(parser, "cs",    required=True)
        access.add_pins_argument(parser, "copi",  required=True)
        access.add_pins_argument(parser, "reset", required=True)
        access.add_pins_argument(parser, "done")

    def build_subtarget(self, target, args):
        subtarget = super().build_subtarget(target, args)

        port_reset = self.mux_interface.get_port(args.reset, name="reset")
        dut_reset, self.__addr_dut_reset = target.registers.add_rw(1)

        if args.done is not None:
            port_done = self.mux_interface.get_port(args.done, name="done")
            dut_done, self.__addr_dut_done = target.registers.add_ro(1)
        else:
            port_done = None
            dut_done = None
            self.__addr_dut_done = None

        return ProgramICE40SRAMSubtarget(subtarget, port_reset, dut_reset, port_done, dut_done)

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

        if args.done is not None:
            for _ in range(200):    # Wait up to 2s
                await asyncio.sleep(0.010)  # Poll every 10 ms
                done = await ice40_iface.get_done()
                if done:
                    break
            if done:
                self.logger.info("FPGA successfully configured")
            else:
                self.logger.warning("FPGA failed to configure after releasing reset")

    @classmethod
    def tests(cls):
        from . import test
        return test.ProgramICE40SRAMAppletTestCase
