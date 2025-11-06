from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_hardware_test
from glasgow.database.microchip.avr import *

from . import ProgramAVRSPIApplet


class ProgramAVRSPIAppletTestCase(GlasgowAppletV2TestCase, applet=ProgramAVRSPIApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    # Device used for testing: ATmega328P
    hardware_args  = "-V 3.3"
    hardware_mocks = ["avr_iface._spi_iface", "avr_iface._reset_iface"]
    dut_signature = (0x1e, 0x95, 0x0f)
    dut_device = devices_by_signature[dut_signature]
    dut_gold_fuses = (0b11111111, 0b11011010, 0b11111101)
    dut_test_fuses = (0b11001111, 0b11000111, 0b11111000)

    async def prepare_programming(self, applet):
        await applet.avr_iface.programming_enable()

    @applet_v2_hardware_test(prepare=prepare_programming, args=hardware_args, mocks=hardware_mocks)
    async def test_api_signature(self, applet):
        signature = await applet.avr_iface.read_signature()
        self.assertEqual(signature, self.dut_signature)

    @applet_v2_hardware_test(prepare=prepare_programming, args=hardware_args, mocks=hardware_mocks)
    async def test_api_calibration(self, applet):
        calibration = await applet.avr_iface.read_calibration_range(
            range(self.dut_device.calibration_size))
        # could be anything, really

    @applet_v2_hardware_test(prepare=prepare_programming, args=hardware_args, mocks=hardware_mocks)
    async def test_api_fuses(self, applet):
        for index, gold_fuse, test_fuse in \
                zip(range(self.dut_device.fuses_size), self.dut_gold_fuses, self.dut_test_fuses):
            # program
            await applet.avr_iface.write_fuse(index, test_fuse)
            # verify
            fuse = await applet.avr_iface.read_fuse(index)
            self.assertEqual(fuse, test_fuse)
            # revert
            await applet.avr_iface.write_fuse(index, gold_fuse)
            # verify
            fuse = await applet.avr_iface.read_fuse(index)
            self.assertEqual(fuse, gold_fuse)

    @applet_v2_hardware_test(prepare=prepare_programming, args=hardware_args, mocks=hardware_mocks)
    async def test_api_lock_bits(self, applet):
        # erase
        await applet.avr_iface.chip_erase()
        # verify
        lock_bits = await applet.avr_iface.read_lock_bits()
        self.assertEqual(lock_bits, 0xff)
        # program
        await applet.avr_iface.write_lock_bits(0b11111110)
        # verify
        lock_bits = await applet.avr_iface.read_lock_bits()
        self.assertEqual(lock_bits, 0xfe)

    @applet_v2_hardware_test(prepare=prepare_programming, args=hardware_args, mocks=hardware_mocks)
    async def test_api_program_memory(self, applet):
        page = self.dut_device.program_page
        # erase
        await applet.avr_iface.chip_erase()
        # program
        await applet.avr_iface.write_program_memory_range(
            page // 2, list(range(page)), page)
        # verify
        data = await applet.avr_iface.read_program_memory_range(range(page * 2))
        self.assertEqual(data,
            b"\xff" * (page // 2) + bytes(list(range(page))) + b"\xff" * (page // 2))

    @applet_v2_hardware_test(prepare=prepare_programming, args=hardware_args, mocks=hardware_mocks)
    async def test_api_eeprom(self, applet):
        page = self.dut_device.eeprom_page
        # erase
        await applet.avr_iface.write_eeprom_range(
            0, b"\xff" * page * 2, page)
        # program
        await applet.avr_iface.write_eeprom_range(
            page // 2, list(range(page)), page)
        # verify
        data = await applet.avr_iface.read_eeprom_range(range(page * 2))
        self.assertEqual(data,
            b"\xff" * (page // 2) + bytes(list(range(page))) + b"\xff" * (page // 2))
