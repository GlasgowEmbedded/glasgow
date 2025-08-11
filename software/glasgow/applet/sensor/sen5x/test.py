import asyncio

from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_hardware_test
from . import SensorSEN5xApplet


class SensorSEN5xAppletTestCase(GlasgowAppletV2TestCase, applet=SensorSEN5xApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    @applet_v2_hardware_test(mocks=["sen5x_iface._i2c_iface"], args=["-V", "3.3"])
    async def test_sen5x(self, applet: SensorSEN5xApplet):
        await applet.sen5x_iface.product_name()
        await applet.sen5x_iface.serial_number()
        await applet.sen5x_iface.firmware_version()

        await applet.sen5x_iface.start_measurement()
        while not await applet.sen5x_iface.is_data_ready():
            await asyncio.sleep(1.0)
        sample = await applet.sen5x_iface.read_measurement()
        await applet.sen5x_iface.stop_measurement()
