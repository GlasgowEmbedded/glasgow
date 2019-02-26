import logging
import asyncio
import random
from functools import reduce
from migen import *
from migen.genlib.cdc import MultiReg

from .. import *
from ...gateware.pads import *


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

        self.submodules.fsm = FSM(reset_state="RECV-COMMAND")
        self.fsm.act("RECV-COMMAND",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(cmd, out_fifo.dout),
                If(out_fifo.dout == CMD_W,
                    NextValue(timer, period_cyc - 1),
                    NextState("WAIT")
                ).Elif(out_fifo.dout == CMD_I,
                    NextState("INPUT")
                ).Else(
                    NextState("RECV-DATA")
                )
            )
        )
        self.fsm.act("RECV-DATA",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                If(cmd == CMD_OE,
                    NextValue(jtag_oe, out_fifo.dout)
                ).Elif(cmd == CMD_O,
                    NextValue(jtag_o,  out_fifo.dout)
                ).Elif(cmd == CMD_L,
                    NextValue(jtag_o, ~out_fifo.dout & jtag_o)
                ).Elif(cmd == CMD_H,
                    NextValue(jtag_o,  out_fifo.dout | jtag_o)
                ),
                NextState("RECV-COMMAND")
            )
        )
        self.fsm.act("WAIT",
            If(timer == 0,
                NextState("RECV-COMMAND")
            ).Else(
                NextValue(timer, timer - 1)
            )
        )
        self.fsm.act("INPUT",
            If(in_fifo.writable,
                in_fifo.we.eq(1),
                in_fifo.din.eq(jtag_i),
                NextState("RECV-COMMAND")
            )
        )


class JTAGPinoutApplet(GlasgowApplet, name="jtag-pinout"):
    preview = True
    logger = logging.getLogger(__name__)
    help = "automatically determine JTAG pinout"
    description = """
    Determine JTAG pin functions given a set of pins.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_set_argument(parser, "jtag", width=range(4, 9), required=True)

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
        return await device.demultiplexer.claim_interface(self, self.mux_interface, args)

    def _word_to_bits(self, bits):
        pins = []
        for bit in self.bits:
            if bits & (1 << bit):
                pins.append(bit)
        return pins

    def _bits_to_str(self, pins):
        return ", ".join(self.names[pin] for pin in pins)

    async def _detect_pulls(self, iface):
        for o in (0x00, 0xff):
            await iface.write([
                CMD_O,  o,
                CMD_OE, 0xff,
                CMD_W,
                CMD_OE, 0x00,
                CMD_W,
                CMD_I,
            ])
        after_low, after_high = await iface.read(2)

        high_z_pins    = self._word_to_bits(~after_low &  after_high)
        pull_up_pins   = self._word_to_bits( after_low &  after_high)
        pull_down_pins = self._word_to_bits(~after_low & ~after_high)
        return high_z_pins, pull_up_pins, pull_down_pins

    @staticmethod
    def _x_tck(tck):       return [CMD_L, tck, CMD_W,        CMD_H, tck, CMD_W]

    @staticmethod
    def _x_tck_i_tdo(tck): return [CMD_L, tck, CMD_W, CMD_I, CMD_H, tck, CMD_W]

    async def _enter_shift_ir(self, iface, tck, tms, tdi, trst):
        pulse = self._x_tck(tck)
        await iface.write([
            CMD_O,  tck|tms|tdi|trst,
            CMD_OE, tck|tms|tdi|trst,
            CMD_W,
            # Pulse TRST
            CMD_L, trst, CMD_W,
            CMD_H, trst, CMD_W,
            # Enter Test-Logic-Reset
            CMD_H, tms, *pulse * 5,
            # Enter Run-Test/Idle
            CMD_L, tms, *pulse,
            # Enter Shift-IR
            CMD_H, tms, *pulse,
            CMD_H, tms, *pulse,
            CMD_L, tms, *pulse,
            CMD_L, tms, *pulse,
        ])

    async def _detect_tdo(self, iface, tck, tms, trst=0):
        await self._enter_shift_ir(iface, tck=tck, tms=tms, tdi=0, trst=trst)

        pulse = self._x_tck_i_tdo(tck)
        await iface.write([
            # Shift IR
            *pulse * 2,
            # Release the bus
            CMD_OE, 0,
        ])

        ir_0, ir_1, *_ = await iface.read(2)
        tdo_pins = self._word_to_bits(ir_0 & ~ir_1)
        return set(tdo_pins)

    async def _detect_tdi(self, iface, tck, tms, tdi, tdo, trst=0):
        await self._enter_shift_ir(iface, tck=tck, tms=tms, tdi=tdi, trst=trst)

        pat_bits   = 32
        flush_bits = 64
        pattern    = random.getrandbits(pat_bits)

        pulse = self._x_tck_i_tdo(tck)
        await iface.write([
            # Shift IR
            *sum(([CMD_H if pattern & (1 << bit) else CMD_L, tdi, *pulse]
                  for bit in range(pat_bits)), []),
            CMD_H, tdi, *pulse * flush_bits,
            # Release the bus
            CMD_OE, 0,
        ])

        result = await iface.read(pat_bits + flush_bits)
        ir_lens = []
        for ir_len in range(flush_bits):
            corr_result = [result[ir_len + bit] if pattern & (1 << bit) else ~result[ir_len + bit]
                           for bit in range(pat_bits)]
            if reduce(lambda x, y: x & y, corr_result) & tdo:
                ir_lens.append(ir_len)
        return ir_lens

    async def interact(self, device, args, iface):
        self.logger.info("detecting pull resistors")
        high_z_bits, pull_up_bits, pull_down_bits = await self._detect_pulls(iface)
        if high_z_bits:
            self.logger.info("high-Z: %s", self._bits_to_str(high_z_bits))
        if pull_up_bits:
            self.logger.info("pull-H: %s", self._bits_to_str(pull_up_bits))
        if pull_down_bits:
            self.logger.info("pull-L: %s", self._bits_to_str(pull_down_bits))

        if len(self.bits) > 4:
            trst_bits = self.bits
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
                    tdo_bits = await self._detect_tdo(iface, 1 << bit_tck, 1 << bit_tms,
                                                      0 if bit_trst is None else 1 << bit_trst)
                    for bit_tdo in tdo_bits - {bit_tck, bit_tms}:
                        self.logger.info("shifted 10 out of IR with TCK=%s TMS=%s TDO=%s",
                                         self.names[bit_tck], self.names[bit_tms],
                                         self.names[bit_tdo])
                        tck_tms_tdo.append((bit_tck, bit_tms, bit_tdo))

            if not tck_tms_tdo:
                continue

            self.logger.info("detecting TDI")
            for (bit_tck, bit_tms, bit_tdo) in tck_tms_tdo:
                for bit_tdi in data_bits - {bit_tck, bit_tms, bit_tdo}:
                    self.logger.debug("trying TCK=%s TMS=%s TDI=%s TDO=%s",
                                      self.names[bit_tck], self.names[bit_tms],
                                      self.names[bit_tdi], self.names[bit_tdo])
                    ir_lens = await self._detect_tdi(iface, 1 << bit_tck, 1 << bit_tms,
                                                     1 << bit_tdi, 1 << bit_tdo,
                                                     0 if bit_trst is None else 1 << bit_trst)
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
            args = ["jtag"]
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
