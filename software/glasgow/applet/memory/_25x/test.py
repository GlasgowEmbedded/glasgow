import unittest

from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_hardware_test
from . import Memory25xApplet


class Memory25xAppletTestCase(GlasgowAppletV2TestCase, applet=Memory25xApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    # Flash used for testing: Winbond 25Q32FV
    hardware_args = "-V 3.3 --sck A0 --io A1:4 --cs A5"
    dut_ids = (0xef, 0x15, 0x4016)
    dut_page_size   = 0x100
    dut_sector_size = 0x1000
    dut_block_size  = 0x10000

    async def prepare_flash_data(self, applet):
        await applet.m25x_iface.write_enable()
        await applet.m25x_iface.sector_erase(0)
        await applet.m25x_iface.write_enable()
        await applet.m25x_iface.page_program(0, b"Hello, world!")
        await applet.m25x_iface.write_enable()
        await applet.m25x_iface.sector_erase(self.dut_sector_size)
        await applet.m25x_iface.write_enable()
        await applet.m25x_iface.page_program(self.dut_sector_size, b"Some more data")
        await applet.m25x_iface.write_enable()
        await applet.m25x_iface.sector_erase(self.dut_block_size)
        await applet.m25x_iface.write_enable()
        await applet.m25x_iface.page_program(self.dut_block_size, b"One block later")

    @applet_v2_hardware_test(args=hardware_args, mock="m25x_iface.qspi")
    async def test_api_sleep_wake(self, applet):
        await applet.m25x_iface.wakeup()
        await applet.m25x_iface.deep_sleep()

    @applet_v2_hardware_test(args=hardware_args, mock="m25x_iface.qspi")
    async def test_api_device_ids(self, applet):
        self.assertEqual(await applet.m25x_iface.read_device_id(),
                         (self.dut_ids[1],))
        self.assertEqual(await applet.m25x_iface.read_manufacturer_device_id(),
                         (self.dut_ids[0], self.dut_ids[1]))
        self.assertEqual(await applet.m25x_iface.read_manufacturer_long_device_id(),
                         (self.dut_ids[0], self.dut_ids[2]))

    @applet_v2_hardware_test(prepare=prepare_flash_data, args=hardware_args, mock="m25x_iface.qspi")
    async def test_api_read(self, applet):
        self.assertEqual(await applet.m25x_iface.read(0, 13),
                         b"Hello, world!")
        self.assertEqual(await applet.m25x_iface.read(self.dut_sector_size, 14),
                         b"Some more data")

    @applet_v2_hardware_test(prepare=prepare_flash_data, args=hardware_args, mock="m25x_iface.qspi")
    async def test_api_fast_read(self, applet):
        self.assertEqual(await applet.m25x_iface.fast_read(0, 13),
                         b"Hello, world!")
        self.assertEqual(await applet.m25x_iface.fast_read(self.dut_sector_size, 14),
                         b"Some more data")

    @applet_v2_hardware_test(prepare=prepare_flash_data, args=hardware_args, mock="m25x_iface.qspi")
    async def test_api_sector_erase(self, applet):
        await applet.m25x_iface.write_enable()
        await applet.m25x_iface.sector_erase(0)
        self.assertEqual(await applet.m25x_iface.read(0, 16),
                         b"\xff" * 16)
        self.assertEqual(await applet.m25x_iface.read(self.dut_sector_size, 14),
                         b"Some more data")
        await applet.m25x_iface.write_enable()
        await applet.m25x_iface.sector_erase(self.dut_sector_size)
        self.assertEqual(await applet.m25x_iface.read(self.dut_sector_size, 16),
                         b"\xff" * 16)

    @applet_v2_hardware_test(prepare=prepare_flash_data, args=hardware_args, mock="m25x_iface.qspi")
    async def test_api_block_erase(self, applet):
        await applet.m25x_iface.write_enable()
        await applet.m25x_iface.block_erase(0)
        self.assertEqual(await applet.m25x_iface.read(0, 16),
                         b"\xff" * 16)
        self.assertEqual(await applet.m25x_iface.read(self.dut_sector_size, 16),
                         b"\xff" * 16)
        self.assertEqual(await applet.m25x_iface.read(self.dut_block_size, 15),
                         b"One block later")
        await applet.m25x_iface.write_enable()
        await applet.m25x_iface.block_erase(self.dut_block_size)
        self.assertEqual(await applet.m25x_iface.read(self.dut_block_size, 16),
                         b"\xff" * 16)

    @applet_v2_hardware_test(prepare=prepare_flash_data, args=hardware_args, mock="m25x_iface.qspi")
    async def test_api_chip_erase(self, applet):
        await applet.m25x_iface.write_enable()
        await applet.m25x_iface.chip_erase()
        self.assertEqual(await applet.m25x_iface.read(0, 16),
                         b"\xff" * 16)
        self.assertEqual(await applet.m25x_iface.read(self.dut_sector_size, 16),
                         b"\xff" * 16)
        self.assertEqual(await applet.m25x_iface.read(self.dut_block_size, 16),
                         b"\xff" * 16)

    @applet_v2_hardware_test(prepare=prepare_flash_data, args=hardware_args, mock="m25x_iface.qspi")
    async def test_api_page_program(self, applet):
        await applet.m25x_iface.write_enable()
        await applet.m25x_iface.page_program(self.dut_page_size * 2, b"test")
        self.assertEqual(await applet.m25x_iface.read(self.dut_page_size * 2, 4),
                         b"test")

    @applet_v2_hardware_test(prepare=prepare_flash_data, args=hardware_args, mock="m25x_iface.qspi")
    async def test_api_program(self, applet):
        # crosses the page boundary
        await applet.m25x_iface.write_enable()
        await applet.m25x_iface.program(self.dut_page_size * 2 - 6, b"before/after", page_size=0x100)
        self.assertEqual(await applet.m25x_iface.read(self.dut_page_size * 2 - 6, 12),
                         b"before/after")

    @applet_v2_hardware_test(prepare=prepare_flash_data, args=hardware_args, mock="m25x_iface.qspi")
    async def test_api_erase_program(self, applet):
        await applet.m25x_iface.write_enable()
        await applet.m25x_iface.erase_program(0, b"Bye  ",
            page_size=0x100, sector_size=self.dut_sector_size)
        self.assertEqual(await applet.m25x_iface.read(0, 13),
                         b"Bye  , world!")
