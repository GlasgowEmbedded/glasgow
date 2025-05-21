# Ref: IEEE Std 1149.1-2001
# Accession: G00018

import logging
import random
import struct
from functools import reduce

from amaranth import *
from amaranth.lib import io, wiring, stream, cdc, enum
from amaranth.lib.wiring import In, Out

from glasgow.applet import GlasgowAppletV2


class JTAGPinoutCommand(enum.Enum, shape=8):
    Wait  = 0x00
    SetOE = 0x01
    SetO  = 0x02
    SetO0 = 0x03
    SetO1 = 0x04
    GetI  = 0x05


class JTAGPinoutComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))

    def __init__(self, ports, period_cyc):
        self._ports      = ports
        self._period_cyc = period_cyc

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        pins = []
        for i, port in enumerate(self._ports.pins):
            m.submodules[f"pins{i}_buffer"] = pin = io.Buffer("io", port)
            pins.append(pin)

        jtag_oe = Signal(len(pins))
        jtag_o  = Signal(len(pins))
        jtag_i  = Signal(len(pins))
        m.d.comb += [
            Cat(pin.oe for pin in pins).eq(jtag_oe),
            Cat(pin.o  for pin in pins).eq(jtag_o),
        ]
        m.submodules += cdc.FFSynchronizer(Cat(pin.i for pin in pins), jtag_i)

        timer = Signal(range(self._period_cyc))
        cmd   = Signal(JTAGPinoutCommand)
        data  = Signal(16)

        with m.FSM():
            with m.State("RECV-COMMAND"):
                with m.If(self.i_stream.valid):
                    m.d.comb += self.i_stream.ready.eq(1)
                    m.d.sync += cmd.eq(self.i_stream.payload)
                    with m.If(self.i_stream.payload == JTAGPinoutCommand.Wait):
                        m.d.sync += timer.eq(self._period_cyc - 1)
                        m.next = "WAIT"
                    with m.Elif(self.i_stream.payload == JTAGPinoutCommand.GetI):
                        m.next = "SAMPLE"
                    with m.Else():
                        m.next = "RECV-DATA-1"

            with m.State("RECV-DATA-1"):
                with m.If(self.i_stream.valid):
                    m.d.comb += self.i_stream.ready.eq(1)
                    m.d.sync += data[0:8].eq(self.i_stream.payload)
                    m.next = "RECV-DATA-2"

            with m.State("RECV-DATA-2"):
                with m.If(self.i_stream.valid):
                    m.d.comb += self.i_stream.ready.eq(1)
                    m.d.sync += data[8:16].eq(self.i_stream.payload)
                    m.next = "DRIVE"

            with m.State("DRIVE"):
                with m.If(cmd == JTAGPinoutCommand.SetOE):
                    m.d.sync += jtag_oe.eq(data)
                with m.Elif(cmd == JTAGPinoutCommand.SetO):
                    m.d.sync += jtag_o.eq( data)
                with m.Elif(cmd == JTAGPinoutCommand.SetO0):
                    m.d.sync += jtag_o.eq(~data & jtag_o)
                with m.Elif(cmd == JTAGPinoutCommand.SetO1):
                    m.d.sync += jtag_o.eq( data | jtag_o)
                m.next = "RECV-COMMAND"

            with m.State("WAIT"):
                with m.If(timer == 0):
                    m.next = "RECV-COMMAND"
                with m.Else():
                    m.d.sync += timer.eq(timer - 1)

            with m.State("SAMPLE"):
                m.d.sync += data.eq(jtag_i)
                m.next = "SEND-DATA-1"

            with m.State("SEND-DATA-1"):
                m.d.comb += self.o_stream.valid.eq(1)
                m.d.comb += self.o_stream.payload.eq(data[0:8])
                with m.If(self.o_stream.ready):
                    m.next = "SEND-DATA-2"

            with m.State("SEND-DATA-2"):
                m.d.comb += self.o_stream.valid.eq(1)
                m.d.comb += self.o_stream.payload.eq(data[8:16])
                with m.If(self.o_stream.ready):
                    m.next = "RECV-COMMAND"

        return m


