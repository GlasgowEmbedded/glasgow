from amaranth import *
from amaranth.lib import io

from glasgow.gateware.ports import PortGroup
from glasgow.gateware.i2c import I2CTarget
from glasgow.simulation.assembly import SimulationAssembly
from glasgow.applet import GlasgowAppletV2TestCase, synthesis_test, applet_v2_simulation_test
from . import I2CNotAcknowledged, I2CControllerApplet


class I2CControllerAppletTestCase(GlasgowAppletV2TestCase, applet=I2CControllerApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    def prepare_target(self, assembly: SimulationAssembly):
        ctl_ports = PortGroup(
            scl=assembly.get_pin("A0"),
            sda=assembly.get_pin("A1")
        )
        tgt_ports = PortGroup(
            scl=io.SimulationPort("io", 1),
            sda=io.SimulationPort("io", 1),
        )

        m = Module()
        m.submodules.tgt = tgt = self.tgt = I2CTarget(tgt_ports)
        m.d.comb += [
            ctl_ports.scl.i.eq(~(ctl_ports.scl.oe | tgt_ports.scl.oe)),
            tgt_ports.scl.i.eq(~(ctl_ports.scl.oe | tgt_ports.scl.oe)),
            ctl_ports.sda.i.eq(~(ctl_ports.sda.oe | tgt_ports.sda.oe)),
            tgt_ports.sda.i.eq(~(ctl_ports.sda.oe | tgt_ports.sda.oe)),
        ]

        self.i2c_events = []
        self.i2c_reads  = []
        self.i2c_acks   = []
        async def testbench(ctx):
            ctx.set(tgt.address, 0x50)
            async for _ in ctx.tick():
                if ctx.get(tgt.start):
                    self.i2c_events.append("S")
                if ctx.get(tgt.restart):
                    self.i2c_events.append("Sr")
                if ctx.get(tgt.stop):
                    self.i2c_events.append("P")
                if ctx.get(tgt.write):
                    self.i2c_events.append("W")
                    self.i2c_events.append(ctx.get(tgt.data_i))
                    ctx.set(tgt.ack_o, self.i2c_acks[0])
                    del self.i2c_acks[0]
                if ctx.get(tgt.read):
                    self.i2c_events.append("R")
                    ctx.set(tgt.data_o, self.i2c_reads[0])
                    del self.i2c_reads[0]

        assembly.add_submodule(m)
        assembly.add_testbench(testbench, background=True)

    @applet_v2_simulation_test(prepare=prepare_target)
    async def test_addr_ack(self, applet: I2CControllerApplet, ctx):
        await applet.i2c_iface.write(0x50, b"")
        self.assertEqual(self.i2c_events, ['S', 'P'])

    @applet_v2_simulation_test(prepare=prepare_target)
    async def test_addr_nak(self, applet: I2CControllerApplet, ctx):
        try:
            await applet.i2c_iface.write(0x51, b"")
            self.fail("expected NAK")
        except I2CNotAcknowledged:
            pass
        self.assertEqual(self.i2c_events, [])

    @applet_v2_simulation_test(prepare=prepare_target)
    async def test_write_ack(self, applet: I2CControllerApplet, ctx):
        self.i2c_acks = [1, 1, 1]
        await applet.i2c_iface.write(0x50, b"abc")
        self.assertEqual(self.i2c_events, ['S', 'W', 97, 'W', 98, 'W', 99, 'P'])

    @applet_v2_simulation_test(prepare=prepare_target)
    async def test_write_nak(self, applet: I2CControllerApplet, ctx):
        self.i2c_acks = [1, 0]
        try:
            await applet.i2c_iface.write(0x50, [0x12, 0x34])
            self.fail("expected NAK")
        except I2CNotAcknowledged:
            pass
        self.assertEqual(self.i2c_events, ['S', 'W', 0x12, 'W', 0x34, 'P'])

    @applet_v2_simulation_test(prepare=prepare_target)
    async def test_read(self, applet: I2CControllerApplet, ctx):
        self.i2c_reads = [0x12, 0x34]
        data = await applet.i2c_iface.read(0x50, 2)
        self.assertEqual(data, bytes([0x12, 0x34]))
        self.assertEqual(self.i2c_events, ['S', 'R', 'R', 'P'])

    @applet_v2_simulation_test(prepare=prepare_target)
    async def test_trans_ack(self, applet: I2CControllerApplet, ctx):
        self.i2c_reads = [0x12, 0x34]
        self.i2c_acks = [1]
        async with applet.i2c_iface.transaction():
            await applet.i2c_iface.write(0x50, [0xaa])
            data = await applet.i2c_iface.read(0x50, 2)
        self.assertEqual(data, bytes([0x12, 0x34]))
        self.assertEqual(self.i2c_events, ['S', 'W', 0xaa, 'Sr', 'S', 'R', 'R', 'P'])

    @applet_v2_simulation_test(prepare=prepare_target)
    async def test_trans_nak(self, applet: I2CControllerApplet, ctx):
        self.i2c_acks = [1, 0]
        try:
            async with applet.i2c_iface.transaction():
                await applet.i2c_iface.write(0x50, [0x55])
                await applet.i2c_iface.write(0x50, [0xaa])
            self.fail("expected NAK")
        except I2CNotAcknowledged:
            pass
        self.assertEqual(self.i2c_events, ['S', 'W', 0x55, 'Sr', 'S', 'W', 0xaa, 'P'])

    @applet_v2_simulation_test(prepare=prepare_target)
    async def test_ping_ack(self, applet: I2CControllerApplet, ctx):
        self.assertTrue(await applet.i2c_iface.ping(0x50))
        self.assertEqual(self.i2c_events, ['S', 'P'])

    @applet_v2_simulation_test(prepare=prepare_target)
    async def test_ping_nak(self, applet: I2CControllerApplet, ctx):
        self.assertFalse(await applet.i2c_iface.ping(0x51))
        self.assertEqual(self.i2c_events, [])

    @applet_v2_simulation_test(prepare=prepare_target)
    async def test_scan(self, applet: I2CControllerApplet, ctx):
        self.assertEqual(await applet.i2c_iface.scan(), {0x50})
        self.assertEqual(self.i2c_events, ['S', 'P'])

    @applet_v2_simulation_test(prepare=prepare_target)
    async def test_scan_range(self, applet: I2CControllerApplet, ctx):
        self.assertEqual(await applet.i2c_iface.scan(range(0x20, 0x30)), set())
        self.assertEqual(self.i2c_events, [])

    @applet_v2_simulation_test(prepare=prepare_target)
    async def test_device_id(self, applet: I2CControllerApplet, ctx):
        ctx.set(self.tgt.address, 0b1111_100)
        self.i2c_reads = [0xab, 0xc1, 0x25]
        self.i2c_acks = [1]
        device_id = await applet.i2c_iface.device_id(0x50)
        self.assertEqual(device_id, (0xabc, 0x24, 0x5))
        self.assertEqual(self.i2c_events, ['S', 'W', 0x50, 'Sr', 'S', 'R', 'R', 'R', 'P'])
