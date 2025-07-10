from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_hardware_test
from . import SensorBMx280Applet


class SensorBMx280AppletTestCase(GlasgowAppletV2TestCase, applet=SensorBMx280Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    @applet_v2_hardware_test(mocks=["bmx280_iface._i2c_iface"], args=["-V", "3.3"])
    async def test_bmp280(self, applet: SensorBMx280Applet):
        await applet.bmx280_iface.reset()
        ident = await applet.bmx280_iface.identify()
        self.assertEqual(ident, "BMP280")

        await applet.bmx280_iface.set_mode("sleep")
        await applet.bmx280_iface.set_iir_coefficient(2)
        await applet.bmx280_iface.set_oversample(ovs_t=8, ovs_p=8)

        await applet.bmx280_iface.set_mode("force")
        await applet.bmx280_iface.get_temperature()
        await applet.bmx280_iface.get_pressure()
        await applet.bmx280_iface.get_altitude()

    @applet_v2_hardware_test(mocks=["bmx280_iface._i2c_iface"], args=["-V", "3.3"])
    async def test_bme280(self, applet: SensorBMx280Applet):
        await applet.bmx280_iface.reset()
        ident = await applet.bmx280_iface.identify()
        self.assertEqual(ident, "BME280")

        await applet.bmx280_iface.set_mode("sleep")
        await applet.bmx280_iface.set_iir_coefficient(2)
        await applet.bmx280_iface.set_oversample(ovs_t=8, ovs_p=8, ovs_h=8)

        await applet.bmx280_iface.set_mode("force")
        await applet.bmx280_iface.get_temperature()
        await applet.bmx280_iface.get_pressure()
        await applet.bmx280_iface.get_altitude()
        await applet.bmx280_iface.get_humidity()
