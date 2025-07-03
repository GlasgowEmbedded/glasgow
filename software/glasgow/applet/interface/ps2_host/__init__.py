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
# even worse, them being in-band commands to i8042 itself. This lead mice developers to a quite
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
import asyncio

from amaranth import *
from amaranth.lib import data, io, wiring, stream, cdc
from amaranth.lib.wiring import In, Out

from glasgow.applet import GlasgowAppletV2, GlasgowAppletError


__all__ = ["PS2HostComponent", "PS2HostInterface", "PS2HostError"]


_frame_layout = data.StructLayout({
    "start":  1,
    "data":   8,
    "parity": 1,
    "stop":   1,
})

def _verify_frame(frame):
    return (
        (frame.start == 0) &
        (frame.parity == ~frame.data.xor()) &
        (frame.stop == 1)
    )

def _prepare_frame(frame, data):
    return [
        frame.start.eq(0),
        frame.data.eq(data),
        frame.parity.eq(~data.xor()),
        frame.stop.eq(1),
    ]


class PS2Bus(wiring.Component):
    falling : Out(1)
    rising  : Out(1)
    clock_i : Out(1, init=1)
    clock_o : In(1, init=1)
    data_i  : Out(1, init=1)
    data_o  : In(1, init=1)

    def __init__(self, ports):
        self.ports = ports

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.clock_buffer = clock_buffer = io.Buffer("io", self.ports.clock)
        m.submodules.data_buffer = data_buffer = io.Buffer("io", self.ports.data)
        m.d.comb += [
            clock_buffer.o.eq(0),
            clock_buffer.oe.eq(~self.clock_o),
            data_buffer.o.eq(0),
            data_buffer.oe.eq(~self.data_o)
        ]

        m.submodules += [
            cdc.FFSynchronizer(clock_buffer.i, self.clock_i, init=1),
            cdc.FFSynchronizer(data_buffer.i,  self.data_i,  init=1),
        ]

        clock_s = Signal(init=1)
        clock_r = Signal(init=1)
        m.d.sync += [
            clock_s.eq(self.clock_i),
            clock_r.eq(clock_s),
            self.falling.eq( clock_r & ~clock_s),
            self.rising .eq(~clock_r &  clock_s),
        ]

        if self.ports.reset is not None:
            m.submodules.reset_buffer = reset_buffer = io.Buffer("o", self.ports.reset)
            m.d.comb += reset_buffer.o.eq(ResetSignal())

        return m


class PS2HostController(wiring.Component):
    en      : In(1)  # whether communication should be allowed or inhibited
    stb     : Out(1) # strobed for 1 cycle after each stop bit to indicate an update

    i_valid : In(1)  # whether i_data is to be transmitted
    i_data  : In(8)  # data byte written to device
    i_ack   : Out(1) # whether the device acked the data ("line control" bit)

    o_valid : Out(1) # whether o_data has been received correctly
    o_data  : Out(8) # data byte read from device

    def __init__(self, bus):
        self.bus = bus

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        frame = Signal(_frame_layout)
        bitno = self.bitno = Signal(range(12))
        setup = Signal()
        shift = Signal()
        input = Signal()

        with m.If(setup):
            m.d.sync += self.bus.data_o.eq(frame.as_value()[0])
        with m.If(shift):
            m.d.sync += [
                frame.eq(Cat(frame.as_value()[1:], input)),
                bitno.eq(bitno + 1),
            ]

        with m.FSM():
            with m.State("IDLE"):
                with m.If(self.en):
                    m.d.sync += [
                        *_prepare_frame(frame, self.i_data),
                        self.bus.clock_o.eq(1),
                        bitno.eq(0),
                    ]
                    with m.If(self.i_valid):
                        m.d.comb += [
                            setup.eq(1),
                            shift.eq(1),
                        ]
                        m.next = "SEND-BIT"
                    with m.Else():
                        m.next = "RECV-BIT"
                with m.Else():
                    m.d.sync += [
                        # Inhibit clock
                        self.bus.clock_o.eq(0),
                        self.bus.data_o.eq(1),
                    ]

            with m.State("SEND-BIT"):
                m.d.comb += [
                    input.eq(1),
                    setup.eq(self.bus.falling),
                    shift.eq(self.bus.rising),
                ]
                with m.If(bitno == 12):
                    m.d.comb += self.stb.eq(1)
                    m.d.sync += [
                        bitno.eq(0),
                        # Device acknowledgement ("line control" bit)
                        self.i_ack.eq(~self.bus.data_i),
                    ]
                    m.next = "RECV-BIT"
                with m.If(~self.en):
                    m.next = "IDLE"

            with m.State("RECV-BIT"):
                m.d.comb += [
                    input.eq(self.bus.data_i),
                    shift.eq(self.bus.falling),
                ]
                with m.If(bitno == 11):
                    m.d.comb += self.stb.eq(1),
                    m.d.sync += [
                        bitno.eq(0),
                        self.o_valid.eq(_verify_frame(frame)),
                        self.o_data.eq(frame.data),
                    ]
                with m.If(~self.en):
                    m.next = "IDLE"

        return m


