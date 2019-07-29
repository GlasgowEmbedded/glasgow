# Ref: https://static.docs.arm.com/ihi0031/c/IHI0031C_debug_interface_as.pdf
# Document Number: IHI0031C
# Accession: G00027

import logging
import asyncio
import struct
import math
from migen import *

from ....gateware.pads import *
from ... import *


class SWDBus(Module):
    def __init__(self, pads, period_cyc):
        self.di  = Signal(52)
        self.do  = Signal(33)
        self.w   = Signal()
        self.cnt = Signal(max=max(self.di.nbits, self.do.nbits) + 1)
        self.ack = Signal()
        self.rdy = Signal()

        ###

        clk = Signal(reset=1)
        oe  = Signal(reset=1)
        o   = Signal(reset=0)
        i   = Signal()
        self.comb += [
            pads.clk_t.oe.eq(1),
            pads.clk_t.o.eq(clk),
            pads.io_t.oe.eq(oe),
            pads.io_t.o.eq(o),
            i.eq(pads.io_t.i),
        ]

        half_cyc = period_cyc // 2
        timer    = Signal(max=half_cyc)
        stb      = Signal()
        self.sync += [
            If(timer == 0,
                timer.eq(half_cyc - 1),
            ).Else(
                timer.eq(timer - 1)
            )
        ]
        self.comb += stb.eq(timer == 0)

        d   = Signal(max(self.di.nbits, self.do.nbits))
        cnt = Signal(max=d.nbits)
        self.sync += [
            If(self.rdy & self.ack,
                If(self.w,
                    d.eq(self.di)
                ).Else(
                    d.eq(self.do)
                ),
                cnt.eq(self.cnt),
            )
        ]

        self.submodules.fsm = FSM(reset_state="IDLE")
        self.fsm.act("IDLE",
            self.rdy.eq(1),
            If(self.ack,
                If(self.w & ~oe,
                    NextValue(o, 0),
                    NextValue(oe, 1),
                    NextState("TURN-WRITE")
                ).Elif(~self.w & oe,
                    NextValue(oe, 0),
                    NextState("TURN-READ")
                ).Else(
                    NextState("FALLING")
                )
            ).Elif(stb,
                NextValue(o, 0)
            )
        )
        self.fsm.act("TURN-WRITE",
            If(stb,
                If(clk,
                    NextValue(clk, 0),
                ).Else(
                    NextValue(clk, 1),
                    NextState("FALLING")
                )
            )
        )
        self.fsm.act("TURN-READ",
            If(stb,
                If(clk,
                    NextValue(clk, 0),
                ).Else(
                    NextValue(clk, 1),
                    NextState("FALLING")
                )
            )
        )
        self.fsm.act("FALLING",
            If(stb,
                If(oe,
                    NextValue(o, d[0])
                ).Else(
                    NextValue(d[1:], d)
                ),
                NextValue(cnt, cnt - 1),
                NextValue(clk, 0),
                NextState("RISING")
            )
        )
        self.fsm.act("RISING",
            If(stb,
                If(oe,
                    NextValue(d, d[1:])
                ).Else(
                    NextValue(d[0], i)
                ),
                NextValue(clk, 1),
                If(cnt == 0,
                    NextState("DONE")
                ).Else(
                    NextState("FALLING")
                )
            )
        )
        self.fsm.act("DONE",
            If(~oe,
                NextValue(self.do, d)
            ),
            NextState("IDLE")
        )


CMD_LINE_RESET  = 0xff
CMD_JTAG_TO_SWD = 0xfe


