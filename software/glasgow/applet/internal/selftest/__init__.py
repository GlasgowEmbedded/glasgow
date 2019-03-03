import logging
import asyncio
from migen import *

from ... import *


class SelfTestSubtarget(Module):
    def __init__(self, applet, target):
        t_a  = [TSTriple() for _ in range(8)]
        t_b  = [TSTriple() for _ in range(8)]
        io_a = [target.platform.request("port_a", n) for n in range(8)]
        io_b = [target.platform.request("port_b", n) for n in range(8)]
        self.specials += [t.get_tristate(io_a[i].io) for i, t in enumerate(t_a)]
        self.specials += [t.get_tristate(io_b[i].io) for i, t in enumerate(t_b)]
        self.comb     += [io_a[i].oe.eq(t.oe) for i, t in enumerate(t_a) if hasattr(io_a[i], "oe")]
        self.comb     += [io_b[i].oe.eq(t.oe) for i, t in enumerate(t_b) if hasattr(io_b[i], "oe")]

        reg_oe_a, applet.addr_oe_a = target.registers.add_rw(8)
        reg_o_a,  applet.addr_o_a  = target.registers.add_rw(8)
        reg_i_a,  applet.addr_i_a  = target.registers.add_ro(8)
        self.comb += [
            Cat(t.oe for t in t_a).eq(reg_oe_a),
            Cat(t.o for t in t_a).eq(reg_o_a),
            reg_i_a.eq(Cat(t.i for t in t_a))
        ]

        reg_oe_b, applet.addr_oe_b = target.registers.add_rw(8)
        reg_o_b,  applet.addr_o_b  = target.registers.add_rw(8)
        reg_i_b,  applet.addr_i_b  = target.registers.add_ro(8)
        self.comb += [
            Cat(t.oe for t in t_b).eq(reg_oe_b),
            Cat(t.o for t in t_b).eq(reg_o_b),
            reg_i_b.eq(Cat(t.i for t in t_b))
        ]