class PS2HostComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))

    def __init__(self, ports, *, inhibit_cyc):
        self._ports = ports
        self._inhibit_cyc = inhibit_cyc

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.bus  = bus  = PS2Bus(self._ports)
        m.submodules.ctrl = ctrl = PS2HostController(bus)

        timer = Signal(range(self._inhibit_cyc))
        count = Signal(7)
        error = Signal()

        with m.FSM():
            with m.State("RECV-COMMAND"):
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    m.d.sync += [
                        count.eq(self.i_stream.payload[:7]),
                        error.eq(0),
                    ]
                    with m.If(self.i_stream.payload[7]):
                        m.d.sync += ctrl.i_valid.eq(1)
                        m.next = "WRITE-BYTE"
                    with m.Else():
                        m.d.sync += [
                            ctrl.i_valid.eq(0),
                            ctrl.en.eq(1),
                        ]
                        m.next = "READ-WAIT"

            with m.State("WRITE-BYTE"):
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    m.d.sync += [
                        ctrl.i_data.eq(self.i_stream.payload),
                        ctrl.en.eq(1),
                    ]
                    m.next = "WRITE-WAIT"
            with m.State("WRITE-WAIT"):
                with m.If(ctrl.stb):
                    m.next = "WRITE-CHECK"
            with m.State("WRITE-CHECK"):
                # Writability not checked to avoid dealing with overflows on host controller side.
                # You better be reading from that FIFO. (But the FIFO is 4× larger than the largest
                # possible command response, so it's never a race.)
                m.d.comb += [
                    self.o_stream.valid.eq(1),
                    self.o_stream.payload.eq(ctrl.i_ack),
                ]
                with m.If((count == 0) | ~ctrl.i_ack):
                    m.next = "INHIBIT"
                with m.Else():
                    m.next = "READ-WAIT"

            with m.State("READ-WAIT"):
                with m.If(count == 0):
                    m.next = "SEND-ERROR"
                with m.Elif(ctrl.stb):
                    m.next = "READ-BYTE"
            with m.State("READ-BYTE"):
                m.d.comb += [
                    self.o_stream.valid.eq(1),
                    self.o_stream.payload.eq(ctrl.o_data),
                ]
                with m.If(~ctrl.o_valid & (error == 0)):
                    m.d.sync += error.eq(count)
                with m.If(count != 0x7f):
                    # Maximum count means an infinite read.
                    m.d.sync += count.eq(count - 1)
                m.next = "READ-WAIT"

            with m.State("SEND-ERROR"):
                m.d.comb += [
                    self.o_stream.valid.eq(1),
                    self.o_stream.payload.eq(error),
                ]
                m.next = "INHIBIT"

            with m.State("INHIBIT"):
                # Make sure the controller has time to react to clock inhibition, in case we are
                # sending two back-to-back commands (or a command and a read, etc).
                m.d.sync += [
                    ctrl.en.eq(0),
                    timer.eq(self._inhibit_cyc - 1),
                ]
                m.next = "INHIBIT-WAIT"

            with m.State("INHIBIT-WAIT"):
                with m.If(timer == 0):
                    m.next = "RECV-COMMAND"
                with m.Else():
                    m.d.sync += timer.eq(timer - 1)

        return m


