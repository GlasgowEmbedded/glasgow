# Ref: IBM PS/2 Hardware Technical Reference ­- Keyboard and Auxiliary Device Controller
# Accession: G00031
# Ref: IBM PS/2 Hardware Technical Reference ­- Keyboards (101- and 102-Key)
# Accession: G00037

# PS/2 Physical Layer
# -------------------
#
# The physical layer as described in IBM PS/2 Hardware Technical Reference is reminiscent of
# half-duplex SPI, but this comparison is misleading. In fact, tracing the communication of PS/2
# devices, one can notice that sample/setup points appear to be shifted 90° in phase compared to
# the clock, i.e. they are not edge triggered. This is similar to how an I²C master should be
# implemented (but often isn't). The IBM keyboard reference describes that "Data is valid before
# the trailing edge and beyond the leading edge of the clock pulse", so the host may sample at
# either edge or anywhere during the low half-period of the clock.
#
# PS/2 Protocol Framing
# ---------------------
#
# It is often asserted in materials about the PS/2 protocol with varying degrees of confidence
# that the protocol is byte-oriented. This is, essentially, false. The protocol is packet-oriented,
# with the host always sending 1-byte packets, and the device responding with fixed-size packets,
# although the packet size is not always known in advance, e.g. in case of the identification data
# and keyboard scan codes.
#
# The host and the device may synchronize by using the fact that the device will always interrupt
# the current packet it is sending, whether solicited or unsolicited, and start processing
# the newly sent command. While well-defined on protocol level, lack of explicit frame boundaries
# is a significant problem for a system employing extensive device-, OS- and application-level
# buffering like Glasgow, since it is impossible to say apriori whether the byte that was just
# received is in response to a command or not. (Explicit sequence points would fix a half of this
# problem, but are not completely robust when combined with variable length responses and packets
# sent unsolicited by the device.)
#
# The Intel 8042 controller fixes, or rather works around, this problem by completely encapsulating
# the handling of PS/2. In fact many (if not most) PS/2 commands that are sent to i8042 result in
# no PS/2 traffic at all, with their response being either synthesized on the fly on the i8042, or,
# even worse, them being an in-band commands to i8042 itself. This lead mice developers to a quite
# horrifying response: any advanced settings are conveyed to the mouse and back by abusing
# the sensitivity adjustment commands as 2-bit at a time a communication channel; keyboards use
# similar hacks.
#
# In this applet, we solve this problem by treating the PS/2 device rather harshly: it is only
# allowed to speak when we permit it to, i.e. all communication is host-initiated. (This is quite
# awkward when combined with the clock being device-generated...) Each time the host initiates
# a communication, it optionally sends a command byte (all commands are single byte), and receives
# exactly as many response bytes as a higher layer determines is necessary, then inhibits
# the clock. As a result, the command responses that are longer than expected are cut short (but
# the higher layer cannot process them anyway), and unsolicited packets are dropped when they are
# not actively polled by a higher layer. In exchange, the communication is always deterministic.
#
# PS/2 Command Assignment
# -----------------------
#
# Observing the assignment of keyboard and mouse commands in PS/2, it might be deduced that in-band
# i8042 controller commands were assigned from 00 upwards, that keyboard commands were assigned
# from FF downwards, and the auxiliary device (mouse, etc) commands were assigned the same numbers
# as keyboard commands when there was an equivalent one, or from EB downwards, lowest assigned
# keyboard command being EC (Reset Wrap Mode). See the respective keyboard and mouse applets for
# details on the command set.

import logging
import operator
import asyncio
from nmigen.compat import *
from nmigen.compat.genlib.cdc import MultiReg
from nmigen.compat.genlib.fifo import SyncFIFOBuffered

from ... import *


_frame_layout = [
    ("start",  1),
    ("data",   8),
    ("parity", 1),
    ("stop",   1),
]

def _verify_frame(frame):
    return (
        (frame.start == 0) &
        (frame.parity == ~reduce(operator.xor, frame.data)) &
        (frame.stop == 1)
    )

def _prepare_frame(frame, data):
    return [
        NextValue(frame.start,  0),
        NextValue(frame.data,   data),
        NextValue(frame.parity, ~reduce(operator.xor, data)),
        NextValue(frame.stop,   1),
    ]


class PS2Bus(Module):
    def __init__(self, pads):
        self.falling = Signal()
        self.rising  = Signal()
        self.clock_i = Signal(reset=1)
        self.clock_o = Signal(reset=1)
        self.data_i  = Signal(reset=1)
        self.data_o  = Signal(reset=1)

        ###

        self.comb += [
            pads.clock_t.o.eq(0),
            pads.clock_t.oe.eq(~self.clock_o),
            pads.data_t.o.eq(0),
            pads.data_t.oe.eq(~self.data_o),
        ]
        self.specials += [
            MultiReg(pads.clock_t.i, self.clock_i, reset=1),
            MultiReg(pads.data_t.i,  self.data_i,  reset=1),
        ]

        clock_s = Signal(reset=1)
        clock_r = Signal(reset=1)
        self.sync += [
            clock_s.eq(self.clock_i),
            clock_r.eq(clock_s),
            self.falling.eq( clock_r & ~clock_s),
            self.rising .eq(~clock_r &  clock_s),
        ]


