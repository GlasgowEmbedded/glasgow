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

        self.pins      = set(args.pin_set_jtag)
        self.pin_names = {pin: self.mux_interface.get_pin_name(pin) for pin in self.pins}

    async def run(self, device, args):
        return await device.demultiplexer.claim_interface(self, self.mux_interface, args)

    def _bits_to_pins(self, bits):
        pins = []
        for bit, pin in enumerate(self.pins):
            if bits & (1 << bit):
                pins.append(pin)
        return pins

    def _pins_to_names(self, pins):
        return [self.pin_names[pin] for pin in pins]

    def _pins_to_str(self, pins):
        return ", ".join(self._pins_to_names(pins))

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

        high_z_pins    = self._bits_to_pins(~after_low &  after_high)
        pull_up_pins   = self._bits_to_pins( after_low &  after_high)
        pull_down_pins = self._bits_to_pins(~after_low & ~after_high)
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
        tdo_pins = self._bits_to_pins(ir_0 & ~ir_1)
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
        high_z_pins, pull_up_pins, pull_down_pins = await self._detect_pulls(iface)
        if high_z_pins:
            self.logger.info("high-Z: %s", self._pins_to_str(high_z_pins))
        if pull_up_pins:
            self.logger.info("pull-H: %s", self._pins_to_str(pull_up_pins))
        if pull_down_pins:
            self.logger.info("pull-L: %s", self._pins_to_str(pull_down_pins))

        if pull_down_pins and len(self.pins) > 4:
            self.logger.info("found pins with pull-downs, will probe TRST#")
        elif len(self.pins) > 4:
            self.logger.info("no pins with pull-downs, not probing TRST#")

        results = []
        for pin_trst in [None, *pull_down_pins]:
            if pin_trst is None:
                self.logger.info("detecting TCK, TMS and TDO")
                pins = self.pins
            else:
                self.logger.info("detecting TCK, TMS and TDO with TRST#=%s",
                                 self.pin_names[pin_trst])
                pins = self.pins - {pin_trst}

            tck_tms_tdo = []
            for pin_tck in pins:
                for pin_tms in pins - {pin_tck}:
                    self.logger.debug("trying TCK=%s TMS=%s",
                                      self.pin_names[pin_tck], self.pin_names[pin_tms])
                    tdo_pins = await self._detect_tdo(iface, 1 << pin_tck, 1 << pin_tms,
                                                      1 << pin_trst if pin_trst else 0)
                    for pin_tdo in tdo_pins - {pin_tck, pin_tms}:
                        self.logger.info("shifted 10 out of IR with TCK=%s TMS=%s TDO=%s",
                                         self.pin_names[pin_tck], self.pin_names[pin_tms],
                                         self.pin_names[pin_tdo])
                        tck_tms_tdo.append((pin_tck, pin_tms, pin_tdo))

            if not tck_tms_tdo:
                continue

            self.logger.info("detecting TDI")
            for (pin_tck, pin_tms, pin_tdo) in tck_tms_tdo:
                for pin_tdi in pins - {pin_tck, pin_tms, pin_tdo}:
                    self.logger.debug("trying TCK=%s TMS=%s TDI=%s TDO=%s",
                                      self.pin_names[pin_tck], self.pin_names[pin_tms],
                                      self.pin_names[pin_tdi], self.pin_names[pin_tdo])
                    ir_lens = await self._detect_tdi(iface, 1 << pin_tck, 1 << pin_tms,
                                                     1 << pin_tdi, 1 << pin_tdo,
                                                     1 << pin_trst if pin_trst else 0)
                    for ir_len in ir_lens:
                        self.logger.info("shifted %d-bit IR with TCK=%s TMS=%s TDI=%s TDO=%s",
                                         ir_len,
                                         self.pin_names[pin_tck], self.pin_names[pin_tms],
                                         self.pin_names[pin_tdi], self.pin_names[pin_tdo])
                        results.append((pin_tck, pin_tms, pin_tdi, pin_tdo, pin_trst))
                    else:
                        continue

            if results:
                self.logger.info("JTAG interface detected, not probing TRST#")
                break

        if len(results) == 0:
            self.logger.warning("no JTAG interface detected")
        elif len(results) == 1:
            pin_tck, pin_tms, pin_tdi, pin_tdo, pin_trst = results[0]
            args = ["jtag"]
            args += ["--pin-tck", str(pin_tck)]
            args += ["--pin-tms", str(pin_tms)]
            args += ["--pin-tdi", str(pin_tdi)]
            args += ["--pin-tdo", str(pin_tdo)]
            if pin_trst is not None:
                args += ["--pin-trst", str(pin_trst)]
            self.logger.info("use `%s` as arguments", " ".join(args))
        else:
            self.logger.warning("more than one JTAG interface detected; this likely a false "
                                "positive")

# -------------------------------------------------------------------------------------------------

class JTAGPinoutAppletTestCase(GlasgowAppletTestCase, applet=JTAGPinoutApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds(args=["--pins-jtag", "0:3"])
