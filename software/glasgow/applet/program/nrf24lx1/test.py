from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_hardware_test
from . import ProgramNRF24Lx1Applet, _FlashStatus


class ProgramNRF24Lx1AppletTestCase(GlasgowAppletV2TestCase, applet=ProgramNRF24Lx1Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    # Device used for tests: nRF24LE1.
    hardware_args  = "-V 3.3"
    hardware_mocks = [
        "nrf24lx1_iface._spi_iface",
        "nrf24lx1_iface._prog_iface",
        "nrf24lx1_iface._reset_iface",
    ]

    async def prepare(self, applet):
        await applet.nrf24lx1_iface.reset_program()
        assert await applet.nrf24lx1_iface.check_presence()

    @applet_v2_hardware_test(prepare=prepare, args=hardware_args, mocks=hardware_mocks)
    async def test_read_info_page(self, applet: ProgramNRF24Lx1Applet):
        old_status = await applet.nrf24lx1_iface.read_status()
        await applet.nrf24lx1_iface.write_status(_FlashStatus.INFEN)
        assert (await applet.nrf24lx1_iface.read_status()) & _FlashStatus.INFEN
        info_page = await applet.nrf24lx1_iface.read(0, 0x200)
        assert info_page[0] != 0xff
        await applet.nrf24lx1_iface.write_status(old_status)

        await applet.nrf24lx1_iface.reset_application()

    @applet_v2_hardware_test(prepare=prepare, args=hardware_args, mocks=hardware_mocks)
    async def test_program_verify_page(self, applet: ProgramNRF24Lx1Applet):
        await applet.nrf24lx1_iface.write_enable()
        await applet.nrf24lx1_iface.erase_page(2)
        await applet.nrf24lx1_iface.wait_status()

        code_page = await applet.nrf24lx1_iface.read(0x400, 0x200)
        assert code_page == b"\xff" * 0x200

        await applet.nrf24lx1_iface.write_enable()
        await applet.nrf24lx1_iface.program(0x400, bytes(range(256)) * 2)
        await applet.nrf24lx1_iface.wait_status()

        code_page = await applet.nrf24lx1_iface.read(0x400, 0x200)
        assert code_page == bytes(range(256)) * 2

        await applet.nrf24lx1_iface.reset_application()