class SWDSubtarget(Module):
    def __init__(self, pads, out_fifo, in_fifo, period_cyc):
        self.submodules.bus = SWDBus(pads, period_cyc)

        ###

        def reverse(sig, bits):
            return Cat(sig[b - 1] for b in range(bits, 0, -1))

        def parity(sig):
            bits, _ = value_bits_sign(sig)
            return sum([sig[b] for b in range(bits)]) & 1

        cmd  = Signal(8)
        data = Signal(32)

        self.submodules.fsm = FSM(reset_state="IDLE")
        self.fsm.act("CLOCK-IDLE",
            If(self.bus.rdy,
                If(~out_fifo.readable,
                    self.bus.w.eq(1),
                    self.bus.di.eq(0),
                    self.bus.cnt.eq(8),
                    self.bus.ack.eq(1),
                ),
                NextState("IDLE")
            )
        )
        self.fsm.act("IDLE",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(cmd, out_fifo.dout),
                NextState("SWD-WRITE-COMMAND")
            )
        )
        self.fsm.act("SWD-WRITE-COMMAND",
            If(self.bus.rdy,
                If(cmd == CMD_LINE_RESET,
                    self.bus.w.eq(1),
                    self.bus.di.eq((1 << 50) - 1),
                    self.bus.cnt.eq(52),
                    self.bus.ack.eq(1),
                    NextState("FIFO-WRITE-REPLY")
                ).Elif(cmd == CMD_JTAG_TO_SWD,
                    self.bus.w.eq(1),
                    self.bus.di.eq(0b1110_0111_1001_1110),
                    self.bus.cnt.eq(16),
                    self.bus.ack.eq(1),
                    NextState("FIFO-WRITE-REPLY")
                ).Elif(cmd & 0x80,
                    self.bus.w.eq(1),
                    self.bus.di.eq(Cat(
                        C(0b1, 1),          # start
                        cmd[0:4],           # APnDP, RnW, A[2:3]
                        parity(cmd[0:4]),   # parity
                        C(0b0, 1),          # stop
                        C(0b1, 1),          # park
                    )),
                    self.bus.cnt.eq(8),
                    self.bus.ack.eq(1),
                    If(cmd & 0b10,
                        NextState("SWD-READ-ACK")
                    ).Else(
                        NextState("FIFO-READ-DATA-1")
                    )
                ).Else(
                    NextState("IDLE")
                )
            )
        )
        self.fsm.act("FIFO-WRITE-REPLY",
            If(self.bus.rdy & in_fifo.writable,
                in_fifo.we.eq(1),
                in_fifo.din.eq(cmd),
                NextState("CLOCK-IDLE")
            )
        )
        for (state, shift, next_state) in (
            ("FIFO-READ-DATA-1",  0, "FIFO-READ-DATA-2"),
            ("FIFO-READ-DATA-2",  8, "FIFO-READ-DATA-3"),
            ("FIFO-READ-DATA-3", 16, "FIFO-READ-DATA-4"),
            ("FIFO-READ-DATA-4", 24, "SWD-READ-ACK"),
        ):
            self.fsm.act(state,
                If(out_fifo.readable,
                    out_fifo.re.eq(1),
                    NextValue(data[shift:shift + 8], out_fifo.dout),
                    NextState(next_state)
                )
            )
        self.fsm.act("SWD-READ-ACK",
            If(self.bus.rdy,
                self.bus.w.eq(0),
                self.bus.cnt.eq(3),
                self.bus.ack.eq(1),
                NextState("SWD-CHECK-ACK")
            )
        )
        self.fsm.act("SWD-CHECK-ACK",
            If(self.bus.rdy & in_fifo.writable,
                in_fifo.we.eq(1),
                in_fifo.din.eq(reverse(self.bus.do, 3)),
                If(reverse(self.bus.do, 3) == 0b001,
                    If(cmd & 0b10,
                        self.bus.w.eq(0),
                        self.bus.cnt.eq(33),
                        self.bus.ack.eq(1),
                        NextState("SWD-READ-DATA")
                    ).Else(
                        self.bus.w.eq(1),
                        self.bus.di.eq(Cat(data, parity(data))),
                        self.bus.cnt.eq(33),
                        self.bus.ack.eq(1),
                        NextState("CLOCK-IDLE")
                    )
                ).Else(
                    NextState("CLOCK-IDLE")
                )
            )
        )
        self.fsm.act("SWD-READ-DATA",
            If(self.bus.rdy,
                # TODO: check parity
                NextValue(data, reverse(self.bus.do[1:], 32)),
                NextState("FIFO-WRITE-DATA-1")
            )
        )
        for (state, shift, next_state) in (
            ("FIFO-WRITE-DATA-1",  0, "FIFO-WRITE-DATA-2"),
            ("FIFO-WRITE-DATA-2",  8, "FIFO-WRITE-DATA-3"),
            ("FIFO-WRITE-DATA-3", 16, "FIFO-WRITE-DATA-4"),
            ("FIFO-WRITE-DATA-4", 24, "CLOCK-IDLE"),
        ):
            self.fsm.act(state,
                If(in_fifo.writable,
                    in_fifo.we.eq(1),
                    in_fifo.din.eq(data[shift:shift + 8]),
                    NextState(next_state)
                )
            )


