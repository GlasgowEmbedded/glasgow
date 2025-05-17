import os
import unittest

from amaranth import *
from amaranth.sim import Simulator
from amaranth.lib import io, wiring

from .....gateware.ports import PortGroup
from .....gateware.stream import stream_get, stream_put
from .....hardware.assembly import HardwareAssembly
from .... import *
from . import DebugARM7Applet, DebugARM7Sequencer


class DebugARM7AppletTestCase(GlasgowAppletV2TestCase, applet=DebugARM7Applet):
    # DUT used for testing: Yamaha SWLL (from PSS-A50 keyboard)
    hardware_args = "-e big -V A=3.30,B=5.00 --tck A1 --tms A3 --tdi A2 --tdo A4 --trst A0"
    ram_addr = 0x2ff00

    def test_sequencer(self):
        ports = PortGroup()
        ports.tck  = io.SimulationPort("o", 1, name="tck")
        ports.tms  = io.SimulationPort("o", 1, name="tms")
        ports.tdi  = io.SimulationPort("o", 1, name="tdi")
        ports.tdo  = io.SimulationPort("i", 1, name="tdo")
        ports.trst = None

        dut = DebugARM7Sequencer(ports)

        async def i_testbench(ctx):
            await stream_put(ctx, dut.i_stream, 0xe0)

        async def o_testbench(ctx):
            for _ in range(4):
                await stream_get(ctx, dut.o_stream)

        sim = Simulator(dut)
        sim.add_clock(1e-6)
        sim.add_testbench(i_testbench)
        sim.add_testbench(o_testbench)
        with sim.write_vcd("test_debug_arm7_sequencer.vcd"):
            sim.run()

    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    @unittest.skipUnless("DEBUG_ARM7_HARDWARE_TEST" in os.environ, "hardware unavailable")
    def test_enter_exit_arm(self):
        self.run_on_hardware(self.do_test_enter_exit, is_thumb=False)

    @unittest.skipUnless("DEBUG_ARM7_HARDWARE_TEST" in os.environ, "hardware unavailable")
    def test_enter_exit_thumb(self):
        self.run_on_hardware(self.do_test_enter_exit, is_thumb=True)

    async def do_test_enter_exit(self, iface, *, is_thumb):
        """ARM7TDMI has a very finicky debug state entry/exit procedure where you can easily lose
        track of PC. This test verifies that the PC is correct on both entry and exit.

        Running this test requires ARM7TDMI hardware, so it is disabled by default. You will need
        to adjust `hardware_args` above to match your connections, as well as `ram_addr` to point
        at any RWX region in the target's address space.
        """

        await iface._debug_request()
        await iface._debug_enter()
        ctx = iface._context
        # print(ctx)

        async with iface.queue() as txn:
            txn.a_ldr(12, self.ram_addr)
            if is_thumb:
                txn.a_ldr(1, 0x30013001)      # adds r0, #1
            else:
                txn.a_ldr(1, 0xe2800001)      # add  r0, r0, #1
            txn.a_stm_sys(12, 0x2, w=1) # 00
            txn.a_stm_sys(12, 0x2, w=1) # 04
            txn.a_stm_sys(12, 0x2, w=1) # 08
            txn.a_stm_sys(12, 0x2, w=1) # 0c
            txn.a_stm_sys(12, 0x2, w=1) # 10
            txn.a_stm_sys(12, 0x2, w=1) # 14
            txn.a_stm_sys(12, 0x2, w=1) # 18
            if is_thumb:
                txn.a_ldr(1, 0xe7fee7fe)      # b .
            else:
                txn.a_ldr(1, 0xeafffffe)      # b .
            txn.a_stm_sys(12, 0x2, w=1) # 1c
            txn.a_stm_sys(12, 0x2, w=1) # 20
            txn.a_stm_sys(12, 0x2, w=1) # 24
            txn.a_stm_sys(12, 0x2, w=1) # 28
            txn.a_stm_sys(12, 0x2, w=1) # 2c
            txn.a_stm_sys(12, 0x2, w=1) # 30
            txn.a_stm_sys(12, 0x2, w=1) # 34
            txn.a_stm_sys(12, 0x2, w=1) # 38
            txn.a_stm_sys(12, 0x2, w=1) # 3c
            txn.a_stm_sys(12, 0x2, w=1) # 40

            txn.a_ldr(12, self.ram_addr)
            txn.a_ldm_sys(12, 0xff, w=1)
            regs = txn.a_stm(12, 0xff)
        if is_thumb:
            assert list(regs) == [0x30013001] * 7 + [0xe7fee7fe]
        else:
            assert list(regs) == [0xe2800001] * 7 + [0xeafffffe]

        ctx.r0   = 0x10000
        ctx.r15  = self.ram_addr
        ctx.cpsr = 0x400000d0 | (0x20 if is_thumb else 0)
        await iface._debug_exit()

        for _ in range(3):
            await iface._debug_request()
            await iface._debug_enter()
            ctx = iface._context
            # print(ctx)

            expected_r15  = self.ram_addr + 0x1c
            if is_thumb:
                expected_r0   = 0x1000e
                expected_cpsr = 0x400000f0
            else:
                expected_r0   = 0x10007
                expected_cpsr = 0x400000d0
            assert ctx.r0   == expected_r0, \
                f"expected r0 to be {expected_r0:08x}, it is {ctx.r0:08x}"
            assert ctx.r15  == expected_r15, \
                f"expected r15 to be {expected_r15:08x}, it is {ctx.r15:08x}"
            assert ctx.cpsr == expected_cpsr, \
                f"expected cpsr to be {expected_cpsr:08x}, it is {ctx.cpsr:08x}"

            await iface._debug_exit()

    @unittest.skipUnless("DEBUG_ARM7_HARDWARE_TEST" in os.environ, "hardware unavailable")
    def test_breakpoints(self):
        self.run_on_hardware(self.do_test_breakpoints)

    async def do_test_breakpoints(self, iface):
        await iface.target_stop()
        await iface.target_write_memory(
            self.ram_addr,
            # 00000000  e2800001   add     r0, r0, #1
            # ...
            # 0000003c  e2800001   add     r0, r0, #1
            # 00000040  e28f1001   adr     r1, #0x49
            # 00000044  e12fff11   bx      r1
            # 00000048  1c40       adds    r0, r0, #1
            # ...
            # 00000066  1c40       adds    r0, r0, #1
            # 00000068  e7fe       b       .
            bytes.fromhex(
                "e2800001e2800001e2800001e2800001e2800001e2800001e2800001e2800001"
                "e2800001e2800001e2800001e2800001e2800001e2800001e2800001e2800001"
                "e28f1001e12fff111c401c401c401c401c401c401c401c401c401c401c401c40"
                "1c401c401c401c40e7fe0000"
            )
        )
        iface.target_context.r0   = 0
        iface.target_context.r15  = self.ram_addr
        iface.target_context.cpsr = 0x400000d3

        def assert_r0_r15(r0, r15_off):
            assert iface.target_context.r0  == r0, \
                f"r0 != {r0:08x}\n{iface.target_context}"
            assert iface.target_context.r15 == self.ram_addr + r15_off, \
                f"r15 != {self.ram_addr:08x}+{r15_off:02x}\n{iface.target_context}"

        await iface.target_set_instr_breakpt(self.ram_addr, 4)
        await iface.target_continue()
        assert_r0_r15(0x00, 0x00)
        await iface.target_clear_instr_breakpt(self.ram_addr, 4)

        await iface.target_single_step()
        assert_r0_r15(0x01, 0x04)

        await iface.target_single_step()
        assert_r0_r15(0x02, 0x08)

        await iface.target_single_step()
        assert_r0_r15(0x03, 0x0c)

        await iface.target_set_instr_breakpt(self.ram_addr + 0x10, 4)
        await iface.target_continue()
        assert_r0_r15(0x04, 0x10)
        await iface.target_clear_instr_breakpt(self.ram_addr + 0x10, 4)

        await iface.target_set_software_breakpt(self.ram_addr + 0x18, 4)
        await iface.target_set_instr_breakpt(self.ram_addr + 0x1c, 4)
        await iface.target_continue()
        assert_r0_r15(0x06, 0x18)
        await iface.target_clear_software_breakpt(self.ram_addr + 0x18, 4)
        await iface.target_set_software_breakpt(self.ram_addr + 0x4e, 2)

        await iface.target_continue()
        assert_r0_r15(0x07, 0x1c)
        await iface.target_clear_instr_breakpt(self.ram_addr + 0x1c, 4)

        await iface.target_set_instr_breakpt(self.ram_addr + 0x48, 2)
        await iface.target_continue()
        assert_r0_r15(0x10, 0x48)
        await iface.target_clear_instr_breakpt(self.ram_addr + 0x48, 2)

        await iface.target_set_software_breakpt(self.ram_addr + 0x4a, 2)
        await iface.target_continue()
        assert_r0_r15(0x11, 0x4a)
        await iface.target_clear_software_breakpt(self.ram_addr + 0x4a, 2)

        await iface.target_single_step()
        assert_r0_r15(0x12, 0x4c)

        await iface.target_continue()
        assert_r0_r15(0x13, 0x4e)
        await iface.target_clear_software_breakpt(self.ram_addr + 0x4e, 2)
        try:
            await iface.target_clear_software_breakpt(self.ram_addr + 0x4e, 2)
        except Exception as e:
            assert "breakpoint does not exist" in str(e)

        await iface.target_single_step()
        assert_r0_r15(0x14, 0x50)

    @async_test
    async def run_on_hardware(self, test_case, **test_kwargs):
        parsed_args = self._parse_args(self.hardware_args)
        assembly = HardwareAssembly()
        applet = self.applet_cls(assembly)
        applet.build(parsed_args)
        async with assembly:
            await applet.setup(parsed_args)
            await test_case(applet.arm_iface, **test_kwargs)
