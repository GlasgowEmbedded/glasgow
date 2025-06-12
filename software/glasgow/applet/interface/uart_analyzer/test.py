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

        self.assertEqual(("rx", ord("R")), await applet.uart_analyzer_iface.capture())
        self.assertEqual(("tx", ord("t")), await applet.uart_analyzer_iface.capture())
        self.assertEqual(("rx", ord("X")), await applet.uart_analyzer_iface.capture())
        self.assertEqual(("tx", ord("x")), await applet.uart_analyzer_iface.capture())

        await self.rx_uart.set_baud(30000)
        await self.rx_uart.write(b"U")
        self.assertEqual(("rx", 0xC7),
                         await applet.uart_analyzer_iface.capture())
        self.assertEqual(("rx", UARTAnalyzerError.Frame),
                         await applet.uart_analyzer_iface.capture())
        self.assertEqual(("rx", 0xC3),
                         await applet.uart_analyzer_iface.capture())