class PS2HostController(Module):
    def __init__(self, bus):
        self.en      = Signal()  # whether communication should be allowed or inhibited
        self.stb     = Signal()  # strobed for 1 cycle after each stop bit to indicate an update

        self.i_valid = Signal()  # whether i_data is to be transmitted
        self.i_data  = Signal(8) # data byte written to device
        self.i_ack   = Signal()  # whether the device acked the data ("line control" bit)

        self.o_valid = Signal()  # whether o_data has been received correctly
        self.o_data  = Signal(8) # data byte read from device

        ###

        frame = Record(_frame_layout)
        bitno = self.bitno = Signal(max=12)
        setup = Signal()
        shift = Signal()
        input = Signal()
        self.sync += [
            If(setup,
                bus.data_o.eq(frame.raw_bits()[0])
            ),
            If(shift,
                frame.raw_bits().eq(Cat(frame.raw_bits()[1:], input)),
                bitno.eq(bitno + 1),
            )
        ]

        self.submodules.fsm = FSM()
        self.fsm.act("IDLE",
            If(self.en,
                _prepare_frame(frame, self.i_data),
                NextValue(bus.clock_o, 1),
                NextValue(bitno, 0),
                If(self.i_valid,
                    setup.eq(1),
                    shift.eq(1),
                    NextState("SEND-BIT")
                ).Else(
                    NextState("RECV-BIT")
                )
            ).Else(
                # Inhibit clock
                NextValue(bus.clock_o, 0),
                NextValue(bus.data_o,  1),
            )
        )
        self.fsm.act("SEND-BIT",
            input.eq(1),
            setup.eq(bus.falling),
            shift.eq(bus.rising),
            If(bitno == 12,
                self.stb.eq(1),
                NextValue(bitno, 0),
                # Device acknowledgement ("line control" bit)
                NextValue(self.i_ack, ~bus.data_i),
                NextState("RECV-BIT")
            ),
            If(~self.en,
                NextState("IDLE"),
            )
        )
        self.fsm.act("RECV-BIT",
            input.eq(bus.data_i),
            shift.eq(bus.falling),
            If(bitno == 11,
                self.stb.eq(1),
                NextValue(bitno, 0),
                NextValue(self.o_valid, _verify_frame(frame)),
                NextValue(self.o_data, frame.data),
            ),
            If(~self.en,
                NextState("IDLE"),
            )
        )


class PS2HostSubtarget(Module):
    def __init__(self, pads, in_fifo, out_fifo, inhibit_cyc):
        self.submodules.bus  = bus  = PS2Bus(pads)
        self.submodules.ctrl = ctrl = PS2HostController(bus)

        timer = Signal(max=inhibit_cyc)
        count = Signal(7)
        error = Signal()

        self.submodules.fsm = FSM()
        self.fsm.act("RECV-COMMAND",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(count, out_fifo.dout[:7]),
                NextValue(error, 0),
                If(out_fifo.dout[7],
                    NextValue(ctrl.i_valid, 1),
                    NextState("WRITE-BYTE")
                ).Else(
                    NextValue(ctrl.i_valid, 0),
                    NextValue(ctrl.en, 1),
                    NextState("READ-WAIT")
                )
            )
        )
        self.fsm.act("WRITE-BYTE",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(ctrl.i_data, out_fifo.dout),
                NextValue(ctrl.en, 1),
                NextState("WRITE-WAIT")
            )
        )
        self.fsm.act("WRITE-WAIT",
            If(ctrl.stb,
                NextState("WRITE-CHECK")
            )
        )
        self.fsm.act("WRITE-CHECK",
            # Writability not checked to avoid dealing with overflows on host controller side.
            # You better be reading from that FIFO. (But the FIFO is 4× larger than the largest
            # possible command response, so it's never a race.)
            in_fifo.we.eq(1),
            in_fifo.din.eq(ctrl.i_ack),
            If((count == 0) | ~ctrl.i_ack,
                NextState("INHIBIT")
            ).Else(
                NextState("READ-WAIT")
            )
        )
        self.fsm.act("READ-WAIT",
            If(count == 0,
                NextState("SEND-ERROR")
            ).Elif(ctrl.stb,
                NextState("READ-BYTE")
            ),
        )
        self.fsm.act("READ-BYTE",
            in_fifo.we.eq(1),
            in_fifo.din.eq(ctrl.o_data),
            If(~ctrl.o_valid & (error == 0),
                NextValue(error, count),
            ),
            If(count != 0x7f,
                # Maximum count means an infinite read.
                NextValue(count, count - 1),
            ),
            NextState("READ-WAIT")
        )
        self.fsm.act("SEND-ERROR",
            in_fifo.we.eq(1),
            in_fifo.din.eq(error),
            NextState("INHIBIT")
        )
        self.fsm.act("INHIBIT",
            # Make sure the controller has time to react to clock inhibition, in case we are
            # sending two back-to-back commands (or a command and a read, etc).
            NextValue(ctrl.en, 0),
            NextValue(timer, inhibit_cyc),
            NextState("INHIBIT-WAIT")
        )
        self.fsm.act("INHIBIT-WAIT",
            If(timer == 0,
                NextState("RECV-COMMAND")
            ).Else(
                NextValue(timer, timer - 1)
            )
        )