class SWDInterface:
    def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, "SWD: " + message, *args)

    async def _init_command(self, command):
        command = bytes(command)
        await self.lower.write(command)
        ack = await self.lower.read(len(command))
        if ack == command:
            self._log("ack")
            return True
        else:
            self._log("nak")
            return False

    async def reset(self):
        self._log("reset probe")
        await self.lower.reset()

        self._log("reset interface")
        await self._init_command([CMD_LINE_RESET])

    async def jtag_to_swd(self):
        self._log("JTAG to SWD")
        await self._init_command([CMD_LINE_RESET, CMD_JTAG_TO_SWD, CMD_LINE_RESET])

    async def _read(self, ap, address):
        self._log("read %s[%d]", "AP" if ap else "DP", address)
        await self.lower.write([ap | (1 << 1) | ((address & 0x3) << 2) | 0x80])
        ack, = await self.lower.read(1)

        if ack != 0b001:
            self._log("nak=%s", "{:03b}".format(ack))
            return None
        else:
            data, = struct.unpack("<L", await self.lower.read(4))
            self._log("ack data=%08x", data)
            return data

    async def _write(self, ap, address, data):
        self._log("write %s[%d] data=<%08x>", "AP" if ap else "DP", address, data)
        await self.lower.write([ap | ((address & 0x3) << 2) | 0x80])
        await self.lower.write(struct.pack("<L", data))

        ack, = await self.lower.read(1)
        if ack != 0b001:
            self._log("nak=%s", "{:03b}".format(ack))
            return False
        else:
            self._log("ack")
            return True

    async def read_ap(self, address):
        return await self._read(ap=True, address=address)

    async def read_dp(self, address):
        return await self._read(ap=False, address=address)

    async def write_ap(self, address, data):
        return await self._write(ap=True, address=address, data=data)

    async def write_dp(self, address, data):
        return await self._write(ap=False, address=address, data=data)


class DebugARMSWDApplet(GlasgowApplet, name="debug-arm-swd"):
    preview = True
    logger = logging.getLogger(__name__)
    help = "debug microcontrollers via SWD"
    description = """
    Debug ARM Cortex microcontrollers via SWD.
    """
    # SWD I/O isn't compatible with A0 level shifters.
    required_revision = "C0"

    __pins = ("clk", "io")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in cls.__pins:
            access.add_pin_argument(parser, pin, default=True)

        parser.add_argument(
            "-b", "--bit-rate", metavar="FREQ", type=int, default=100,
            help="set bit rate to FREQ kHz (default: %(default)s)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(SWDSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(),
            period_cyc=math.ceil(target.sys_clk_freq / (args.bit_rate * 1000))
        ))

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        return SWDInterface(iface, self.logger)

# -------------------------------------------------------------------------------------------------

class DebugARMSWDAppletTestCase(GlasgowAppletTestCase, applet=DebugARMSWDApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
