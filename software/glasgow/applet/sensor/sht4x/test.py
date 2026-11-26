from contextlib import redirect_stdout
from io import StringIO

from glasgow.applet import GlasgowAppletV2TestCase, applet_v2_hardware_test, synthesis_test
from . import SHT4xError, SensorSHT4xApplet


class SensorSHT4xAppletTestCase(GlasgowAppletV2TestCase, applet=SensorSHT4xApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    @applet_v2_hardware_test(mocks=["sht4x_iface.i2c_iface"], args=["-V", "3.3"])
    async def test_measure(self, applet: SensorSHT4xApplet):
        sample = await applet.sht4x_iface.measure()
        self.assertAlmostEqual(sample.temp_degC, 25.0)
        self.assertAlmostEqual(sample.rh_pct, 56.50095, places=5)

        sample = await applet.sht4x_iface.measure("medium")
        self.assertEqual(sample.rh_pct, 0.0)

        sample = await applet.sht4x_iface.measure("low")
        self.assertEqual(sample.rh_pct, 100.0)

    @applet_v2_hardware_test(mocks=["sht4x_iface.i2c_iface"],
                             args=["-V", "3.3", "--i2c-address", "0x46"])
    async def test_serial_number(self, applet: SensorSHT4xApplet):
        args = self._parse_args(["serial-number"], mode="run")
        with redirect_stdout(StringIO()) as output:
            await applet.run(args)
        self.assertEqual(output.getvalue(), "00ef1234\n")

    def test_log_interval(self):
        self.assertEqual(self._parse_args(["log", "stdout"], mode="run").interval, 1.0)
        args = self._parse_args(["log", "--interval", "5", "stdout"], mode="run")
        self.assertEqual(args.interval, 5.0)

    @applet_v2_hardware_test(mocks=["sht4x_iface.i2c_iface"], args=["-V", "3.3"])
    async def test_bad_crc(self, applet: SensorSHT4xApplet):
        for index in (0, 1):
            with self.subTest(word=index), self.assertRaisesRegex(SHT4xError, f"word {index}"):
                await applet.sht4x_iface.measure()

    @applet_v2_hardware_test(mocks=["sht4x_iface.i2c_iface"], args=["-V", "3.3"])
    async def test_heat(self, applet: SensorSHT4xApplet):
        for power in (20, 110, 200):
            for duration in (0.1, 1.0):
                with self.subTest(power=power, duration=duration):
                    if power == 20 and duration == 0.1:
                        sample = await applet.sht4x_iface.heat()
                    else:
                        sample = await applet.sht4x_iface.heat(power, duration)
                    self.assertAlmostEqual(sample.temp_degC, 25.0)
                    self.assertAlmostEqual(sample.rh_pct, 56.50095, places=5)

    @applet_v2_hardware_test(mocks=["sht4x_iface.i2c_iface"],
                             args=["-V", "3.3", "--i2c-address", "0x45"])
    async def test_soft_reset(self, applet: SensorSHT4xApplet):
        await applet.sht4x_iface.soft_reset()