class PS2HostError(GlasgowAppletError):
    pass


class PS2HostInterface:
    def __init__(self, interface, logger):
        self._lower     = interface
        self._logger    = logger
        self._level     = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._streaming = False

    def _log(self, message, *args):
        self._logger.log(self._level, "PS/2: " + message, *args)

    async def send_command(self, cmd, ret=0):
        assert ret < 0x7f
        assert not self._streaming
        await self._lower.write([0x80|(ret + 1), cmd])
        line_ack, = await self._lower.read(1)
        if not line_ack:
            self._log("cmd=%02x nak", cmd)
            raise PS2HostError("peripheral did not acknowledge command {:#04x}"
                               .format(cmd))
        cmd_ack, *result, error = await self._lower.read(1 + ret + 1)
        result = bytes(result)
        self._log("cmd=%02x ack=%02x ret=<%s>", cmd, cmd_ack, result.hex())
        if error > 0:
            raise PS2HostError("parity error in byte {} in response to command {:#04x}"
                               .format(error - 1, cmd))
        if cmd_ack in (0xfa, 0xee): # ACK
            pass
        elif cmd_ack in (0xfe, 0xfc, 0xfd): # NAK
            # Response FE means resend according to the protocol, but really it means that
            # the peripheral did not like our command. Parity errors are rare, so resending
            # the command is probably a waste of time and we'll just get FC in response
            # the second time anyway; and after getting FC (unlike FE) we are required to reset
            # the device and try again, which the downstream code probably doesn't want in
            # the first place. (Some devices will reset themselves after sending FC.)
            #
            # In practice treating FE and FC the same seems to be the best option.
            raise PS2HostError("peripheral did not accept command {:#04x}".format(cmd))
        else:
            raise PS2HostError("peripheral returned unknown response {:#04x}".format(cmd))
        return result

    async def recv_packet(self, ret):
        assert ret < 0x7f
        assert not self._streaming
        await self._lower.write([ret])
        *result, error = await self._lower.read(ret + 1)
        result = bytes(result)
        self._log("ret=<%s>", result.hex())
        if error > 0:
            raise PS2HostError("parity error in byte {} in unsolicited response"
                               .format(error - 1))
        return result

    async def stream(self, callback):
        assert not self._streaming
        await self._lower.write([0x7f])
        while True:
            await callback(*await self._lower.read(1))


class PS2HostApplet(GlasgowApplet, name="ps2-host"):
    logger = logging.getLogger(__name__)
    help = "communicate with IBM PS/2 peripherals"
    description = """
    Communicate via IBM PS/2 protocol with peripherals such as keyboards and mice.

    A reset pin is optionally supported. This pin will be asserted when the applet is reset, which
    prevents desynchronization. The reset line is not a part of IBM PS/2, but is present on some
    peripherals, such as IBM TrackPoint™ devices.
    """
    required_revision = "C0"

    __pins = ("clock", "data")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in cls.__pins:
            access.add_pin_argument(parser, pin, default=True)
        access.add_pin_argument(parser, "reset")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(PS2HostSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            in_fifo=iface.get_in_fifo(),
            out_fifo=iface.get_out_fifo(),
            inhibit_cyc=int(target.sys_clk_freq * 60e-6),
        ))
        if args.pin_reset is not None:
            reset_t = self.mux_interface.get_pin(args.pin_reset, name="reset")
            subtarget.comb += [
                reset_t.o.eq(subtarget.reset),
                reset_t.oe.eq(1),
            ]

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args,
            pull_high={args.pin_clock, args.pin_data})
        return PS2HostInterface(iface, self.logger)

    @classmethod
    def add_interact_arguments(cls, parser):
        def hex_bytes(arg):
            return bytes.fromhex(arg)
        parser.add_argument(
            "init", metavar="INIT", type=hex_bytes, nargs="?", default=b"",
            help="send each byte from INIT as an initialization command")

    async def interact(self, device, args, iface):
        for init_byte in args.init:
            await iface.send_command(init_byte)
        async def print_byte(byte):
            print("{:02x}".format(byte), end=" ", flush=True)
        await iface.stream(print_byte)

# -------------------------------------------------------------------------------------------------

class PS2HostAppletTestCase(GlasgowAppletTestCase, applet=PS2HostApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
