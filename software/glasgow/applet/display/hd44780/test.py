from amaranth.lib import io
from amaranth.sim import Simulator

from glasgow.gateware.ports import PortGroup
from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_hardware_test
from . import DisplayHD44780Applet, HD44780Component


class DisplayHD44780AppletTestCase(GlasgowAppletV2TestCase, applet=DisplayHD44780Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    # Fixtures are authored protocol expectations, not captures from a physical display.
    # To re-record, connect a compatible display using the default pin assignments and 5 V I/O.
    hardware_args = "-V 5"
    hardware_mocks = ["hd44780_interface._pipe"]

    @applet_v2_hardware_test(args=hardware_args, mocks=hardware_mocks)
    async def test_initialize(self, applet: DisplayHD44780Applet):
        iface = applet.hd44780_interface
        await iface.initialize()

    @applet_v2_hardware_test(args=hardware_args, mocks=hardware_mocks)
    async def test_reinitialize(self, applet: DisplayHD44780Applet):
        iface = applet.hd44780_interface
        await iface.initialize()
        await iface.use_two_display_lines()
        await iface.use_5x10_font()
        await iface.display_on()
        await iface.cursor_on()
        await iface.display_shift_on()
        await iface.initialize()
        await iface.cursor_on()
        await iface.display_shift_off()
        await iface.set_cursor_position(position=41, line_no=1)

    @applet_v2_hardware_test(args=hardware_args, mocks=hardware_mocks)
    async def test_display_modes(self, applet: DisplayHD44780Applet):
        iface = applet.hd44780_interface
        await iface.initialize()
        await iface.display_on()
        await iface.cursor_on()
        await iface.cursor_blink_on()
        await iface.display_off()
        await iface.cursor_off()
        await iface.cursor_blink_off()
        await iface.display_shift_on()
        await iface.decrement_cursor()
        await iface.display_shift_off()
        await iface.increment_cursor()
        await iface.use_two_display_lines()
        await iface.use_5x10_font()
        await iface.use_one_display_line()
        await iface.use_5x7_font()

    @applet_v2_hardware_test(args=hardware_args, mocks=hardware_mocks)
    async def test_cursor_position(self, applet: DisplayHD44780Applet):
        iface = applet.hd44780_interface
        await iface.initialize()
        await iface.set_cursor_position(position=80)
        await iface.set_cursor_position(position=-1)
        await iface.use_two_display_lines()
        await iface.set_cursor_position(position=3, line_no=1)
        await iface.set_cursor_position(position=43, line_no=0)
        await iface.set_cursor_position(position=40, line_no=5)
        await iface.set_cursor_position(position=0, line_no=-1)
        await iface.shift_cursor_left()
        await iface.shift_cursor_right()
        await iface.shift_display_and_cursor_left()
        await iface.shift_display_right()
        await iface.home()
        await iface.clear_display()

    @applet_v2_hardware_test(args=hardware_args, mocks=hardware_mocks)
    async def test_write(self, applet: DisplayHD44780Applet):
        iface = applet.hd44780_interface
        await iface.initialize()
        await iface.write_text("Hi")
        await iface.write_bytes(b"\x00\xef")
        await iface.write_bytes(b"")
        with self.assertRaises(UnicodeEncodeError):
            await iface.write_text("ö")
        await iface.home()

    @applet_v2_hardware_test(args=hardware_args, mocks=hardware_mocks)
    async def test_custom_characters(self, applet: DisplayHD44780Applet):
        iface = applet.hd44780_interface
        await iface.initialize()
        await iface.define_cg_ram_char(1, bytes(range(10)))
        await iface.define_cg_ram_char(8, b"\x1f")
        await iface.use_5x10_font()
        await iface.define_cg_ram_char(3, bytes(range(18)))
        await iface.define_cg_ram_char(4, b"\x00")
        await iface.set_cursor_position()
        await iface.write_bytes(b"\x00")

    def test_bus_write(self):
        ports = PortGroup(rs=io.SimulationPort("o", 1), rw=io.SimulationPort("o", 1),
                          e=io.SimulationPort("o", 1), d=io.SimulationPort("io", 4))
        dut = HD44780Component(ports=ports, sys_clk_period=1e-6)
        writes = []

        async def monitor(ctx):
            last_e = 0
            while True:
                _, _, e, rs, rw, data = await ctx.tick().sample(
                    ports.e.o, ports.rs.o, ports.rw.o, ports.d.o)
                if last_e and not e:
                    writes.append((rs, rw, data))
                last_e = e

        async def testbench(ctx):
            # Half-byte initialization, a wait, then a full data byte.
            for byte in (0x04, 0x03, 0x08, 0x01, 0x41):
                ctx.set(dut.i_stream.payload, byte)
                ctx.set(dut.i_stream.valid, 1)
                for _ in range(2000):
                    _, _, ready = await ctx.tick().sample(dut.i_stream.ready)
                    if ready:
                        break
                else:
                    self.fail("command stream stalled")
            ctx.set(dut.i_stream.valid, 0)
            await ctx.tick().repeat(30)
            self.assertEqual(writes, [(0, 0, 3), (1, 0, 4), (1, 0, 1)])

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(monitor, background=True)
        sim.add_testbench(testbench)
        sim.run()
