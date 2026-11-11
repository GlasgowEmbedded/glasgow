import asyncio
from amaranth import *
from amaranth.lib import io, stream, wiring
from amaranth.build.res import ResourceError

from glasgow.support import logging
from glasgow.applet import *


class SelfTestSubtarget(Elaboratable):
    def __init__(self, ports):
        self.ports = ports
        self.reg_oe_a = Signal(8)
        self.reg_o_a  = Signal(8)
        self.reg_i_a  = Signal(8)
        self.reg_oe_b = Signal(8)
        self.reg_o_b  = Signal(8)
        self.reg_i_b  = Signal(8)
        self.reg_leds = Signal(5)

    def elaborate(self, platform):
        m = Module()

        for idx, pin in enumerate(self.ports.a):
            m.submodules[f"buffer_a{idx}"] = buffer = io.Buffer("io", pin)
            m.d.comb += buffer.oe.eq(self.reg_oe_a[idx])
            m.d.comb += buffer.o.eq(self.reg_o_a[idx])
            m.d.comb += self.reg_i_a[idx].eq(buffer.i)

        for idx, pin in enumerate(self.ports.b):
            m.submodules[f"buffer_b{idx}"] = buffer = io.Buffer("io", pin)
            m.d.comb += buffer.oe.eq(self.reg_oe_b[idx])
            m.d.comb += buffer.o.eq(self.reg_o_b[idx])
            m.d.comb += self.reg_i_b[idx].eq(buffer.i)

        if platform is not None:
            try:
                leds = [platform.request("led", n) for n in range(5)]
            except ResourceError:
                leds = []
            m.d.comb += Cat(pin.o for pin in leds).eq(self.reg_leds)

        return m


class SelfTestApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "diagnose hardware faults"
    description = """
    Diagnose hardware faults.

    Currently, shorts and opens on I/O lines can be detected.

    Test modes:
        * leds: test indicator LED functionality
          (Vio will be enabled)
        * pins-int: detect shorts on traces between FPGA and I/O buffers
          (no requirements)
        * pins-ext: detect shorts and opens on traces between FPGA and I/O connector
          (all pins on all I/O connectors must be floating)
        * pins-pull: detects faults in pull resistor circuits
          (all pins on all I/O connectors must be floating)
        * pins-bufs: detects faults in I/O buffer ASICs
          (all pins on all I/O connectors must be floating)
        * pins-loop: detect faults anywhere in the I/O circuits
          (pins A0:A7 must be connected to B0:B7)
        * voltage: detect ADC, DAC or LDO faults
          (on all ports, Vsense and Vio pins must be connected)
        * loopback: detect faults in USB FIFO traces
          (no requirements)
    """

    __all_modes = [
        "leds",
        "pins-int", "pins-ext", "pins-pull", "pins-bufs", "pins-loop",
        "voltage", "loopback"
    ]
    __default_modes = ["loopback"]

    @classmethod
    def add_build_arguments(cls, parser, access):
        # Each diagnostic controls the port voltages directly.
        pass

    def build(self, args):
        with self.assembly.add_applet(self):
            component = self.assembly.add_submodule(SelfTestSubtarget(
                self.assembly.add_port_group(a="A0:7", b="B0:7")))
            self._oe_a = self.assembly.add_rw_register(component.reg_oe_a)
            self._o_a  = self.assembly.add_rw_register(component.reg_o_a)
            self._i_a  = self.assembly.add_ro_register(component.reg_i_a)
            self._oe_b = self.assembly.add_rw_register(component.reg_oe_b)
            self._o_b  = self.assembly.add_rw_register(component.reg_o_b)
            self._i_b  = self.assembly.add_ro_register(component.reg_i_b)
            self._leds = self.assembly.add_rw_register(component.reg_leds)

            self._loopback_pipes = []
            for _ in range(2):
                loopback = stream.Signature(8).create()
                self._loopback_pipes.append(
                    self.assembly.add_inout_pipe(loopback, wiring.flipped(loopback), in_flush=C(1)))

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument(
            dest="modes", metavar="MODE", type=str, nargs="*", choices=[[]] + cls.__all_modes,
            help=f"run self-test mode MODE (default: {' '.join(cls.__default_modes)})")

    async def run(self, args):
        device = self.device

        async def set_oe(bits):
            await self._oe_a.set((bits >> 0) & 0xff)
            await self._oe_b.set((bits >> 8) & 0xff)

        async def set_o(bits):
            await self._o_a.set((bits >> 0) & 0xff)
            await self._o_b.set((bits >> 8) & 0xff)

        async def set_pull(bits_o, bits_oe):
            pull_low  = {x for x in range(16) if bits_oe & (1 << x) and not bits_o & (1 << x)}
            pull_high = {x for x in range(16) if bits_oe & (1 << x) and     bits_o & (1 << x)}
            await device.set_pulls("AB", pull_low, pull_high)

        async def get_pull():
            return ((await device.get_state("A") << 0) |
                    (await device.get_state("B") << 8))

        async def get_i():
            return ((await self._i_a.get() << 0) |
                    (await self._i_b.get() << 8))

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
            desc = f"oe={oe:016b} o={o:016b} i={i:016b}"
            return i, desc

        async def check_bufs(oe, o):
            await set_o(o)
            await set_oe(oe)
            i = await get_pull()
            desc = f"oe={oe:016b} o={o:016b} i={i:016b}"
            return i, desc

        pin_names = [f"{p}{n}" for p in ("A", "B") for n in range(8)]
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

            if mode == "leds":
                self.logger.warning("power cycle the device to restore LED function")

                led_state = 0b11111111111_00000000000
                while True:
                    await device._test_leds(True,
                        (led_state & 0b1111) >> 0)
                    await self._leds.set(
                        (led_state & 0b11111_0000) >> 4)
                    await device.set_voltage("A",
                        3.3 if (led_state & 0b1_000000000) >> 9 else 0.0)
                    await device.set_voltage("B",
                        3.3 if (led_state & 0b1_0000000000) >> 10 else 0.0)
                    await asyncio.sleep(0.1)
                    led_state = ((led_state << 1) | (led_state >> 21)) & ~(1 << 22)

            if mode in ("pins-int", "pins-ext", "pins-pull", "pins-bufs"):
                if mode in ("pins-int", "pins-ext") and device.revision >= "C0":
                    raise GlasgowAppletError(f"mode {mode} is not supported on device revision "
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
                elif mode == "pins-bufs":
                    await device.set_voltage("AB", 3.3)

                use_pull = (mode == "pins-pull")

                for bits in (0x0000, 0xffff):
                    await reset_pins(bits)
                    if mode == "pins-bufs":
                        i, desc = await check_bufs(bits, bits)
                    else:
                        i, desc = await check_pins(bits, bits, use_pull=use_pull)
                    self.logger.debug("%s: %s", mode, desc)
                    if bits == 0x0000:
                        fail_high = decode_pins(i)
                    if bits == 0xffff:
                        fail_low  = decode_pins(~i)

                shorted = []
                for bit in range(0, 16):
                    await reset_pins(bits=0x0000)
                    if mode == "pins-bufs":
                        i, desc = await check_bufs(1 << bit, 1 << bit)
                    else:
                        i, desc = await check_pins(1 << bit, 1 << bit, use_pull=use_pull)
                    self.logger.debug("%s: %s", mode, desc)

                    if i != 1 << bit:
                        pins = decode_pins(i) - fail_high
                        if len(pins) > 1 and pins not in shorted:
                            shorted.append(pins)
                        passed = False

                if fail_high:
                    report.append((mode, f"fail high: {' '.join(sorted(fail_high))}"))
                if fail_low:
                    report.append((mode, f"fail low: {' '.join(sorted(fail_low))}"))
                for pins in shorted:
                    report.append((mode, f"fail short: {' '.join(sorted(pins))}"))

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
                            report.append((mode, f"fault: {' '.join(pins)}"))
                            break

                await device.set_voltage("AB", 0)

            if mode == "voltage":
                await device.set_voltage("AB", 0)

                for port in ("A", "B"):
                    for vout in (1.8, 2.7, 3.3, 5.0):
                        await device.set_voltage(port, vout)
                        await asyncio.sleep(0.1)
                        vin = await device.measure_voltage(port)
                        self.logger.debug(f"port {port}: Vio={vout:.1f} Vsense={vin:.2f}"
                                          )

                        if abs(vout - vin) / vout > 0.05:
                            passed = False
                            report.append((mode, f"port {port} out of ±5% tolerance: "
                                                 f"Vio={vout:.2f} Vsense={vin:.2f}"
                                                 ))

                    await device.set_voltage(port, 0)

            if mode == "loopback":
                iface_1, iface_2 = self._loopback_pipes

                data_1 = b"The quick brown fox jumps over the lazy dog.\x55\xaa"
                data_2 = bytes(reversed(data_1))

                for iface_out, ep_out, iface_in, ep_in, data in (
                    (iface_1, "EP2OUT", iface_1, "EP6IN", data_1),
                    (iface_2, "EP4OUT", iface_2, "EP8IN", data_2),
                ):
                    try:
                        await iface_out.send(data)
                        await asyncio.wait_for(iface_out.flush(), timeout=0.1)
                    except TimeoutError:
                        passed = False
                        report.append((mode, f"USB {ep_out} timeout"))
                        continue

                    try:
                        received = await asyncio.wait_for(iface_in.recv(len(data)), timeout=0.1)
                    except TimeoutError:
                        passed = False
                        report.append((mode, f"USB {ep_in} timeout"))
                        continue

                    if received != data:
                        passed = False
                        report.append((mode, f"USB {ep_out}->{ep_in} read-write mismatch"
                                             ))

        if passed:
            self.logger.info("self-test: PASS")
        else:
            for (mode, message) in report:
                self.logger.error("%s: %s", mode, message)
            raise GlasgowAppletError("self-test: FAIL")

    @classmethod
    def tests(cls):
        from . import test
        return test.SelfTestAppletTestCase