class PS2HostError(GlasgowAppletError):
    pass


class PS2HostInterface:
    def __init__(self, logger, assembly, *, clock, data, reset):
        self._logger    = logger
        self._level     = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        inhibit_cyc = round(60e-6 / assembly.sys_clk_period)

        ports = assembly.add_port_group(clock=clock, data=data, reset=reset)
        assembly.use_pulls({clock: "high", data: "high"})
        component = assembly.add_submodule(PS2HostComponent(ports, inhibit_cyc=inhibit_cyc))
        self._pipe = assembly.add_inout_pipe(component.o_stream, component.i_stream)

        self._streaming = False

    def _log(self, message, *args):
        self._logger.log(self._level, "PS/2: " + message, *args)

    async def send_command(self, cmd, ret=0):
        assert ret < 0x7f
        assert not self._streaming
        await self._pipe.send([0x80|(ret + 1), cmd])
        await self._pipe.flush()
        line_ack, = await self._pipe.recv(1)
        if not line_ack:
            self._log("cmd=%02x nak", cmd)
            raise PS2HostError("peripheral did not acknowledge command {:#04x}"
                               .format(cmd))
        cmd_ack, *result, error = await self._pipe.recv(1 + ret + 1)
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
            raise PS2HostError(f"peripheral did not accept command {cmd:#04x}")
        else:
            raise PS2HostError(f"peripheral returned unknown response {cmd:#04x}")
        return result

    async def recv_packet(self, ret):
        assert ret < 0x7f
        assert not self._streaming
        await self._pipe.send([ret])
        await self._pipe.flush()
        *result, error = await self._pipe.recv(ret + 1)
        result = bytes(result)
        self._log("ret=<%s>", result.hex())
        if error > 0:
            raise PS2HostError("parity error in byte {} in unsolicited response"
                               .format(error - 1))
        return result

    async def stream(self, callback):
        assert not self._streaming
        self._streaming = True
        await self._pipe.send([0x7f])
        await self._pipe.flush()
        while True:
            await callback(*await self._pipe.recv(1))


class PS2HostApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "communicate with IBM PS/2 peripherals"
    description = """
    Communicate via IBM PS/2 protocol with peripherals such as keyboards and mice.

    A reset pin is optionally supported. This pin will be asserted when the applet is reset, which
    prevents desynchronization. The reset line is not a part of IBM PS/2, but is present on some
    peripherals, such as IBM TrackPoint™ devices.
    """
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "clock", default=True)
        access.add_pins_argument(parser, "data", default=True)
        access.add_pins_argument(parser, "reset")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.ps2_iface = PS2HostInterface(self.logger, self.assembly,
                clock=args.clock, data=args.data, reset=args.reset)

    @classmethod
    def add_run_arguments(cls, parser):
        def hex_bytes(arg):
            return bytes.fromhex(arg)
        parser.add_argument(
            "init", metavar="INIT", type=hex_bytes, nargs="?", default=b"",
            help="send each byte from INIT as an initialization command")

    async def run(self, args):
        for init_byte in args.init:
            await self.ps2_iface.send_command(init_byte)
        async def print_byte(byte):
            print(f"{byte:02x}", end=" ", flush=True)
        await self.ps2_iface.stream(print_byte)

    @classmethod
    def tests(cls):
        from . import test
        return test.PS2HostAppletTestCase