class JTAGPinoutInterface:
    def __init__(self, logger, assembly, *, pins, frequency):
        self._logger = logger
        self._level  = logging.TRACE

        ports = assembly.add_port_group(pins=pins)
        component = assembly.add_submodule(JTAGPinoutComponent(ports,
            period_cyc=round(1 / (assembly.sys_clk_period * frequency)),
        ))
        self._pipe = assembly.add_inout_pipe(component.o_stream, component.i_stream)

    def _log(self, message, *args):
        self._logger.log(self._level, "JTAG: " + message, *args)

    async def _cmd(self, cmd):
        await self._pipe.send([cmd.value])

    async def _arg(self, arg):
        await self._pipe.send(struct.pack("<H", arg))

    async def _ret(self):
        return struct.unpack("<H", await self._pipe.recv(2))[0]

    async def wait(self):
        self._log("wait")
        await self._cmd(JTAGPinoutCommand.Wait)

    async def set_oe(self, word):
        self._log("set oe=%s", f"{word:016b}")
        await self._cmd(JTAGPinoutCommand.SetOE)
        await self._arg(word)

    async def set_o(self, word):
        self._log("set o= %s", f"{word:016b}")
        await self._cmd(JTAGPinoutCommand.SetO)
        await self._arg(word)

    async def set_o_1(self, word):
        self._log("set h= %s", f"{word:016b}")
        await self._cmd(JTAGPinoutCommand.SetO1)
        await self._arg(word)

    async def set_o_0(self, word):
        self._log("set l= %s", f"{word:016b}")
        await self._cmd(JTAGPinoutCommand.SetO0)
        await self._arg(word)

    async def get_i(self):
        await self._cmd(JTAGPinoutCommand.GetI)
        await self._pipe.flush()
        word = await self._ret()
        self._log("get i= %s", f"{word:016b}")
        return word


class JTAGPinoutApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "automatically determine JTAG pinout"
    description = """
    Determine JTAG pin functions given a set of pins.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)

        access.add_pins_argument(parser, "pins", width=range(4, 17), required=True)

        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=10,
            help="set clock period to FREQ kHz (default: %(default)s)")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.jtag_iface = JTAGPinoutInterface(self.logger, self.assembly,
                pins=args.pins, frequency=args.frequency * 1000)

        self.bits  = set(range(len(args.pins)))
        self.pins  = {bit: pin      for bit, pin in enumerate(args.pins)}
        self.names = {bit: str(pin) for bit, pin in enumerate(args.pins)}

    @staticmethod
    def _to_word(bits):
        return reduce(lambda x, y: x|y, (1 << bit for bit in bits), 0)

    @staticmethod
    def _from_word(word):
        return {bit for bit in range(word.bit_length()) if word & (1 << bit)}

    async def _detect_pulls(self):
        each = self._to_word(self.bits)
        none = self._to_word(set())

        results = []
        for bits in (each, none):
            await self.jtag_iface.set_o (bits)
            await self.jtag_iface.set_oe(each)
            await self.jtag_iface.wait()
            await self.jtag_iface.set_oe(none)
            await self.jtag_iface.wait()
            results.append(await self.jtag_iface.get_i())
        after_low, after_high = results

        high_z_bits    = self._from_word(~after_low &  after_high)
        pull_up_bits   = self._from_word( after_low &  after_high)
        pull_down_bits = self._from_word(~after_low & ~after_high & each)
        return high_z_bits, pull_up_bits, pull_down_bits

    async def _strobe_tck(self, tck):
        await self.jtag_iface.set_o_0(tck)
        await self.jtag_iface.wait()
        await self.jtag_iface.set_o_1(tck)
        await self.jtag_iface.wait()

    async def _strobe_tck_input(self, tck):
        await self.jtag_iface.set_o_0(tck)
        await self.jtag_iface.wait()
        word = await self.jtag_iface.get_i()
        await self.jtag_iface.set_o_1(tck)
        await self.jtag_iface.wait()
        return word

    async def _enter_shift_ir(self, *, tck, tms, tdi, trst=0, assert_trst=False):
        await self.jtag_iface.set_o (tck|tms|tdi|trst)
        await self.jtag_iface.set_oe(tck|tms|tdi|trst)
        await self.jtag_iface.wait()
        # Pulse or assert TRST
        await self.jtag_iface.set_o_0(trst); await self.jtag_iface.wait()
        if not assert_trst:
            await self.jtag_iface.set_o_1(trst); await self.jtag_iface.wait()
        # Enter Test-Logic-Reset
        await self.jtag_iface.set_o_1(tms)
        for _ in range(5):
            await self._strobe_tck(tck)
        # Enter Run-Test/Idle
        await self.jtag_iface.set_o_0(tms)
        await self._strobe_tck(tck)
        # Enter Shift-IR
        await self.jtag_iface.set_o_1(tms); await self._strobe_tck(tck)
        await self.jtag_iface.set_o_1(tms); await self._strobe_tck(tck)
        await self.jtag_iface.set_o_0(tms); await self._strobe_tck(tck)
        await self.jtag_iface.set_o_0(tms); await self._strobe_tck(tck)

    async def _detect_tdo(self, *, tck, tms, trst=0, assert_trst=False):
        await self._enter_shift_ir(tck=tck, tms=tms, tdi=0, trst=trst,
                                   assert_trst=assert_trst)

        # Shift IR
        ir_0 = await self._strobe_tck_input(tck)
        ir_1 = await self._strobe_tck_input(tck)
        # Release the bus
        await self.jtag_iface.set_oe(0)

        tdo_bits = self._from_word(ir_0 & ~ir_1)
        return set(tdo_bits)

    async def _detect_tdi(self, *, tck, tms, tdi, tdo, trst=0):
        await self._enter_shift_ir(tck=tck, tms=tms, tdi=tdi, trst=trst)

        pat_bits   = 32
        flush_bits = 64
        pattern    = random.getrandbits(pat_bits)
        result     = []

        # Shift IR
        for bit in range(pat_bits):
            if pattern & (1 << bit):
                await self.jtag_iface.set_o_1(tdi)
            else:
                await self.jtag_iface.set_o_0(tdi)
            result.append(await self._strobe_tck_input(tck))
        await self.jtag_iface.set_o_1(tdi)
        for bit in range(flush_bits):
            result.append(await self._strobe_tck_input(tck))
        # Release the bus
        await self.jtag_iface.set_oe(0)

        for ir_len in range(flush_bits):
            corr_result = [result[ir_len + bit] if pattern & (1 << bit) else ~result[ir_len + bit]
                           for bit in range(pat_bits)]
            if reduce(lambda x, y: x&y, corr_result) & tdo:
                return ir_len

    async def run(self, args):
        def bits_to_str(pins):
            return ", ".join(self.names[pin] for pin in pins)

        self.logger.info("detecting pull resistors")
        high_z_bits, pull_up_bits, pull_down_bits = await self._detect_pulls()
        if high_z_bits:
            self.logger.info("high-Z: %s", bits_to_str(high_z_bits))
        if pull_up_bits:
            self.logger.info("pull-H: %s", bits_to_str(pull_up_bits))
        if pull_down_bits:
            self.logger.info("pull-L: %s", bits_to_str(pull_down_bits))

        trst_l_bits = []
        trst_h_bits = []
        if len(self.bits) > 4:
            # Try possible TRST# pins from most to least likely. This changes based on whether we
            # expect TRST# to be low (i.e. if we can't detect the TAP without TRST) or to be high
            # (i.e. if we found a TAP without TRST).
            trst_l_bits += pull_down_bits
            trst_h_bits += pull_up_bits
            trst_l_bits += high_z_bits
            trst_h_bits += high_z_bits
            # Try inconsistent (neither pull-up nor pull-down nor high-Z) pins and pins pulled to
            # the wrong direction after exhausting every reasonable attempt.
            trst_l_bits += self.bits - set(trst_l_bits)
            trst_h_bits += self.bits - set(trst_h_bits)

        results = []
        for bit_trst in [None, *trst_l_bits]:
            if bit_trst is None:
                self.logger.info("detecting TCK, TMS, and TDO")
                data_bits = self.bits
            else:
                self.logger.info("detecting TCK, TMS, and TDO with TRST#=%s",
                                 self.names[bit_trst])
                data_bits = self.bits - {bit_trst}

            # Try every TCK, TMS pin combination to detect possible TDO pins in parallel.
            tck_tms_tdo = []
            for bit_tck in data_bits:
                for bit_tms in data_bits - {bit_tck}:
                    self.logger.debug("trying TCK=%s TMS=%s",
                        self.names[bit_tck], self.names[bit_tms])
                    tdo_bits = await self._detect_tdo(
                        tck=1 << bit_tck, tms=1 << bit_tms,
                        trst=0 if bit_trst is None else 1 << bit_trst)
                    for bit_tdo in tdo_bits - {bit_tck, bit_tms}:
                        self.logger.info("shifted 10 out of IR with TCK=%s TMS=%s TDO=%s",
                            self.names[bit_tck], self.names[bit_tms], self.names[bit_tdo])
                        tck_tms_tdo.append((bit_tck, bit_tms, bit_tdo))

            if not tck_tms_tdo:
                continue

            self.logger.info("detecting TDI")

            # Try every TDI pin for every potential TCK, TMS, TDO combination.
            tck_tms_tdi_tdo = []
            for (bit_tck, bit_tms, bit_tdo) in tck_tms_tdo:
                for bit_tdi in data_bits - {bit_tck, bit_tms, bit_tdo}:
                    self.logger.debug("trying TCK=%s TMS=%s TDI=%s TDO=%s",
                        self.names[bit_tck], self.names[bit_tms],
                        self.names[bit_tdi], self.names[bit_tdo])
                    ir_len = await self._detect_tdi(
                        tck=1 << bit_tck, tms=1 << bit_tms, tdi=1 << bit_tdi, tdo=1 << bit_tdo,
                        trst=0 if bit_trst is None else 1 << bit_trst)
                    if ir_len is None or ir_len < 2:
                        continue
                    self.logger.info("shifted %d-bit IR with TCK=%s TMS=%s TDI=%s TDO=%s",
                        ir_len,
                        self.names[bit_tck], self.names[bit_tms],
                        self.names[bit_tdi], self.names[bit_tdo])
                    tck_tms_tdi_tdo.append((bit_tck, bit_tms, bit_tdi, bit_tdo))

            if not tck_tms_tdi_tdo:
                continue

            if bit_trst is not None or len(self.bits) == 4:
                # TRST# is either already known, or can't be present.
                for bits in tck_tms_tdi_tdo:
                    results.append((*bits, bit_trst))
                break

            self.logger.info("detecting TRST#")

            # Although we have discovered a JTAG interface without TRST#, if it is still possible
            # that a TRST# pin is connected and pulled up (or worse, floating), try to detect it.
            # Otherwise, if the pull-up is weak or the pin is floating, interference may cause it
            # to become spuriously active, especially with high volume of JTAG traffic on nearby
            # pins, and disrupt operation of the probe.
            #
            # Try every TRST# pin for every potential TCK, TMS, TDI, TDO combination.
            for (bit_tck, bit_tms, bit_tdi, bit_tdo) in tck_tms_tdi_tdo:
                for bit_trst in trst_h_bits:
                    if bit_trst in {bit_tck, bit_tms, bit_tdi, bit_tdo}:
                        continue
                    self.logger.debug("trying TCK=%s TMS=%s TDI=%s TDO=%s TRST#=%s",
                        self.names[bit_tck], self.names[bit_tms],
                        self.names[bit_tdi], self.names[bit_tdo],
                        self.names[bit_trst])
                    tdo_bits_1 = await self._detect_tdo(
                        tck=1 << bit_tck, tms=1 << bit_tms, trst=1 << bit_trst,
                        assert_trst=True)
                    tdo_bits_0 = await self._detect_tdo(
                        tck=1 << bit_tck, tms=1 << bit_tms, trst=1 << bit_trst,
                        assert_trst=False)
                    if bit_tdo in tdo_bits_0 and bit_tdo not in tdo_bits_1:
                        self.logger.info("disabled TAP with TCK=%s TMS=%s TDI=%s "
                                         "TDO=%s TRST#=%s",
                            self.names[bit_tck], self.names[bit_tms],
                            self.names[bit_tdi], self.names[bit_tdo],
                            self.names[bit_trst])
                        results.append((bit_tck, bit_tms, bit_tdi, bit_tdo, bit_trst))

            if not results:
                # TRST# is not found.
                for bits in tck_tms_tdi_tdo:
                    results.append((*bits, None))
            break

        if len(results) == 0:
            self.logger.warning("no JTAG interface detected")

        elif len(results) == 1:
            bit_tck, bit_tms, bit_tdi, bit_tdo, bit_trst = results[0]
            if bit_trst is not None:
                self.logger.info("JTAG interface with reset detected")
            else:
                self.logger.info("JTAG interface without reset detected")

            probe_args = ["jtag-probe"]
            if args.voltage:
                probe_args += ["-V", ",".join(f"{port}={vio}" for port, vio in args.voltage.items())]
            probe_args += ["--tck", str(self.pins[bit_tck])]
            probe_args += ["--tms", str(self.pins[bit_tms])]
            probe_args += ["--tdi", str(self.pins[bit_tdi])]
            probe_args += ["--tdo", str(self.pins[bit_tdo])]
            if bit_trst is not None:
                probe_args += ["--trst", str(self.pins[bit_trst])]
            self.logger.info("use `%s` as arguments", " ".join(probe_args))

        else:
            self.logger.warning("more than one JTAG interface detected; this is likely a false "
                                "positive")

    @classmethod
    def tests(cls):
        from . import test
        return test.JTAGPinoutAppletTestCase
