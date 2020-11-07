# Ref: IEEE Std 1149.1-2001
# Accession: G00018

import logging
import asyncio
import random
import struct
from functools import reduce
from nmigen import *
from nmigen.lib.cdc import FFSynchronizer

from ....gateware.pads import *
from ... import *


CMD_W  = 0x00
CMD_OE = 0x01
CMD_O  = 0x02
CMD_L  = 0x03
CMD_H  = 0x04
CMD_I  = 0x05


class JTAGPinoutSubtarget(Elaboratable):
    def __init__(self, pins, out_fifo, in_fifo, period_cyc):
        self._pins       = pins
        self._out_fifo   = out_fifo
        self._in_fifo    = in_fifo
        self._period_cyc = period_cyc

    def elaborate(self, platform):
        m = Module()
        pins = self._pins
        in_fifo  = self._in_fifo
        out_fifo = self._out_fifo

        jtag_oe = Signal(len(pins))
        jtag_o  = Signal(len(pins))
        jtag_i  = Signal(len(pins))
        m.d.comb += [
            Cat(pin.oe for pin in pins).eq(jtag_oe),
            Cat(pin.o  for pin in pins).eq(jtag_o),
        ]
        m.submodules += FFSynchronizer(Cat(pin.i for pin in pins), jtag_i)

        timer = Signal(range(self._period_cyc))
        cmd   = Signal(8)
        data  = Signal(16)

        with m.FSM():
            with m.State("RECV-COMMAND"):
                with m.If(out_fifo.readable):
                    m.d.comb += out_fifo.re.eq(1)
                    m.d.sync += cmd.eq(out_fifo.dout)
                    with m.If(out_fifo.dout == CMD_W):
                        m.d.sync += timer.eq(self._period_cyc - 1)
                        m.next = "WAIT"
                    with m.Elif(out_fifo.dout == CMD_I):
                        m.next = "SAMPLE"
                    with m.Else():
                        m.next = "RECV-DATA-1"

            with m.State("RECV-DATA-1"):
                with m.If(out_fifo.readable):
                    m.d.comb += out_fifo.re.eq(1)
                    m.d.sync += data[0:8].eq(out_fifo.dout)
                    m.next = "RECV-DATA-2"

            with m.State("RECV-DATA-2"):
                with m.If(out_fifo.readable):
                    m.d.comb += out_fifo.re.eq(1)
                    m.d.sync += data[8:16].eq(out_fifo.dout)
                    m.next = "DRIVE"

            with m.State("DRIVE"):
                with m.If(cmd == CMD_OE):
                    m.d.sync += jtag_oe.eq(data)
                with m.Elif(cmd == CMD_O):
                    m.d.sync += jtag_o.eq( data)
                with m.Elif(cmd == CMD_L):
                    m.d.sync += jtag_o.eq(~data & jtag_o)
                with m.Elif(cmd == CMD_H):
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
                with m.If(in_fifo.writable):
                    m.d.comb += in_fifo.we.eq(1)
                    m.d.comb += in_fifo.din.eq(data[0:8])
                    m.next = "SEND-DATA-2"

            with m.State("SEND-DATA-2"):
                with m.If(in_fifo.writable):
                    m.d.comb += in_fifo.we.eq(1)
                    m.d.comb += in_fifo.din.eq(data[8:16])
                    m.next = "RECV-COMMAND"

        return m


class JTAGPinoutInterface:
    def __init__(self, interface, logger):
        self._lower  = interface
        self._logger = logger
        self._level  = logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, "JTAG: " + message, *args)

    async def _cmd(self, cmd):
        await self._lower.write([cmd])

    async def _arg(self, arg):
        await self._lower.write(struct.pack("<H", arg))

    async def _ret(self):
        return struct.unpack("<H", await self._lower.read(2))[0]

    async def wait(self):
        self._log("wait")
        await self._cmd(CMD_W)

    async def set_oe(self, word):
        self._log("set oe=%s", "{:016b}".format(word))
        await self._cmd(CMD_OE)
        await self._arg(word)

    async def set_o(self, word):
        self._log("set o= %s", "{:016b}".format(word))
        await self._cmd(CMD_O)
        await self._arg(word)

    async def set_o_1(self, word):
        self._log("set h= %s", "{:016b}".format(word))
        await self._cmd(CMD_H)
        await self._arg(word)

    async def set_o_0(self, word):
        self._log("set l= %s", "{:016b}".format(word))
        await self._cmd(CMD_L)
        await self._arg(word)

    async def get_i(self):
        await self._cmd(CMD_I)
        word = await self._ret()
        self._log("get i= %s", "{:016b}".format(word))
        return word


