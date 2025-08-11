import asyncio

from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_hardware_test
from . import SensorSCD30Applet


class SensorSCD30AppletTestCase(GlasgowAppletV2TestCase, applet=SensorSCD30Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    @applet_v2_hardware_test(mocks=["scd30_iface._i2c_iface"], args=["-V", "3.3"])
    async def test_scd30(self, applet: SensorSCD30Applet):
        await applet.scd30_iface.firmware_version()

        await applet.scd30_iface.get_auto_self_calibration()
        await applet.scd30_iface.get_forced_calibration()
        await applet.scd30_iface.get_temperature_offset()
        await applet.scd30_iface.get_altitude_compensation()
        await applet.scd30_iface.get_measurement_interval()

        await applet.scd30_iface.start_measurement(1000)
        while not await applet.scd30_iface.is_data_ready():
            await asyncio.sleep(1.0)
        await applet.scd30_iface.read_measurement()
        await applet.scd30_iface.stop_measurement()
