import unittest

from amaranth import *
from amaranth.sim import Simulator
from amaranth.lib import io, wiring

from glasgow.gateware.ports import PortGroup
from glasgow.gateware.jtag import probe as jtag_probe, tap as jtag_tap


def bits(*args):
    return sum(bit * (1 << place) for place, bit in enumerate(args))


async def stream_get(ctx, stream):
    ctx.set(stream.ready, 1)
    payload, = await ctx.tick().sample(stream.payload).until(stream.valid)
    ctx.set(stream.ready, 0)
    return payload


async def stream_put(ctx, stream, payload):
    ctx.set(stream.payload, payload)
    ctx.set(stream.valid, 1)
    await ctx.tick().until(stream.ready)
    ctx.set(stream.valid, 0)


class TAPToplevel(Elaboratable):
    def __init__(self, ports):
        self._ports = ports

    def elaborate(self, platform):
        m = Module()

        m.domains.jtag = ClockDomain(async_reset=True)

        if hasattr(self._ports, "trst"):
            m.submodules.trst_buffer = trst_buffer = io.Buffer("i", self._ports.trst)
            m.submodules.trst_sync = cdc.ResetSynchronizer(trst_buffer.i, domain="jtag")

        m.submodules.tck_buffer = tck_buffer = io.Buffer("i", self._ports.tck)
        m.submodules.tms_buffer = tms_buffer = io.Buffer("i", self._ports.tms)
        m.submodules.tdi_buffer = tdi_buffer = io.Buffer("i", self._ports.tdi)
        m.submodules.tdo_buffer = tdo_buffer = io.Buffer("o", self._ports.tdo)

        m.submodules.ctrl = ctrl = jtag_tap.Controller(ir_length=2, ir_idcode=0b00)
        m.d.comb += ctrl.dr_idcode.cap.eq(0b0011_1111000011110000_00001010100_1)

        m.d.comb += ClockSignal("jtag").eq(tck_buffer.i)
        wiring.connect(m, ctrl.tms, tms_buffer)
        wiring.connect(m, ctrl.tdi, tdi_buffer)
        wiring.connect(m, ctrl.tdo, tdo_buffer)

        return m


class ProbeTestCase(unittest.TestCase):
    def test_probe_controller(self):
        ports = PortGroup()
        ports.tck = io.SimulationPort("o", 1, name="tck")
        ports.tms = io.SimulationPort("o", 1, name="tms")
        ports.tdi = io.SimulationPort("o", 1, name="tdi")
        ports.tdo = io.SimulationPort("i", 1, name="tdo")

        dut = jtag_probe.Controller(ports, width=32)

        async def i_testbench(ctx):
            await stream_put(ctx, dut.i_words,
                {"mode": jtag_probe.Mode.ShiftTMS, "data": 0b11101, "size": 5})
            await stream_put(ctx, dut.i_words,
                {"mode": jtag_probe.Mode.ShiftTDI, "data": 0b11110000111100001111000011110000, "size": 32})
            await stream_put(ctx, dut.i_words,
                {"mode": jtag_probe.Mode.ShiftTDIO, "size": 8})

        async def o_testbench(ctx):
            await stream_get(ctx, dut.o_words)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(i_testbench)
        sim.add_testbench(o_testbench)
        with sim.write_vcd("test_probe_controller.vcd"):
            sim.run()

    def test_probe_integration(self):
        tap_ports = PortGroup()
        tap_ports.tck = io.SimulationPort("i", 1, name="tck")
        tap_ports.tms = io.SimulationPort("i", 1, name="tms")
        tap_ports.tdi = io.SimulationPort("i", 1, name="tdi")
        tap_ports.tdo = io.SimulationPort("o", 1, name="tdo")

        probe_ports = PortGroup()
        probe_ports.tck = io.SimulationPort("o", 1, name="tck")
        probe_ports.tms = io.SimulationPort("o", 1, name="tms")
        probe_ports.tdi = io.SimulationPort("o", 1, name="tdi")
        probe_ports.tdo = io.SimulationPort("i", 1, name="tdo")

        m = Module()
        m.submodules.tap   = tap   = TAPToplevel(tap_ports)
        m.submodules.probe = probe = jtag_probe.Controller(probe_ports, width=32)
        m.d.comb += [
            tap_ports.tck.i.eq(probe_ports.tck.o),
            tap_ports.tms.i.eq(probe_ports.tms.o),
            tap_ports.tdi.i.eq(probe_ports.tdi.o),
            probe_ports.tdo.i.eq(tap_ports.tdo.o),
        ]

        async def i_testbench(ctx):
            await stream_put(ctx, probe.i_words,
                {"mode": jtag_probe.Mode.ShiftTMS,  "size": 5, "data": bits(0,1,1,0,0)})
            await stream_put(ctx, probe.i_words,
                {"mode": jtag_probe.Mode.ShiftTDIO, "size": 2, "data": bits(0,0), "last": 1})
            await stream_put(ctx, probe.i_words,
                {"mode": jtag_probe.Mode.ShiftTMS,  "size": 5, "data": bits(1,0,1,0,0)})
            await stream_put(ctx, probe.i_words,
                {"mode": jtag_probe.Mode.ShiftTDIO, "size": 32, "last": 1})
            await stream_put(ctx, probe.i_words,
                {"mode": jtag_probe.Mode.ShiftTMS,  "size": 5, "data": bits(1,0)})

        async def o_testbench(ctx):
            assert await stream_get(ctx, probe.o_words) == {
                "size": 2, "data": 0b01
            }
            assert await stream_get(ctx, probe.o_words) == {
                "size": 32, "data": 0b0011_1111000011110000_00001010100_1
            }

        sim = Simulator(m)
        sim.add_clock(1e-6)
        sim.add_testbench(i_testbench)
        sim.add_testbench(o_testbench)
        with sim.write_vcd("test_probe_integration.vcd"):
            sim.run()
