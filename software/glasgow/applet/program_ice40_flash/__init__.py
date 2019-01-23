import asyncio
import logging

from ..spi_flash_25c import SPIFlash25CInterface, SPIFlash25CApplet


class ProgramICE40FlashInterface:
    def __init__(self, interface, logger, device, addr_dut_reset, addr_dut_done):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._device = device
        self._addr_dut_reset = addr_dut_reset
        self._addr_dut_done  = addr_dut_done

    async def set_reset(self, reset):
        if self._addr_dut_reset is not None:
            await self._device.write_register(self._addr_dut_reset, int(reset))

    async def get_done(self):
        if self._addr_dut_reset is not None:
            return await self._device.read_register(self._addr_dut_done)


class ProgramICE40FlashApplet(SPIFlash25CApplet, name='program-ice40-flash'):
    logger = logging.getLogger(__name__)
    help = "program the 25C-compatible Flash memories on iCE40 FPGAs boards"
    description = """
    Program the 25C-compatible Flash memories found on many iCE40 FPGAs boards.
    This is very similar to the spi_flash applet but also controls the fpga
    reset pin and monitors the cdone line
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_argument(parser, "reset")
        access.add_pin_argument(parser, "done")

    def build(self, target, args):
        subtarget = super().build(target, args)

        if args.pin_reset is not None:
            reset_t = self.mux_interface.get_pin(args.pin_reset)
            dut_reset, self.__addr_dut_reset = target.registers.add_rw(1)
            subtarget.comb += [
                reset_t.o.eq(0),
                reset_t.oe.eq(dut_reset),
            ]
        else:
            self.__addr_dut_reset = None

        if args.pin_done is not None:
            done_t = self.mux_interface.get_pin(args.pin_done)
            dut_done, self.__addr_dut_done = target.registers.add_ro(1)
            subtarget.comb += [
                dut_done.eq(done_t.i),
            ]
        else:
            self.__addr_dut_done = None

        return subtarget

    async def run(self, device, args):
        flash_iface = await self.run_lower(ProgramICE40FlashApplet, device, args)
        return ProgramICE40FlashInterface(flash_iface, self.logger, device,
                                          self.__addr_dut_reset, self.__addr_dut_done)

    async def interact(self, device, args, ice40_iface):
        await ice40_iface.set_reset(True)
        await super().interact(device, args, ice40_iface.lower)
        await ice40_iface.set_reset(False)

        if args.pin_done is not None:
            for retry in range(200):    # Wait up to 2s
                await asyncio.sleep(0.010)  # Poll every 10 ms
                done = await ice40_iface.get_done()
                if done:
                    break
            if done:
                self.logger.info("FPGA configured from flash")
            else:
                self.logger.warning("FPGA failed to configure after releasing reset")
