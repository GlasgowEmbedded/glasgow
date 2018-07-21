import argparse
import logging
from migen import *

from . import GlasgowApplet


logger = logging.getLogger(__name__)


class SelfTestSubtarget(Module):
    def __init__(self, applet, registers, io_A, io_B):
        super().__init__()

        reg_oe_A, applet.addr_oe_A = registers.add_rw()
        reg_o_A,  applet.addr_o_A  = registers.add_rw()
        reg_i_A,  applet.addr_i_A  = registers.add_ro()
        self.comb += [
            io_A.oe.eq(reg_oe_A),
            io_A.o.eq(reg_o_A),
            reg_i_A.eq(io_A.i)
        ]

        reg_oe_B, applet.addr_oe_B = registers.add_rw()
        reg_o_B,  applet.addr_o_B  = registers.add_rw()
        reg_i_B,  applet.addr_i_B  = registers.add_ro()
        self.comb += [
            io_B.oe.eq(reg_oe_B),
            io_B.o.eq(reg_o_B),
            reg_i_B.eq(io_B.i)
        ]


class SelfTestApplet(GlasgowApplet, name="selftest"):
    help = "diagnose hardware faults"
    description = """
    Diagnose hardware faults.

    Currently, shorts and opens on I/O lines can be detected.

    Test modes:
        * pins-int: detect shorts on traces between FPGA and I/O buffers
          (no requirements)
        * pins-ext: detect shorts and opens on traces between FPGA and I/O connector
          (all pins on all I/O connectors must be floating)
    """
    all_modes = ["pins-int", "pins-ext"]

    def build(self, target, args):
        target.submodules += SelfTestSubtarget(
            applet=self,
            registers=target.registers,
            io_A=target.get_io_port("A"),
            io_B=target.get_io_port("B"),
        )

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument(
            "-m", "--mode", dest="modes", metavar="MODE", type=str,
            choices=cls.all_modes, nargs="+",
            help="run self-test mode MODE (default: all)")


    def run(self, device, args):
        def set_oe(bits):
            device.write_register(self.addr_oe_A, (bits >> 0) & 0xff)
            device.write_register(self.addr_oe_B, (bits >> 8) & 0xff)

        def set_o(bits):
            device.write_register(self.addr_o_A,  (bits >> 0) & 0xff)
            device.write_register(self.addr_o_B,  (bits >> 8) & 0xff)

        def get_i():
            return ((device.read_register(self.addr_i_A) << 0) |
                    (device.read_register(self.addr_i_B) << 8))

        def reset_pins(level=0):
            set_o(0xffff if level else 0x0000)
            set_oe(0xffff)
            set_oe(0x0000)

        def check_pins(oe, o):
            set_o(o)
            set_oe(oe)
            i = get_i()
            desc = "oe={:016b} o={:016b} i={:016b}".format(oe, o, i)
            return i, desc

        pin_names = sum([["%s%d" % (p, n) for n in range(8)] for p in ("A", "B")], [])
        def decode_pins(bits):
            result = set()
            for bit in range(0, 16):
                if bits & (1 << bit):
                    result.add(pin_names[bit])
            return result

        passed = True
        report = []
        for mode in (args.modes or self.all_modes):
            logger.info("running self-test mode %s", mode)

            if mode in ("pins-int", "pins-ext"):
                if mode == "pins-int":
                    device.set_voltage("AB", 0)
                    device._iobuf_enable(False)
                elif mode == "pins-ext":
                    device.set_voltage("AB", 3.3)
                    device._iobuf_enable(True)

                reset_pins(0)
                stuck_high = decode_pins(get_i())
                reset_pins(1)
                stuck_low  = decode_pins(~get_i())

                shorted = []
                for bit in range(0, 16):
                    reset_pins()
                    i, desc = check_pins(1 << bit, 1 << bit)
                    logger.debug("%s: %s", mode, desc)
                    if i != 1 << bit:
                        pins = decode_pins(i) - stuck_high
                        if len(pins) > 1 and pins not in shorted:
                            shorted.append(pins)
                        passed = False

                if stuck_high:
                    report.append((mode, "stuck high: {}".format(" ".join(stuck_high))))
                if stuck_low:
                    report.append((mode, "stuck low: {}".format(" ".join(stuck_low))))
                for pins in shorted:
                    report.append((mode, "shorted: {}".format(" ".join(pins))))

        if passed:
            logger.info("self-test: PASS")
        else:
            logger.error("self-test: FAIL")
            for (mode, message) in report:
                logger.error("%s: %s", mode, message)

        device.set_voltage("AB", 0)
        device._iobuf_enable(True)
