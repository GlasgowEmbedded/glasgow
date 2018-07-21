import argparse
import logging
import time
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
        * pins-loop: detect faults anywhere in the I/O ciruits
          (pins A0:A7 must be connected to B7:B0)
        * voltage: detect ADC, DAC or LDO faults
          (on all ports, Vsense and Vio pins must be connected)
    """
    all_modes = ["pins-int", "pins-ext", "pins-loop", "voltage"]
    default_mode = "pins-int"

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
            dest="modes", metavar="MODE", type=str, nargs="*", choices=[[]] + cls.all_modes,
            help="run self-test mode MODE (default: {})".format(cls.default_mode))

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
        for mode in args.modes or [self.default_mode]:
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
                    report.append((mode, "short: {}".format(" ".join(pins))))

                device.set_voltage("AB", 0)
                device._iobuf_enable(True)

            if mode == "pins-loop":
                device.set_voltage("AB", 3.3)

                broken = []
                for bit in range(0, 8):
                    for o in (1 << bit, 1 << (15 - bit)):
                        reset_pins()
                        i, desc = check_pins(o, o)
                        logger.debug("%s: %s", mode, desc)

                        e = (1 << bit) | (1 << (15 - bit))
                        if i != e:
                            passed = False
                            pins = decode_pins(i | e)
                            report.append((mode, "fault: {}".format(" ".join(pins))))
                            break

                device.set_voltage("AB", 0)

            if mode == "voltage":
                device.set_voltage("AB", 0)

                for port in ("A", "B"):
                    for vout in (1.8, 2.7, 3.3, 5.0):
                        device.set_voltage(port, vout)
                        time.sleep(0.1)
                        vin = device.measure_voltage(port)
                        logger.debug("port {}: Vio={:.1f} Vsense={:.2f}"
                                     .format(port, vout, vin))

                        if abs(vout - vin) / vout > 0.05:
                            passed = False
                            report.append((mode, "port {} out of ±5% tolerance: "
                                                 "Vio={:.2f} Vsense={:.2f}"
                                                 .format(port, vout, vin)))

        if passed:
            logger.info("self-test: PASS")
        else:
            logger.error("self-test: FAIL")
            for (mode, message) in report:
                logger.error("%s: %s", mode, message)