class SelfTestApplet(GlasgowApplet, name="selftest"):
    logger = logging.getLogger(__name__)
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
        * loopback: detect faults in USB FIFO traces
          (no requirements)
    """

    __all_modes = ["pins-int", "pins-ext", "pins-loop", "voltage", "loopback"]
    __default_modes = ["pins-int", "loopback"]

    def build(self, target, args):
        target.submodules += SelfTestSubtarget(applet=self, target=target)

        self.mux_interface_1 = iface_1 = target.multiplexer.claim_interface(self, None)
        self.mux_interface_2 = iface_2 = target.multiplexer.claim_interface(self, None)

        in_fifo_1, out_fifo_1 = iface_1.get_inout_fifo()
        in_fifo_2, out_fifo_2 = iface_2.get_inout_fifo()
        target.comb += [
            in_fifo_1.din.eq(out_fifo_1.dout),
            in_fifo_1.we.eq(out_fifo_1.readable),
            out_fifo_1.re.eq(in_fifo_1.writable),
            in_fifo_2.din.eq(out_fifo_2.dout),
            in_fifo_2.we.eq(out_fifo_2.readable),
            out_fifo_2.re.eq(in_fifo_2.writable),
        ]

    @classmethod
    def add_run_arguments(cls, parser, access):
        parser.add_argument(
            dest="modes", metavar="MODE", type=str, nargs="*", choices=[[]] + cls.__all_modes,
            help="run self-test mode MODE (default: {})".format(" ".join(cls.__default_modes)))

    async def run(self, device, args):
        async def set_oe(bits):
            await device.write_register(self.addr_oe_a, (bits >> 0) & 0xff)
            await device.write_register(self.addr_oe_b, (bits >> 8) & 0xff)

        async def set_o(bits):
            await device.write_register(self.addr_o_a,  (bits >> 0) & 0xff)
            await device.write_register(self.addr_o_b,  (bits >> 8) & 0xff)

        async def get_i():
            return ((await device.read_register(self.addr_i_a) << 0) |
                    (await device.read_register(self.addr_i_b) << 8))

        async def reset_pins(level=0):
            await set_o(0xffff if level else 0x0000)
            await set_oe(0xffff)
            await set_oe(0x0000)

        async def check_pins(oe, o):
            await set_o(o)
            await set_oe(oe)
            i = await get_i()
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
        for mode in args.modes or self.__default_modes:
            self.logger.info("running self-test mode %s", mode)

            if mode in ("pins-int", "pins-ext"):
                if mode == "pins-int":
                    await device.set_voltage("AB", 0)
                    await device._iobuf_enable(False)
                elif mode == "pins-ext":
                    await device.set_voltage("AB", 3.3)
                    await device._iobuf_enable(True)

                await reset_pins(0)
                stuck_high = decode_pins(await get_i())
                await reset_pins(1)
                stuck_low  = decode_pins(~await get_i())

                shorted = []
                for bit in range(0, 16):
                    await reset_pins()
                    i, desc = await check_pins(1 << bit, 1 << bit)
                    self.logger.debug("%s: %s", mode, desc)

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

                await device.set_voltage("AB", 0)
                await device._iobuf_enable(True)

            if mode == "pins-loop":
                await device.set_voltage("AB", 3.3)

                broken = []
                for bit in range(0, 8):
                    for o in (1 << bit, 1 << (15 - bit)):
                        await reset_pins()
                        i, desc = await check_pins(o, o)
                        self.logger.debug("%s: %s", mode, desc)

                        e = (1 << bit) | (1 << (15 - bit))
                        if i != e:
                            passed = False
                            pins = decode_pins(i | e)
                            report.append((mode, "fault: {}".format(" ".join(pins))))
                            break

                await device.set_voltage("AB", 0)

            if mode == "voltage":
                await device.set_voltage("AB", 0)

                for port in ("A", "B"):
                    for vout in (1.8, 2.7, 3.3, 5.0):
                        await device.set_voltage(port, vout)
                        await asyncio.sleep(0.1)
                        vin = await device.measure_voltage(port)
                        self.logger.debug("port {}: Vio={:.1f} Vsense={:.2f}"
                                          .format(port, vout, vin))

                        if abs(vout - vin) / vout > 0.05:
                            passed = False
                            report.append((mode, "port {} out of ±5% tolerance: "
                                                 "Vio={:.2f} Vsense={:.2f}"
                                                 .format(port, vout, vin)))

            if mode == "loopback":
                iface_1 = await device.demultiplexer.claim_interface(
                    self, self.mux_interface_1, None)
                iface_2 = await device.demultiplexer.claim_interface(
                    self, self.mux_interface_2, None)

                data_1 = b"The quick brown fox jumps over the lazy dog.\x55\xaa"
                data_2 = bytes(reversed(data_1))

                for iface, data, ep_out, ep_in in (
                    (iface_1, data_1, "EP2OUT", "EP6IN"),
                    (iface_2, data_2, "EP4OUT", "EP8IN"),
                ):
                    try:
                        await iface.write(data)
                        await asyncio.wait_for(iface.flush(), timeout=0.1)
                    except asyncio.TimeoutError:
                        passed = False
                        report.append((mode, "USB {} timeout".format(ep_out)))
                        continue

                    try:
                        received = await asyncio.wait_for(iface.read(len(data)), timeout=0.1)
                    except asyncio.TimeoutError:
                        passed = False
                        report.append((mode, "USB {} timeout".format(ep_in)))
                        continue

                    if received != data:
                        passed = False
                        report.append((mode, "USB {}->{} read-write mismatch"
                                             .format(ep_out, ep_in)))

        if passed:
            self.logger.info("self-test: PASS")
        else:
            self.logger.error("self-test: FAIL")
            for (mode, message) in report:
                self.logger.error("%s: %s", mode, message)

# -------------------------------------------------------------------------------------------------

class SelfTestAppletTestCase(GlasgowAppletTestCase, applet=SelfTestApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
