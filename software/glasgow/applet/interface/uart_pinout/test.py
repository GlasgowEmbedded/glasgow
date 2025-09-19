from amaranth import Elaboratable, Module
from glasgow.gateware.uart import ExternalUART
from glasgow.simulation.assembly import SimulationAssembly
from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from glasgow.applet.interface.uart_pinout import UARTPinoutApplet, UARTPinoutInterface


class UARTPinoutAppletTestCase(GlasgowAppletV2TestCase, applet=UARTPinoutApplet):

    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--pins", "A0:3"])

    def test_run(self):

        assembly = SimulationAssembly()

        pins = "A0:5"
        baud = 115200
        baud_ticks = round((1.0 / baud) / assembly.sys_clk_period)

        iface = UARTPinoutInterface(assembly._logger, assembly, pins=pins)

        # Echo will just send RX to TX at 115200 baud.
        class Echo(Elaboratable):
            def elaborate(self, platform):
                m = Module()
                # Use B0 and B1 for the ports, we'll forward ports in A to them
                # appropriately.
                uart = ExternalUART(
                    ports=assembly.add_port_group(rx="B0", tx="B1"),
                    bit_cyc=baud.bit_length(),
                )
                m.submodules.test_uart = uart

                b0 = assembly.get_pin("B0")
                a5 = assembly.get_pin("A5")

                b1 = assembly.get_pin("B1")
                a3 = assembly.get_pin("A3")

                m.d.comb += uart.bit_cyc.eq(baud_ticks)

                # B0 == A5
                m.d.comb += b0.i.eq((a5.o & a5.oe) | (~a5.oe))

                # A3 == B1
                m.d.comb += a3.i.eq((b1.o & b1.oe) | (~b1.oe))

                # TX == RX
                m.d.comb += uart.tx_data.eq(uart.rx_data)

                with m.If(uart.rx_rdy):
                    m.d.comb += uart.tx_ack.eq(1)
                    m.d.comb += uart.rx_ack.eq(1)

                return m

        assembly.add_submodule(Echo())

        async def testbench(ctx):

            # Set all test pins high since UARTs idle high, ignore A3 because
            # we're driving that elsewhere.
            for i in range(6):
                if i == 3:
                    continue
                pin = f"A{i}"
                pin = assembly.get_pin(pin)
                ctx.set(pin.i, 1)

            data = bytes.fromhex("0FF00FF0")

            await iface._rnstopbits.set(1)
            iface.set_data(data)
            # No need for a big delay with the test
            iface.set_rx_delay_ms(1)
            await iface.set_baud(baud)

            await iface.set_tx_pin(0)
            await iface.set_rx_pin(1)
            result = await iface.transact()
            assert result is None, f"expected None got {result.hex()}"

            # Correct tx, but wrong rx
            await iface.set_tx_pin(5)
            result = await iface.transact()
            assert result is None, f"expected None got {result.hex()}"

            # Correct rx, but wrong tx
            await iface.set_tx_pin(2)
            await iface.set_rx_pin(3)
            result = await iface.transact()
            assert result is None, f"expected None got {result.hex()}"

            # Both correct
            await iface.set_tx_pin(5)
            await iface.set_rx_pin(3)
            result = await iface.transact()
            assert result == data, f"expected {data.hex()} got {result.hex()}"

            # Cases with correct pins but incorrect bauds
            await iface.set_tx_pin(5)
            await iface.set_rx_pin(3)

            # Wrong baud (half) but correct pins
            await iface.set_baud(int(baud / 2))
            result = await iface.transact()
            expected = bytes.fromhex("F0F0")
            assert result == expected, f"expected {expected.hex()} got {result.hex()}"

            # Wrong baud (double) but correct pins
            await iface.set_baud(baud * 2)
            result = await iface.transact()
            expected = bytes.fromhex("F000")
            assert result == expected, f"expected {expected.hex()} got {result.hex()}"

        assembly.run(testbench, vcd_file="test_uart_pinout_run.vcd")
