from amaranth import *

from glasgow.applet import GlasgowAppletV2TestCase, applet_v2_hardware_test, synthesis_test
from . import SensorMAX31855Applet, MAX31855Fault


class SensorMAX31855AppletTestCase(GlasgowAppletV2TestCase, applet=SensorMAX31855Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    @applet_v2_hardware_test(mocks=["max31855_iface._spi_iface"], args=["-V", "3.3"])
    async def test_sample_pos(self, applet: SensorMAX31855Applet):
        sample = await applet.max31855_iface.sample()
        # self.assertEqual(sample.value, 26.75)

    @applet_v2_hardware_test(mocks=["max31855_iface._spi_iface"], args=["-V", "3.3"])
    async def test_sample_neg(self, applet: SensorMAX31855Applet):
        sample = await applet.max31855_iface.sample()
        self.assertEqual(sample.value, -6.5)

    @applet_v2_hardware_test(mocks=["max31855_iface._spi_iface"], args=["-V", "3.3"])
    async def test_fault_open(self, applet: SensorMAX31855Applet):
        sample = await applet.max31855_iface.sample()
        self.assertEqual(sample.fault, MAX31855Fault.Open)

    @applet_v2_hardware_test(mocks=["max31855_iface._spi_iface"], args=["-V", "3.3"])
    async def test_fault_short_gnd(self, applet: SensorMAX31855Applet):
        sample = await applet.max31855_iface.sample()
        self.assertEqual(sample.fault, MAX31855Fault.ShortGND)

    @applet_v2_hardware_test(mocks=["max31855_iface._spi_iface"], args=["-V", "3.3"])
    async def test_fault_short_vcc(self, applet: SensorMAX31855Applet):
        sample = await applet.max31855_iface.sample()
        self.assertEqual(sample.fault, MAX31855Fault.ShortVCC)
