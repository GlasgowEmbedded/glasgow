from .....database.microchip.avr import *
from .... import *
from . import ProgramAVRSPIApplet


class ProgramAVRSPIAppletTestCase(GlasgowAppletTestCase, applet=ProgramAVRSPIApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    # Device used for testing: ATmega32U4
    hardware_args = ["-V", "3.3"]
    dut_signature = (0x1e, 0x95, 0x87)
    dut_device = devices_by_signature[dut_signature]
    dut_gold_fuses = (0b11111111, 0b00011000, 0b11001011)
    dut_test_fuses = (0b00000000, 0b11000111, 0b11110100)

    async def setup_programming(self, mode):
        avr_iface = await self.run_hardware_applet(mode)
        if mode == "record":
            await avr_iface.programming_enable()
        return avr_iface

    @applet_hardware_test(setup="setup_programming", args=hardware_args)
    async def test_api_signature(self, avr_iface):
        signature = await avr_iface.read_signature()
        self.assertEqual(signature, self.dut_signature)

    @applet_hardware_test(setup="setup_programming", args=hardware_args)
    async def test_api_calibration(self, avr_iface):
        calibration = await avr_iface.read_calibration_range(
            range(self.dut_device.calibration_size))
        # could be anything, really

    @applet_hardware_test(setup="setup_programming", args=hardware_args)
    async def test_api_fuses(self, avr_iface):
        for index, gold_fuse, test_fuse in \
                zip(range(self.dut_device.fuses_size), self.dut_gold_fuses, self.dut_test_fuses):
            # program
            await avr_iface.write_fuse(index, test_fuse)
            # verify
            fuse = await avr_iface.read_fuse(index)
            self.assertEqual(fuse, test_fuse)
            # revert
            await avr_iface.write_fuse(index, gold_fuse)
            # verify
            fuse = await avr_iface.read_fuse(index)
            self.assertEqual(fuse, gold_fuse)

    @applet_hardware_test(setup="setup_programming", args=hardware_args)
    async def test_api_lock_bits(self, avr_iface):
        # erase
        await avr_iface.chip_erase()
        # verify
        lock_bits = await avr_iface.read_lock_bits()
        self.assertEqual(lock_bits, 0xff)
        # program
        await avr_iface.write_lock_bits(0b11111110)
        # verify
        lock_bits = await avr_iface.read_lock_bits()
        self.assertEqual(lock_bits, 0xfe)

    @applet_hardware_test(setup="setup_programming", args=hardware_args)
    async def test_api_program_memory(self, avr_iface):
        page = self.dut_device.program_page
        # erase
        await avr_iface.chip_erase()
        # program
        await avr_iface.write_program_memory_range(
            page // 2, [n for n in range(page)], page)
        # verify
        data = await avr_iface.read_program_memory_range(range(page * 2))
        self.assertEqual(data,
            b"\xff" * (page // 2) + bytes([n for n in range(page)]) + b"\xff" * (page // 2))

    @applet_hardware_test(setup="setup_programming", args=hardware_args)
    async def test_api_eeprom(self, avr_iface):
        page = self.dut_device.eeprom_page
        # erase
        await avr_iface.write_eeprom_range(
            0, b"\xff" * page * 2, page)
        # program
        await avr_iface.write_eeprom_range(
            page // 2, [n for n in range(page)], page)
        # verify
        data = await avr_iface.read_eeprom_range(range(page * 2))
        self.assertEqual(data,
            b"\xff" * (page // 2) + bytes([n for n in range(page)]) + b"\xff" * (page // 2))
