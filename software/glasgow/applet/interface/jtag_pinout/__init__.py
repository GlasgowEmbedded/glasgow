# Ref: IEEE Std 1149.1-2001
# Accession: G00018

import logging
import asyncio
import random
import struct
from functools import reduce
from migen import *
from migen.genlib.cdc import MultiReg

from ....gateware.pads import *
from ... import *


CMD_W  = 0x00
CMD_OE = 0x01
CMD_O  = 0x02
CMD_L  = 0x03
CMD_H  = 0x04
CMD_I  = 0x05


class JTAGPinoutSubtarget(Module):
    def __init__(self, pins, out_fifo, in_fifo, period_cyc):
        jtag_oe = Signal(len(pins))
        jtag_o  = Signal(len(pins))
        jtag_i  = Signal(len(pins))
        self.comb += [
            Cat(pin.oe for pin in pins).eq(jtag_oe),
            Cat(pin.o  for pin in pins).eq(jtag_o),
        ]
        self.specials += MultiReg(Cat(pin.i for pin in pins), jtag_i)

        timer = Signal(max=period_cyc)
        cmd   = Signal(8)
        data  = Signal(16)

        self.submodules.fsm = FSM(reset_state="RECV-COMMAND")
        self.fsm.act("RECV-COMMAND",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(cmd, out_fifo.dout),
                If(out_fifo.dout == CMD_W,
                    NextValue(timer, period_cyc - 1),
                    NextState("WAIT")
                ).Elif(out_fifo.dout == CMD_I,
                    NextState("SAMPLE")
                ).Else(
                    NextState("RECV-DATA-1")
                )
            )
        )
        self.fsm.act("RECV-DATA-1",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(data[0:8], out_fifo.dout),
                NextState("RECV-DATA-2")
            )
        )
        self.fsm.act("RECV-DATA-2",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(data[8:16], out_fifo.dout),
                NextState("DRIVE")
            )
        )
        self.fsm.act("DRIVE",
            If(cmd == CMD_OE,
                NextValue(jtag_oe, data)
            ).Elif(cmd == CMD_O,
                NextValue(jtag_o,  data)
            ).Elif(cmd == CMD_L,
                NextValue(jtag_o, ~data & jtag_o)
            ).Elif(cmd == CMD_H,
                NextValue(jtag_o,  data | jtag_o)
            ),
            NextState("RECV-COMMAND")
        )
        self.fsm.act("WAIT",
            If(timer == 0,
                NextState("RECV-COMMAND")
            ).Else(
                NextValue(timer, timer - 1)
            )
        )
        self.fsm.act("SAMPLE",
            NextValue(data, jtag_i),
            NextState("SEND-DATA-1")
        )
        self.fsm.act("SEND-DATA-1",
            If(in_fifo.writable,
                in_fifo.we.eq(1),
                in_fifo.din.eq(data[0:8]),
                NextState("SEND-DATA-2")
            )
        )
        self.fsm.act("SEND-DATA-2",
            If(in_fifo.writable,
                in_fifo.we.eq(1),
                in_fifo.din.eq(data[8:16]),
                NextState("RECV-COMMAND")
            )
        )


class JTAGPinoutInterface:
    def __init__(self, interface, logger):
        self._lower  = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

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

    async def _enter_shift_ir(self, iface, *, tck, tms, tdi, trst=0):
        await iface.set_o (tck|tms|tdi|trst)
        await iface.set_oe(tck|tms|tdi|trst)
        await iface.wait()
        # Pulse TRST
        await iface.set_o_0(trst); await iface.wait()
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

    async def _detect_tdo(self, iface, *, tck, tms, trst=0):
        await self._enter_shift_ir(iface, tck=tck, tms=tms, tdi=0, trst=trst)

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

        ir_lens = []
        for ir_len in range(flush_bits):
            corr_result = [result[ir_len + bit] if pattern & (1 << bit) else ~result[ir_len + bit]
                           for bit in range(pat_bits)]
            if reduce(lambda x, y: x&y, corr_result) & tdo:
                ir_lens.append(ir_len)
        return ir_lens

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

        if len(self.bits) > 4:
            # Try possible TRST# pins from most to least likely.
            trst_bits = set.union(pull_down_bits, high_z_bits, pull_up_bits)
        else:
            trst_bits = set()

        results = []
        for bit_trst in [None, *trst_bits]:
            if bit_trst is None:
                self.logger.info("detecting TCK, TMS and TDO")
                data_bits = self.bits
            else:
                self.logger.info("detecting TCK, TMS and TDO with TRST#=%s",
                                 self.names[bit_trst])
                data_bits = self.bits - {bit_trst}

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
            for (bit_tck, bit_tms, bit_tdo) in tck_tms_tdo:
                for bit_tdi in data_bits - {bit_tck, bit_tms, bit_tdo}:
                    self.logger.debug("trying TCK=%s TMS=%s TDI=%s TDO=%s",
                        self.names[bit_tck], self.names[bit_tms],
                        self.names[bit_tdi], self.names[bit_tdo])
                    ir_lens = await self._detect_tdi(iface,
                        tck=1 << bit_tck, tms=1 << bit_tms, tdi=1 << bit_tdi, tdo=1 << bit_tdo,
                        trst=0 if bit_trst is None else 1 << bit_trst)
                    for ir_len in ir_lens:
                        self.logger.info("shifted %d-bit IR with TCK=%s TMS=%s TDI=%s TDO=%s",
                            ir_len,
                            self.names[bit_tck], self.names[bit_tms],
                            self.names[bit_tdi], self.names[bit_tdo])
                        results.append((bit_tck, bit_tms, bit_tdi, bit_tdo, bit_trst))
                    else:
                        continue

            if bit_trst is None:
                if results:
                    self.logger.info("JTAG interface detected, not probing TRST#")
                    break
                elif trst_bits:
                    self.logger.info("no JTAG interface detected yet, probing TRST#")
            elif results:
                self.logger.info("JTAG interface detected with TRST#=%s",
                                 self.names[bit_trst])
                break

        if len(results) == 0:
            self.logger.warning("no JTAG interface detected")
        elif len(results) == 1:
            bit_tck, bit_tms, bit_tdi, bit_tdo, bit_trst = results[0]
            args = ["jtag-probe"]
            args += ["--pin-tck", str(self.pins[bit_tck])]
            args += ["--pin-tms", str(self.pins[bit_tms])]
            args += ["--pin-tdi", str(self.pins[bit_tdi])]
            args += ["--pin-tdo", str(self.pins[bit_tdo])]
            if bit_trst is not None:
                args += ["--pin-trst", str(self.pins[bit_trst])]
            self.logger.info("use `%s` as arguments", " ".join(args))
        else:
            self.logger.warning("more than one JTAG interface detected; this likely a false "
                                "positive")

# -------------------------------------------------------------------------------------------------

class JTAGPinoutAppletTestCase(GlasgowAppletTestCase, applet=JTAGPinoutApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--pins-jtag", "0:3"])
