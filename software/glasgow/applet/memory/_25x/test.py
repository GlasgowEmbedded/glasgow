import unittest

from ... import *
from . import Memory25xApplet


class Memory25xAppletTestCase(GlasgowAppletTestCase, applet=Memory25xApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--pin-sck",  "0", "--pin-cs",   "1",
                                "--pin-copi", "2", "--pin-cipo", "3"])

    # Flash used for testing: Winbond 25Q32BVSIG
    hardware_args = [
        "--voltage",  "3.3",
        "--pin-cs",   "0", "--pin-cipo", "1",
        "--pin-copi", "2", "--pin-sck",  "3",
        "--pin-hold", "4"
    ]
    dut_ids = (0xef, 0x15, 0x4016)
    dut_page_size   = 0x100
    dut_sector_size = 0x1000
    dut_block_size  = 0x10000

    async def setup_flash_data(self, mode):
        m25x_iface = await self.run_hardware_applet(mode)
        if mode == "record":
            await m25x_iface.write_enable()
            await m25x_iface.sector_erase(0)
            await m25x_iface.write_enable()
            await m25x_iface.page_program(0, b"Hello, world!")
            await m25x_iface.write_enable()
            await m25x_iface.sector_erase(self.dut_sector_size)
            await m25x_iface.write_enable()
            await m25x_iface.page_program(self.dut_sector_size, b"Some more data")
            await m25x_iface.write_enable()
            await m25x_iface.sector_erase(self.dut_block_size)
            await m25x_iface.write_enable()
            await m25x_iface.page_program(self.dut_block_size, b"One block later")
        return m25x_iface

    @applet_hardware_test(args=hardware_args)
    async def test_api_sleep_wake(self, m25x_iface):
        await m25x_iface.wakeup()
        await m25x_iface.deep_sleep()

    @applet_hardware_test(args=hardware_args)
    async def test_api_device_ids(self, m25x_iface):
        self.assertEqual(await m25x_iface.read_device_id(),
                         (self.dut_ids[1],))
        self.assertEqual(await m25x_iface.read_manufacturer_device_id(),
                         (self.dut_ids[0], self.dut_ids[1]))
        self.assertEqual(await m25x_iface.read_manufacturer_long_device_id(),
                         (self.dut_ids[0], self.dut_ids[2]))

    @applet_hardware_test(setup="setup_flash_data", args=hardware_args)
    async def test_api_read(self, m25x_iface):
        self.assertEqual(await m25x_iface.read(0, 13),
                         b"Hello, world!")
        self.assertEqual(await m25x_iface.read(self.dut_sector_size, 14),
                         b"Some more data")

    @applet_hardware_test(setup="setup_flash_data", args=hardware_args)
    async def test_api_fast_read(self, m25x_iface):
        self.assertEqual(await m25x_iface.fast_read(0, 13),
                         b"Hello, world!")
        self.assertEqual(await m25x_iface.fast_read(self.dut_sector_size, 14),
                         b"Some more data")

    @applet_hardware_test(setup="setup_flash_data", args=hardware_args)
    async def test_api_sector_erase(self, m25x_iface):
        await m25x_iface.write_enable()
        await m25x_iface.sector_erase(0)
        self.assertEqual(await m25x_iface.read(0, 16),
                         b"\xff" * 16)
        self.assertEqual(await m25x_iface.read(self.dut_sector_size, 14),
                         b"Some more data")
        await m25x_iface.write_enable()
        await m25x_iface.sector_erase(self.dut_sector_size)
        self.assertEqual(await m25x_iface.read(self.dut_sector_size, 16),
                         b"\xff" * 16)

    @applet_hardware_test(setup="setup_flash_data", args=hardware_args)
    async def test_api_block_erase(self, m25x_iface):
        await m25x_iface.write_enable()
        await m25x_iface.block_erase(0)
        self.assertEqual(await m25x_iface.read(0, 16),
                         b"\xff" * 16)
        self.assertEqual(await m25x_iface.read(self.dut_sector_size, 16),
                         b"\xff" * 16)
        self.assertEqual(await m25x_iface.read(self.dut_block_size, 15),
                         b"One block later")
        await m25x_iface.write_enable()
        await m25x_iface.block_erase(self.dut_block_size)
        self.assertEqual(await m25x_iface.read(self.dut_block_size, 16),
                         b"\xff" * 16)

    @applet_hardware_test(setup="setup_flash_data", args=hardware_args)
    async def test_api_chip_erase(self, m25x_iface):
        await m25x_iface.write_enable()
        await m25x_iface.chip_erase()
        self.assertEqual(await m25x_iface.read(0, 16),
                         b"\xff" * 16)
        self.assertEqual(await m25x_iface.read(self.dut_sector_size, 16),
                         b"\xff" * 16)
        self.assertEqual(await m25x_iface.read(self.dut_block_size, 16),
                         b"\xff" * 16)

    @applet_hardware_test(setup="setup_flash_data", args=hardware_args)
    async def test_api_page_program(self, m25x_iface):
        await m25x_iface.write_enable()
        await m25x_iface.page_program(self.dut_page_size * 2, b"test")
        self.assertEqual(await m25x_iface.read(self.dut_page_size * 2, 4),
                         b"test")

    @applet_hardware_test(setup="setup_flash_data", args=hardware_args)
    async def test_api_program(self, m25x_iface):
        # crosses the page boundary
        await m25x_iface.write_enable()
        await m25x_iface.program(self.dut_page_size * 2 - 6, b"before/after", page_size=0x100)
        self.assertEqual(await m25x_iface.read(self.dut_page_size * 2 - 6, 12),
                         b"before/after")

    @unittest.skip("seems broken??")
    @applet_hardware_test(setup="setup_flash_data", args=hardware_args)
    async def test_api_erase_program(self, m25x_iface):
        await m25x_iface.write_enable()
        await m25x_iface.erase_program(0, b"Bye  ",
            page_size=0x100, sector_size=self.dut_sector_size)
        self.assertEqual(await m25x_iface.read(0, 14),
                         b"Bye  , world!")
