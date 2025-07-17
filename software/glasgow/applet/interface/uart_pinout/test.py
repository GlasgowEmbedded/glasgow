from amaranth import Elaboratable, Module
from amaranth.lib.io import SimulationPort
from glasgow.gateware.uart import UART, ExternalUART
from glasgow.simulation.assembly import SimulationAssembly
from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test
from glasgow.applet.interface.uart_pinout import HostCommunication, UARTPinoutApplet, _Command, _Status, UARTPinoutInterface


class UARTPinoutAppletTestCase(GlasgowAppletV2TestCase, applet=UARTPinoutApplet):

    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--pins", "A0:3"])

    def test_hostcomm(self):

        assembly = SimulationAssembly()

        pin_values = SimulationPort("i", 2)
        dut = HostCommunication(pin_values.i, 32)
        component = assembly.add_submodule(dut)
        pipe = assembly.add_inout_pipe(component.o_stream, component.i_stream)

        async def tk(ctx, count):
            await ctx.tick().repeat(count)

        async def send_cmd(cmd, *args):
            msg = [cmd.value]
            if args:
                msg.extend(args)
            await pipe.send(bytearray(msg))
            await pipe.flush()

        async def pipe_get(expected):
            assert pipe.readable >= 1, f"expected at least one byte but had {pipe.readable}"
            res = (await pipe.recv(1))[0]
            if expected is not None:
                assert res == expected, f"expected {hex(expected)} but got {hex(res)}"
            return res

        async def get_status(stat):
            await pipe_get(stat.value)

        async def testbench(ctx):
            await send_cmd(_Command.SetData, 2, 0x0d, 0x0a)
            await tk(ctx, 3)
            await get_status(_Status.OK)

            await send_cmd(_Command.Start)
            await ctx.tick()
            await get_status(_Status.OK)

            ctx.set(dut.i_rx_data, 0xCAFEC0D3)
            ctx.set(dut.i_rx_data_len, 4)
            ctx.set(dut.i_rx_data_valid, 1)
            await ctx.tick()
            ctx.set(dut.i_rx_data_valid, 0)
            await ctx.tick().repeat(2)
            await pipe_get(4)
            await ctx.tick()
            await pipe_get(0xD3)
            await ctx.tick()
            await pipe_get(0xC0)
            await ctx.tick()
            await pipe_get(0xFE)
            await ctx.tick()
            await pipe_get(0xCA)
            await ctx.tick()
            assert ctx.get(dut.o_stream.valid) == 0, "expected ostream to not be valid anymore"

        assembly.run(testbench, vcd_file="test_uart_probe_hostcomm.vcd")


    def test_main_component(self):

        assembly = SimulationAssembly()

        pins = "A0:5"
        baud = 115200
        baud_ticks = round((1.0 / baud) / assembly.sys_clk_period)

        iface = UARTPinoutInterface(assembly._logger, assembly, pins=pins, max_databits=32)

        class Pump(Elaboratable):
            def elaborate(self, platform):
                m = Module()
                uart = ExternalUART(ports=assembly.add_port_group(rx="B0", tx="B1"), bit_cyc=baud.bit_length())
                m.submodules.test_uart = uart

                b0 = assembly.get_pin("B0")
                a5 = assembly.get_pin("A5")

                b1 = assembly.get_pin("B1")
                a3 = assembly.get_pin("A3")

                m.d.comb += uart.bit_cyc.eq(baud_ticks)
                m.d.comb += b0.i.eq((a5.o & a5.oe) | (~a5.oe))
                m.d.comb += a3.i.eq((b1.o & b1.oe) | (~b1.oe))

                m.d.comb += uart.tx_data.eq(uart.rx_data)

                with m.If(uart.rx_rdy):
                    m.d.comb += uart.tx_ack.eq(1)
                    m.d.comb += uart.rx_ack.eq(1)

                return m

        assembly.add_submodule(Pump())

        async def testbench(ctx):

            for i in range(6):
                if i == 3:
                    continue
                pin = f"A{i}"
                pin = assembly.get_pin(pin)
                ctx.set(pin.i, 1)

            data = bytes.fromhex("0FF00FF0")


            await iface._rnstopbits.set(1)
            #await iface._rparity.set(_Parity.NoParity.value)
            await iface.set_data(data)
            await iface.set_baud(baud)
            await iface.set_abs_delay_ms(1)

            await iface.set_tx_pin(0)
            await iface.set_rx_pin(1)
            await iface.start()
            result = await iface.get_rx_result()
            assert result is None, f"expected None got {result.hex()}"

            # Correct tx, but wrong rx
            await iface.set_tx_pin(5)
            await iface.start()
            result = await iface.get_rx_result()
            assert result is None, f"expected None got {result.hex()}"

            # Correct rx, but wrong tx
            await iface.set_tx_pin(2)
            await iface.set_rx_pin(3)
            await iface.start()
            result = await iface.get_rx_result()
            assert result is None, f"expected None got {result.hex()}"

            # Both correct
            await iface.set_tx_pin(5)
            await iface.set_rx_pin(3)
            await iface.start()
            result = await iface.get_rx_result()
            assert result == data, f"expected {data.hex()} got {result.hex()}"

            # Cases with correct pins but incorrect bauds
            await iface.set_tx_pin(5)
            await iface.set_rx_pin(3)

            # Wrong baud (half) but correct pins
            await iface.set_baud(int(baud/2))
            await iface.start()
            result = await iface.get_rx_result()
            expected = bytes.fromhex("F0F0")
            assert result == expected, f"expected {expected.hex()} got {result.hex()}"

            # Wrong baud (double) but correct pins
            await iface.set_baud(baud*2)
            await iface.start()
            result = await iface.get_rx_result()
            expected = bytes.fromhex("F000")
            assert result == expected, f"expected {expected.hex()} got {result.hex()}"

        assembly.run(testbench, vcd_file="test_uart_main.vcd")

