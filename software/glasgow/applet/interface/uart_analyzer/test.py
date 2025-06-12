import logging

from glasgow.applet.interface.uart import UARTInterface
from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test

from . import UARTAnalyzerError, UARTAnalyzerApplet


class UARTAnalyzerAppletTestCase(GlasgowAppletV2TestCase, applet=UARTAnalyzerApplet):
    logger = logging.getLogger(__name__)

    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    def loopback_prepare(self, assembly):
        self.rx_uart = UARTInterface(self.logger, assembly, rx="A2", tx="A3")
        self.tx_uart = UARTInterface(self.logger, assembly, rx="A4", tx="A5")
        assembly.connect_pins("A0", "A3")
        assembly.connect_pins("A1", "A5")

    @applet_v2_simulation_test(prepare=loopback_prepare, args="--rx A0 --tx A1 -b 100000")
    async def test_loopback(self, applet, ctx):
        await self.rx_uart.set_baud(100000)
        await self.tx_uart.set_baud(100000)

        await self.rx_uart.write(b"RX")
        await ctx.tick().repeat(20)
        await self.tx_uart.write(b"tx")

        await ctx.tick().repeat(500)
        self.assertEqual(await applet.uart_analyzer_iface.capture(), [
            ("rx", b"R"),
            ("tx", b"t"),
            ("rx", b"X"),
            ("tx", b"x"),
        ])

        await self.rx_uart.set_baud(30000)
        await self.rx_uart.write(b"U")

        await ctx.tick().repeat(500)
        self.assertEqual(await applet.uart_analyzer_iface.capture(), [
            ("rx", b"\xC7"),
            ("rx", UARTAnalyzerError.Frame),
            ("rx", b"\xC3"),
        ])
