import logging
import asyncio
from nmigen import *
from nmigen.build.plat import ResourceError

from ... import *


class SelfTestSubtarget(Elaboratable):
    def __init__(self, applet, target):
        self.reg_oe_a, applet.addr_oe_a = target.registers.add_rw(8)
        self.reg_o_a,  applet.addr_o_a  = target.registers.add_rw(8)
        self.reg_i_a,  applet.addr_i_a  = target.registers.add_ro(8)

        self.reg_oe_b, applet.addr_oe_b = target.registers.add_rw(8)
        self.reg_o_b,  applet.addr_o_b  = target.registers.add_rw(8)
        self.reg_i_b,  applet.addr_i_b  = target.registers.add_ro(8)

        self.pins_a = [target.platform.request("port_a", n) for n in range(8)]
        self.pins_b = [target.platform.request("port_b", n) for n in range(8)]
        try:
            self.leds = [target.platform.request("led", n) for n in range(5)]
        except ResourceError:
            self.leds = []

    def elaborate(self, platform):
        m = Module()

        m.d.comb += [pin.oe.eq(pin.io.oe) for pin in self.pins_a if hasattr(pin, "oe")]
        m.d.comb += [pin.oe.eq(pin.io.oe) for pin in self.pins_b if hasattr(pin, "oe")]
        m.d.comb += [led.eq(1) for led in self.leds]

        m.d.comb += [
            Cat(pin.io.oe for pin in self.pins_a).eq(self.reg_oe_a),
            Cat(pin.io.o for pin in self.pins_a).eq(self.reg_o_a),
            self.reg_i_a.eq(Cat(pin.io.i for pin in self.pins_a))
        ]

        m.d.comb += [
            Cat(pin.io.oe for pin in self.pins_b).eq(self.reg_oe_b),
            Cat(pin.io.o for pin in self.pins_b).eq(self.reg_o_b),
            self.reg_i_b.eq(Cat(pin.io.i for pin in self.pins_b))
        ]

        return m


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
        * pins-pull: detects faults in pull resistor circuits
          (all pins on all I/O connectors must be floating)
        * pins-loop: detect faults anywhere in the I/O ciruits
          (pins A0:A7 must be connected to B0:B7)
        * voltage: detect ADC, DAC or LDO faults
          (on all ports, Vsense and Vio pins must be connected)
        * loopback: detect faults in USB FIFO traces
          (no requirements)
    """

    __all_modes = ["pins-int", "pins-ext", "pins-pull", "pins-loop", "voltage", "loopback"]
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

        async def set_pull(bits_o, bits_oe):
            pull_low  = {x for x in range(16) if bits_oe & (1 << x) and not bits_o & (1 << x)}
            pull_high = {x for x in range(16) if bits_oe & (1 << x) and     bits_o & (1 << x)}
            await device.set_pulls("AB", pull_low, pull_high)

        async def get_i():
            return ((await device.read_register(self.addr_i_a) << 0) |
                    (await device.read_register(self.addr_i_b) << 8))

        async def reset_pins(bits):
            await set_o(bits)
            await set_oe(0xffff)
            await asyncio.sleep(0.001)
            await set_oe(0x0000)

        async def check_pins(oe, o, use_pull):
            if use_pull:
                await set_pull(o, oe)
            else:
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

            if mode in ("pins-int", "pins-ext", "pins-pull"):
                if device.revision >= "C0":
                    raise GlasgowAppletError(f"mode {mode} is broken on device revision "
                                             f"{device.revision}")

                if mode == "pins-int":
                    await device.set_voltage("AB", 0)

                    # disable the IO-buffers (FXMA108) on revAB to not influence the external ports
                    # no effect on other revisions
                    await device._iobuf_enable(False)
                elif mode in ("pins-ext", "pins-pull"):
                    await device.set_voltage("AB", 3.3)

                    # re-enable the IO-buffers (FXMA108) on revAB
                    # no effect on other revisions
                    await device._iobuf_enable(True)
                use_pull = (mode == "pins-pull")

                for bits in (0x0000, 0xffff):
                    await reset_pins(bits)
                    i, desc = await check_pins(bits, bits, use_pull=use_pull)
                    self.logger.debug("%s: %s", mode, desc)
                    if bits == 0x0000:
                        fail_high = decode_pins(i)
                    if bits == 0xffff:
                        fail_low  = decode_pins(~i)

                shorted = []
                for bit in range(0, 16):
                    await reset_pins(bits=0x0000)
                    i, desc = await check_pins(1 << bit, 1 << bit, use_pull=use_pull)
                    self.logger.debug("%s: %s", mode, desc)

                    if i != 1 << bit:
                        pins = decode_pins(i) - fail_high
                        if len(pins) > 1 and pins not in shorted:
                            shorted.append(pins)
                        passed = False

                if fail_high:
                    report.append((mode, "fail high: {}".format(" ".join(sorted(fail_high)))))
                if fail_low:
                    report.append((mode, "fail low: {}".format(" ".join(sorted(fail_low)))))
                for pins in shorted:
                    report.append((mode, "fail short: {}".format(" ".join(sorted(pins)))))

                await device.set_voltage("AB", 0)

                # re-enable the IO-buffers (FXMA108) on revAB, they are on by default
                # no effect on other revisions
                await device._iobuf_enable(True)

            if mode == "pins-loop":
                await device.set_voltage("AB", 3.3)

                broken = []
                for bit in range(0, 8):
                    for o in (1 << bit, 1 << (15 - bit)):
                        await reset_pins(bits=0x0000)
                        i, desc = await check_pins(o, o, use_pull=False)
                        self.logger.debug("%s: %s", mode, desc)

                        e = ((o << 8) | o) if (o & 0xFF) else (o | (o >> 8))
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

                    await device.set_voltage(port, 0)

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
