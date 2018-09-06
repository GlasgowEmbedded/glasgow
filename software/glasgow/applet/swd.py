# Reference: https://static.docs.arm.com/ihi0031/c/IHI0031C_debug_interface_as.pdf

import logging
import asyncio
import struct
from migen import *
from migen.fhdl.bitcontainer import value_bits_sign
from migen.genlib.fsm import *

from . import *
from ..gateware.pads import *
from ..pyrepl import *


class SWDBus(Module):
    def __init__(self, pads, bit_rate):
        self.di  = Signal(50)
        self.do  = Signal(33)
        self.w   = Signal()
        self.cnt = Signal(max=max(self.di.nbits, self.do.nbits) + 1)
        self.ack = Signal()
        self.rdy = Signal()

        ###

        clk = Signal(reset=1)
        oe  = Signal(reset=1)
        o   = Signal(reset=1)
        i   = Signal()
        self.comb += [
            pads.clk_t.oe.eq(1),
            pads.clk_t.o.eq(clk)
        ]

        if hasattr(pads, "io_t"):
            self.comb += [
                pads.io_t.oe.eq(oe),
                pads.io_t.o.eq(o),
                i.eq(pads.io_t.i),
            ]
        else:
            # FIXME: remove this branch post revC
            self.comb += [
                pads.o_t.oe.eq(1),
                pads.o_t.o.eq(o),
                i.eq(pads.i_t.i),
            ]

        half_cyc = round(30e6 // (bit_rate * 2))
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
                    NextState("TURN-WRITE")
                ).Elif(~self.w & oe,
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
                    NextValue(oe, 1),
                    NextValue(clk, 1),
                    NextState("FALLING")
                )
            )
        )
        self.fsm.act("TURN-READ",
            If(stb,
                If(clk,
                    NextValue(oe, 0),
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


class SWDSubtarget(Module):
    def __init__(self, pads, out_fifo, in_fifo, bit_rate):
        self.submodules.bus = SWDBus(pads, bit_rate)

        ###

        def parity(sig):
            bits, _ = value_bits_sign(sig)
            return sum([sig[b] for b in range(bits)]) & 1

        cmd = Signal(8)

        self.submodules.fsm = FSM(reset_state="IDLE")
        self.fsm.act("CLOCK-IDLE",
            If(self.bus.rdy,
                If(out_fifo.readable,
                    NextState("IDLE")
                ).Else(
                    self.bus.w.eq(1),
                    self.bus.di.eq(0b00000000),
                    self.bus.cnt.eq(8),
                    self.bus.ack.eq(1),
                )
            )
        )
        self.fsm.act("IDLE",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(cmd, out_fifo.dout),
                NextState("SEND-COMMAND")
            )
        )
        self.fsm.act("SEND-COMMAND",
            If(self.bus.rdy,
                If(cmd == 0xff,
                    self.bus.w.eq(1),
                    self.bus.di.eq((1 << 50) - 1),
                    self.bus.cnt.eq(50),
                    self.bus.ack.eq(1),
                    NextState("QUEUE-RESET")
                ).Elif(cmd == 0xfe,
                    self.bus.w.eq(1),
                    self.bus.di.eq(0xff),
                    self.bus.cnt.eq(8),
                    self.bus.ack.eq(1),
                    NextState("SEND-ALERT-1")
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
                    NextState("RECV-ACK")
                ).Else(
                    NextState("IDLE")
                )
            )
        )
        self.fsm.act("QUEUE-RESET",
            If(in_fifo.writable,
                in_fifo.we.eq(1),
                in_fifo.din.eq(0xff),
                NextState("IDLE")
            )
        )
        for (state, cnt, di, next_state) in (
             ("SEND-ALERT-1", 32, 0b0110_0010_0000_1001_1111_0011_1001_0010, "SEND-ALERT-2"),
             ("SEND-ALERT-2", 32, 0b1000_0110_1000_0101_0010_1101_1001_0101, "SEND-ALERT-3"),
             ("SEND-ALERT-3", 32, 0b1110_0011_1101_1101_1010_1111_1110_1001, "SEND-ALERT-4"),
             ("SEND-ALERT-4", 32, 0b0001_1001_1011_1100_0000_1110_1010_0010, "SEND-ALERT-5"),
             ("SEND-ALERT-5",  4, 0b0000,      "SEND-ALERT-6"),
             ("SEND-ALERT-6",  8, 0b0001_1010, "QUEUE-ALERT"),
        ):
            self.fsm.act(state,
                If(self.bus.rdy,
                    self.bus.w.eq(1),
                    self.bus.di.eq(di),
                    self.bus.cnt.eq(cnt),
                    self.bus.ack.eq(1),
                    NextState(next_state)
                )
            )
        self.fsm.act("QUEUE-ALERT",
            If(in_fifo.writable,
                in_fifo.we.eq(1),
                in_fifo.din.eq(0xfe),
                NextState("IDLE")
            )
        )
        self.fsm.act("RECV-ACK",
            If(self.bus.rdy,
                self.bus.w.eq(0),
                self.bus.cnt.eq(3),
                self.bus.ack.eq(1),
                NextState("CHECK-ACK")
            )
        )
        self.fsm.act("CHECK-ACK",
            If(self.bus.rdy & in_fifo.writable,
                in_fifo.we.eq(1),
                in_fifo.din.eq(self.bus.do & 0b111),
                If((self.bus.do & 0b111) == 0b100,
                    If(cmd & 0b10,
                        self.bus.w.eq(0),
                        self.bus.cnt.eq(33),
                        self.bus.ack.eq(1),
                        NextState("RECV-READ")
                    ).Else(
                        NextState("DEQUEUE-WRITE-1")
                    )
                ).Else(
                    NextState("IDLE")
                )
            )
        )
        self.fsm.act("RECV-READ",
            If(self.bus.rdy,
                NextState("QUEUE-READ-1")
            )
        )
        for (state, shift, next_state) in (
            ("QUEUE-READ-1",  0, "QUEUE-READ-2"),
            ("QUEUE-READ-2",  8, "QUEUE-READ-3"),
            ("QUEUE-READ-3", 16, "QUEUE-READ-4"),
            ("QUEUE-READ-4", 24, "CLOCK-IDLE"),
        ):
            self.fsm.act(state,
                If(in_fifo.writable,
                    in_fifo.we.eq(1),
                    in_fifo.din.eq(self.bus.do[shift:shift + 8]),
                    NextState(next_state)
                )
            )
        for (state, shift, next_state) in (
            ("DEQUEUE-WRITE-1",  0, "DEQUEUE-WRITE-2"),
            ("DEQUEUE-WRITE-2",  8, "DEQUEUE-WRITE-3"),
            ("DEQUEUE-WRITE-3", 16, "DEQUEUE-WRITE-4"),
            ("DEQUEUE-WRITE-4", 24, "SEND-WRITE"),
        ):
            self.fsm.act(state,
                If(out_fifo.readable,
                    out_fifo.re.eq(1),
                    self.bus.di[shift:shift + 8].eq(out_fifo.din),
                    NextState(next_state)
                )
            )
        self.fsm.act("SEND-WRITE",
            self.bus.w.eq(1),
            self.bus.cnt.eq(33),
            self.bus.ack.eq(1),
            NextState("CLOCK-IDLE")
        )


class SWDInterface:
    def __init__(self, interface, logger, addr_reset):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._addr_reset = addr_reset

    def _log(self, message, *args):
        self._logger.log(self._level, "SWD: " + message, *args)

    async def reset(self):
        self._log("reset probe")
        await self.lower.device.write_register(self._addr_reset, 1)
        await self.lower.device.write_register(self._addr_reset, 0)

        self._log("reset interface")
        await self.lower.write([0xff])
        ack, = await self.lower.read(1)
        if ack == 0xff:
            self._log("ack")
            return True
        else:
            self._log("nak")
            return False

    async def dormant_to_swd(self):
        self._log("dormant to swd")
        await self.lower.write([0xfe])
        ack, = await self.lower.read(1)
        if ack == 0xfe:
            self._log("ack")
            return True
        else:
            self._log("nak")
            return False

    async def _read(self, ap, address):
        self._log("read %s[%d]", "AP" if ap else "DP", address)
        await self.lower.write([ap | (1 << 1) | ((address & 0x3) << 2) | 0x80])
        ack, = await self.lower.read(1)
        if ack != 0b100:
            self._log("nak=%s", "{:03b}".format(ack))
            return None
        else:
            data, = struct.unpack("<L", await self.lower.read(4))
            self._log("ack data=%08x", data)
            return data

    async def _write(self, ap, address, data):
        self._log("write %s[%d]", "AP" if ap else "DP", address)
        await self.lower.write([ap | ((address & 0x3) << 2) | 0x80])
        ack, = await self.lower.read(1)
        if ack != 0b100:
            self._log("nak=%s", "{:03b}".format(ack))
            return False
        else:
            await self.lower.write(struct.pack("<L", data))
            await self.lower.flush()
            self._log("ack data=%08x", data)
            return True

    async def read_ap(self, address):
        return await self._read(ap=True, address=address)

    async def read_dp(self, address):
        return await self._read(ap=False, address=address)

    async def write_ap(self, address, data):
        return await self._write(ap=True, address=address, data=data)

    async def write_dp(self, address, data):
        return await self._write(ap=False, address=address, data=data)


class SWDApplet(GlasgowApplet, name="swd"):
    logger = logging.getLogger(__name__)
    help = "debug microcontrollers via SWD"
    description = """
    Debug ARM Cortex microcontrollers via SWD.
    """

    __pins = ("clk", "io", "i", "o")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        # FIXME: uncomment this post revC
        # for pin in cls.__pins:
        #     access.add_pin_argument(parser, pin, default=True)
        access.add_pin_argument(parser, "clk", default=True)
        access.add_pin_argument(parser, "io")
        access.add_pin_argument(parser, "o")
        access.add_pin_argument(parser, "i")

        parser.add_argument(
            "-b", "--bit-rate", metavar="FREQ", type=int, default=100,
            help="set bit rate to FREQ kHz (default: %(default)s)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = ResetInserter()(SWDSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(streaming=False),
            bit_rate=args.bit_rate * 1000,
        ))
        target.submodules += subtarget

        reset, self.__addr_reset = target.registers.add_rw(1)
        target.comb += subtarget.reset.eq(reset)

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        return SWDInterface(iface, self.logger, self.__addr_reset)

    async def interact(self, device, args, swd_iface):
        await AsyncInteractiveConsole(locals={"swd_iface": swd_iface}).interact()

# -------------------------------------------------------------------------------------------------

class SWDAppletTestCase(GlasgowAppletTestCase, applet=SWDApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
