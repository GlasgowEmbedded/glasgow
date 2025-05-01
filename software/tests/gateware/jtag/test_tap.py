import functools
import unittest

from amaranth import *
from amaranth.sim import Simulator

from glasgow.gateware.jtag import tap


async def shift_tms(ctx, dut, tms, state_after, *, expected={}):
    ctx.set(dut.tms.i, tms)

    # HACK(bin): i'm so sorry?
    (_, _, *sampled) = await ctx.tick("jtag").sample(*[getattr(dut, s).o for s in expected.keys()])
    assert ctx.get(dut.state == state_after)

    for (dut_value, (name, expected_value)) in zip(sampled, expected.items()):
        assert dut_value == expected_value, f"dut.{name} != {expected_value:#b}"


class TAPTestCase(unittest.TestCase):
    def test_tap_controller(self):
        ir_idcode = 0b10101010
        dr_idcode = 0b0011_1111000011110000_00001010100_1

        m = Module()
        m.submodules.dut = dut = tap.Controller(ir_length=8, ir_idcode=ir_idcode)
        m.d.comb += dut.dr_idcode.cap.eq(dr_idcode)

        async def testbench(ctx):
            global shift_tms
            shift_tms = functools.partial(shift_tms, ctx, dut)

            assert ctx.get(dut.state) == tap.State.Test_Logic_Reset

            await shift_tms(0, tap.State.Run_Test_Idle)
            await shift_tms(1, tap.State.Select_DR_Scan)
            await shift_tms(0, tap.State.Capture_DR)
            await shift_tms(0, tap.State.Shift_DR)

            for i in range(32):
                await shift_tms(0, tap.State.Shift_DR, expected={
                    "tdo": (dr_idcode >> i) & 1
                })

            await shift_tms(1, tap.State.Exit1_DR)
            await shift_tms(0, tap.State.Pause_DR)
            await shift_tms(1, tap.State.Exit2_DR)
            await shift_tms(1, tap.State.Update_DR)
            await shift_tms(1, tap.State.Select_DR_Scan)
            await shift_tms(1, tap.State.Select_IR_Scan)

            ctx.set(dut.ir_cap, 0b111111)
            await shift_tms(0, tap.State.Capture_IR)
            await shift_tms(0, tap.State.Shift_IR)
            await shift_tms(0, tap.State.Shift_IR, expected={
                "tdo": 0b1
            })
            await shift_tms(1, tap.State.Exit1_IR, expected={
                "tdo": 0b0
            })
            await shift_tms(0, tap.State.Pause_IR)
            await shift_tms(1, tap.State.Exit2_IR)
            await shift_tms(1, tap.State.Update_IR)
            await shift_tms(1, tap.State.Select_DR_Scan)
            assert ctx.get(dut.ir_upd) == 0b111111

            await shift_tms(1, tap.State.Select_IR_Scan)
            await shift_tms(1, tap.State.Test_Logic_Reset)

            await shift_tms(1, tap.State.Test_Logic_Reset)
            assert ctx.get(dut.ir_upd) == ir_idcode

        sim = Simulator(m)
        sim.add_clock(1e-3, domain="jtag")
        sim.add_testbench(testbench)
        with sim.write_vcd("test_tap.vcd"):
            sim.run()