class JTAGPinoutApplet(GlasgowApplet, name="jtag-pinout"):
    logger = logging.getLogger(__name__)
    help = "automatically determine JTAG pinout"
    description = """
    Determine JTAG pin functions given a set of pins.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_set_argument(parser, "jtag", width=range(4, 17), required=True)

        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=10,
            help="set clock period to FREQ kHz (default: %(default)s)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(JTAGPinoutSubtarget(
            pins=[iface.get_pin(pin) for pin in args.pin_set_jtag],
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(),
            period_cyc=int(target.sys_clk_freq // (args.frequency * 1000)),
        ))

        self.bits  = set(range(len(args.pin_set_jtag)))
        self.pins  = {bit: pin
                      for bit, pin in enumerate(args.pin_set_jtag)}
        self.names = {bit: self.mux_interface.get_pin_name(pin)
                      for bit, pin in enumerate(args.pin_set_jtag)}

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        return JTAGPinoutInterface(iface, self.logger)

    @staticmethod
    def _to_word(bits):
        return reduce(lambda x, y: x|y, (1 << bit for bit in bits), 0)

    @staticmethod
    def _from_word(word):
        return set(bit for bit in range(word.bit_length()) if word & (1 << bit))

    async def _detect_pulls(self, iface):
        each = self._to_word(self.bits)
        none = self._to_word(set())

        results = []
        for bits in (each, none):
            await iface.set_o (bits)
            await iface.set_oe(each)
            await iface.wait()
            await iface.set_oe(none)
            await iface.wait()
            results.append(await iface.get_i())
        after_low, after_high = results

        high_z_bits    = self._from_word(~after_low &  after_high)
        pull_up_bits   = self._from_word( after_low &  after_high)
        pull_down_bits = self._from_word(~after_low & ~after_high & each)
        return high_z_bits, pull_up_bits, pull_down_bits

    async def _strobe_tck(self, iface, tck):
        await iface.set_o_0(tck)
        await iface.wait()
        await iface.set_o_1(tck)
        await iface.wait()

    async def _strobe_tck_input(self, iface, tck):
        await iface.set_o_0(tck)
        await iface.wait()
        word = await iface.get_i()
        await iface.set_o_1(tck)
        await iface.wait()
        return word

    async def _enter_shift_ir(self, iface, *, tck, tms, tdi, trst=0, assert_trst=False):
        await iface.set_o (tck|tms|tdi|trst)
        await iface.set_oe(tck|tms|tdi|trst)
        await iface.wait()
        # Pulse or assert TRST
        await iface.set_o_0(trst); await iface.wait()
        if not assert_trst:
            await iface.set_o_1(trst); await iface.wait()
        # Enter Test-Logic-Reset
        await iface.set_o_1(tms)
        for _ in range(5):
            await self._strobe_tck(iface, tck)
        # Enter Run-Test/Idle
        await iface.set_o_0(tms)
        await self._strobe_tck(iface, tck)
        # Enter Shift-IR
        await iface.set_o_1(tms); await self._strobe_tck(iface, tck)
        await iface.set_o_1(tms); await self._strobe_tck(iface, tck)
        await iface.set_o_0(tms); await self._strobe_tck(iface, tck)
        await iface.set_o_0(tms); await self._strobe_tck(iface, tck)

    async def _detect_tdo(self, iface, *, tck, tms, trst=0, assert_trst=False):
        await self._enter_shift_ir(iface, tck=tck, tms=tms, tdi=0, trst=trst,
                                   assert_trst=assert_trst)

        # Shift IR
        ir_0 = await self._strobe_tck_input(iface, tck)
        ir_1 = await self._strobe_tck_input(iface, tck)
        # Release the bus
        await iface.set_oe(0)

        tdo_bits = self._from_word(ir_0 & ~ir_1)
        return set(tdo_bits)

    async def _detect_tdi(self, iface, *, tck, tms, tdi, tdo, trst=0):
        await self._enter_shift_ir(iface, tck=tck, tms=tms, tdi=tdi, trst=trst)

        pat_bits   = 32
        flush_bits = 64
        pattern    = random.getrandbits(pat_bits)
        result     = []

        # Shift IR
        for bit in range(pat_bits):
            if pattern & (1 << bit):
                await iface.set_o_1(tdi)
            else:
                await iface.set_o_0(tdi)
            result.append(await self._strobe_tck_input(iface, tck))
        await iface.set_o_1(tdi)
        for bit in range(flush_bits):
            result.append(await self._strobe_tck_input(iface, tck))
        # Release the bus
        await iface.set_oe(0)

        for ir_len in range(flush_bits):
            corr_result = [result[ir_len + bit] if pattern & (1 << bit) else ~result[ir_len + bit]
                           for bit in range(pat_bits)]
            if reduce(lambda x, y: x&y, corr_result) & tdo:
                return ir_len

    async def interact(self, device, args, iface):
        def bits_to_str(pins):
            return ", ".join(self.names[pin] for pin in pins)

        self.logger.info("detecting pull resistors")
        high_z_bits, pull_up_bits, pull_down_bits = await self._detect_pulls(iface)
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
                    tdo_bits = await self._detect_tdo(iface,
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
                    ir_len = await self._detect_tdi(iface,
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
                    tdo_bits_1 = await self._detect_tdo(iface,
                        tck=1 << bit_tck, tms=1 << bit_tms, trst=1 << bit_trst,
                        assert_trst=True)
                    tdo_bits_0 = await self._detect_tdo(iface,
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

            if args.voltage is not None:
                probe_args += ["-V", "{:.1f}".format(args.voltage)]
            elif args.mirror_voltage:
                probe_args += ["-M"]
            elif args.keep_voltage:
                probe_args += ["--keep-voltage"]

            probe_args += ["--pin-tck", str(self.pins[bit_tck])]
            probe_args += ["--pin-tms", str(self.pins[bit_tms])]
            probe_args += ["--pin-tdi", str(self.pins[bit_tdi])]
            probe_args += ["--pin-tdo", str(self.pins[bit_tdo])]
            if bit_trst is not None:
                probe_args += ["--pin-trst", str(self.pins[bit_trst])]

            self.logger.info("use `%s` as arguments", " ".join(probe_args))

        else:
            self.logger.warning("more than one JTAG interface detected; this is likely a false "
                                "positive")

# -------------------------------------------------------------------------------------------------

class JTAGPinoutAppletTestCase(GlasgowAppletTestCase, applet=JTAGPinoutApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--pins-jtag", "0:3"])
