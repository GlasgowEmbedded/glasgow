import logging
import argparse
import math
import sys
from enum import IntEnum
from amaranth import *
from amaranth.lib import io, data, cdc, wiring, enum

from ... import *

"""
GPIB / IEEE-488 is a 16 line bus, with a single controller (in this case, the
controller will be the Glasgow). The bus can be in one of two modes, depending
on the ATN line (active low). When ATN is low, all other devices on the bus
must listen to the controller. When high, only the addressed device needs to
listen.

The sixteen lines can be broken into three groups. These are the data lines (x8),
the bus management lines (x5) and the handshake lines (x3).

  *** DATA LINES  ***
  DIOx   - There are eight data I/O lines.

  *** BUS MANAGEMENT LINES ***
  ATN    - Attention
           This dictates whether we are in command or data mode.
  EOI    - End-or-Identify
           Any device on the bus can use this to signal the end of binary data, or
           to delimit textual data.
  IFC    - Interface Clear
           Allows the controller to instruct all devices on the bus to reset their
           bus function to the initial state.
  SRQ    - Service Request
           All devices, aside from the controller, can use this line to indicate to
           the controller that something has finished, or that an error has occured.
           When this line is pulled low by a device, the controller should poll to
           find out which device is asking for service and what they want.
  REN    - Remote Enable

  *** HANDSHAKE LINES ***
  DAV    - Data Valid
           A device pulls this line high when it is sending data.
  NRFD   - Not Ready for Data
           A device pulls this line height when data hasn't been fully received yet.
  NDAC   - Not Data Accepted
           A device is not ready to receive data yet.

The NRFD and NDAC lines limit the speed that the bus can run - this
will be determined by the slowest device on the bus. The talker will
pull these lines high, through a resistor. Each listener will pin them
to ground until they are ready for the next step.

Whether the ports are inputs or outputs is dictated by whether the device is
listening or talking.

+--------++------+-----+-----+------+------+--*--+--*--+--*--+--*--+
| Action || DIOx | EOI | DAV | NRFD | NDAC | IFC | SRQ | ATN | REN |
+--------++------+-----+-----+------+------+-----+-----+-----+-----+
| Talk   || OUT  | OUT | OUT | IN   | IN   | OUT | IN  | OUT | OUT |
| Listen || IN   | IN  | IN  | OUT  | OUT  | OUT | IN  | OUT | OUT |
+--------++------+-----+-----+------+------+-----+-----+-----+-----+

All lines use active low signalling. It probably would have made sense to invert the pins.

When a line is marked as an input, it should passively pull up the
line to 5v. Otherwise, the lines voltage should be dictatd by other
devices on the bus.

The applet has been tested with the following pieces of test equipment:

  Tektronix TDS420A Oscilloscope
  Tektronix TDS3014 Oscilloscope
  Rigol DM3068 Multimeter
  HP 1630D Logic Analyser
"""


class GPIBCommand(enum.Enum, shape=8):
    # When the bus is in command mode, these commands can be sent to
    # all devices on the bus. For example, to instruct device 10 to
    # listen to you, you would send MTA + 10.
    MLA = 0x40  # My Listen Address (+ Address)
    MTA = 0x20  # My Talk Address (+ Address)
    PPE = 0x60  # Parallel Poll Enable (+ Secondary Address)
    PPD = 0x70  # Parallel Poll Disable (+ Secondary Address)
    UNL = 0x3F  # Unlisten
    UNT = 0x5F  # Untalk
    SPE = 0x18  # Serial Poll Enable
    SPD = 0x19  # Serial Poll Disable
    LLO = 0x11  # Local Lock Out


class GPIBMessage(enum.IntEnum, shape=8):
    # These are sent prior to any data/commands being sent, and
    # dictate how the controller should handle the data.
    Listen         = 0b0100_0000 # Listen mode, request byte
    Data           = 0b1000_0001 # Normal data byte
    DataEOI        = 0b1000_0011 # Last data byte
    Command        = 0b1000_0101 # Command byte
    InterfaceClear = 0b1000_1000 # Instruct all devices reset their state (e.g. clear errors)

    _Acknowledge   = 0b1000_0000 # Internal - acknowledge that data has been sent


class GPIBStatus(enum.Enum, shape=8):
    Idle    = 0
    Control = 1
    Talk    = 2
    Listen  = 3
    Unknown = 8
    Error   = 16


class GPIBSubtarget(Elaboratable):
    def __init__(self, ports, in_fifo, out_fifo, status):
        self.ports    = ports
        self.in_fifo  = in_fifo
        self.out_fifo = out_fifo
        self.status   = status

        self.dio_i  = Signal(8)  # Data Lines            Listen
        self.dio_o  = Signal(8)  #                       Talk
        self.eoi_i  = Signal(1)  # End or Identify       Listen
        self.eoi_o  = Signal(1)  #                       Talk
        self.dav_i  = Signal(1)  # Data Valid            Listen
        self.dav_o  = Signal(1)  #                       Talk
        self.nrfd_i = Signal(1)  # Not Ready For Data    Talk
        self.nrfd_o = Signal(1)  #                       Listen
        self.ndac_i = Signal(1)  # Not Data Accepted     Talk
        self.ndac_o = Signal(1)  #                       Listen
        self.srq_i  = Signal(1)  # Service Request       Any
        self.ifc_o  = Signal(1)  # Interface Clear       Any
        self.atn_o  = Signal(1)  # Attention             Any
        self.ren_o  = Signal(1)  # Remote Enable         Any

        self.talking   = Signal()
        self.listening = Signal()

    def elaborate(self, platform):
        m = Module()

        m.submodules.dio_buffer  = dio_buffer  = io.Buffer("io", ~self.ports.dio)
        m.submodules.eoi_buffer  = eoi_buffer  = io.Buffer("io", ~self.ports.eoi)
        m.submodules.dav_buffer  = dav_buffer  = io.Buffer("io", ~self.ports.dav)
        m.submodules.nrfd_buffer = nrfd_buffer = io.Buffer("io", ~self.ports.nrfd)
        m.submodules.ndac_buffer = ndac_buffer = io.Buffer("io", ~self.ports.ndac)
        m.submodules.srq_buffer  = srq_buffer  = io.Buffer("i",  ~self.ports.srq)
        m.submodules.ifc_buffer  = ifc_buffer  = io.Buffer("o",  ~self.ports.ifc)
        m.submodules.atn_buffer  = atn_buffer  = io.Buffer("o",  ~self.ports.atn)
        m.submodules.ren_buffer  = ren_buffer  = io.Buffer("o",  ~self.ports.ren)

        m.submodules += [
            cdc.FFSynchronizer(dio_buffer.i,  self.dio_i),
            cdc.FFSynchronizer(eoi_buffer.i,  self.eoi_i),
            cdc.FFSynchronizer(dav_buffer.i,  self.dav_i),
            cdc.FFSynchronizer(nrfd_buffer.i, self.nrfd_i),
            cdc.FFSynchronizer(ndac_buffer.i, self.ndac_i),
            cdc.FFSynchronizer(srq_buffer.i, self.srq_i),
        ]

        m.d.comb += [
            dio_buffer.oe.eq(self.talking),
            eoi_buffer.oe.eq(self.talking),
            dav_buffer.oe.eq(self.talking),
            nrfd_buffer.oe.eq(self.listening),
            ndac_buffer.oe.eq(self.listening),
            ifc_buffer.oe.eq(1),
            atn_buffer.oe.eq(1),
            ren_buffer.oe.eq(1),
        ]
        m.d.comb += [
            dio_buffer.o.eq(self.dio_o),
            eoi_buffer.o.eq(self.eoi_o),
            dav_buffer.o.eq(self.dav_o),
            nrfd_buffer.o.eq(self.nrfd_o),
            ndac_buffer.o.eq(self.ndac_o),
            ifc_buffer.o.eq(self.ifc_o),
            atn_buffer.o.eq(self.atn_o),
            ren_buffer.o.eq(self.ren_o),
        ]

        settle_delay = math.ceil(platform.default_clk_frequency * 1e-6)
        timer = Signal(range(1 + settle_delay))

        m.d.comb += [
            platform.request("led", 0).o.eq(self.status == 0),
            platform.request("led", 1).o.eq(self.status == 1),
            platform.request("led", 2).o.eq(self.status == 2),
            platform.request("led", 3).o.eq(self.status == 4),
            platform.request("led", 4).o.eq(self.status == 8),
        ]

        l_control = Signal(data.StructLayout({
            "tx":     1,
            "eoi":    1,
            "atn":    1,
            "ifc":    1,
            "ren":    1,
            "reserv": 1,
            "listen": 1,
            "talk":   1,
        }))
        l_data    = Signal(8)

        with m.FSM():
            with m.State("Control: Begin"):
                m.d.sync += self.status.eq(GPIBStatus.Idle)
                m.d.comb += self.out_fifo.r_en.eq(1)
                with m.If(self.out_fifo.r_rdy):
                    m.d.sync += l_control.eq(self.out_fifo.r_data)
                    m.next = "Control: Read data"

            with m.State("Control: Read data"):
                m.d.sync += self.status.eq(GPIBStatus.Control)
                m.d.comb += self.out_fifo.r_en.eq(1)
                with m.If(self.out_fifo.r_rdy):
                    m.d.sync += l_data.eq(self.out_fifo.r_data)
                    m.next = "Control: Parse"

            with m.State("Control: Parse"):
                m.d.sync += [
                    self.talking.eq(l_control.talk),
                    self.listening.eq(l_control.listen),
                ]
                with m.If(l_control.talk & l_control.listen):
                    m.next = "Control: Error"
                with m.If(~l_control.talk & ~l_control.listen):
                    m.next = "Control: Begin"
                with m.If(l_control.talk & ~l_control.listen):
                    m.d.sync += self.status.eq(GPIBStatus.Talk)
                    m.next = "Talk: Begin"
                with m.If(l_control.listen & ~l_control.talk):
                    m.d.sync += self.status.eq(GPIBStatus.Listen)
                    m.next = "Listen: Begin"

            with m.State("Control: Error"):
                m.d.sync += self.status.eq(GPIBStatus.Error)

            with m.State("Control: Acknowledge"):
                # Some messages, such as GPIBMessage.Talk, expect an
                # acknowledgement once the operation has completed. In
                # the case of Talk, this ensures that the write
                # operation is blocking, thus preventing the pull up
                # resistor configuration from changing
                # mid-transaction.
                m.d.comb += [
                    self.in_fifo.w_en.eq(1),
                    self.in_fifo.w_data.eq(GPIBMessage._Acknowledge),
                ]
                with m.If(self.in_fifo.w_rdy):
                    m.next = "Control: Begin"

            with m.State("Talk: Begin"):
                m.d.sync += [
                    self.eoi_o.eq(l_control.eoi),
                    self.atn_o.eq(l_control.atn),
                    self.ifc_o.eq(l_control.ifc),
                    self.ren_o.eq(l_control.ren),
                    self.dav_o.eq(0),
                ]
                with m.If(~l_control.tx):
                    m.next = "Control: Acknowledge"
                with m.If(self.ndac_i & l_control.tx):
                    m.d.sync += [
                        self.dio_o.eq(l_data),
                        timer.eq(settle_delay),
                    ]
                    m.next = "Talk: DIO Stabalise"

            with m.State("Talk: DIO Stabalise"):
                m.d.sync += timer.eq(timer - 1)
                with m.If(timer == 0):
                    m.next = "Talk: NRFD"

            with m.State("Talk: NRFD"):
                with m.If(~self.nrfd_i):
                    m.d.sync += self.dav_o.eq(1)
                    m.next = "Talk: NDAC"

            with m.State("Talk: NDAC"):
                with m.If(~self.ndac_i):
                    m.d.sync += self.dav_o.eq(0)
                    m.next = "Control: Acknowledge"

            with m.State("Listen: Begin"):
                m.d.sync += [
                    self.ndac_o.eq(1),
                    self.nrfd_o.eq(0),
                    self.atn_o.eq(0),
                ]
                with m.If(self.dav_i):
                    m.next = "Listen: Management lines"

            with m.State("Listen: Management lines"):
                m.d.comb += [
                    self.in_fifo.w_en.eq(1),
                    self.in_fifo.w_data.eq(Cat(1, self.eoi_i))
                ]
                with m.If(self.in_fifo.w_rdy):
                    m.next = "Listen: DIO lines"

            with m.State("Listen: DIO lines"):
                m.d.comb += [
                    self.in_fifo.w_en.eq(1),
                    self.in_fifo.w_data.eq(self.dio_i),
                ]
                with m.If(self.in_fifo.w_rdy):
                    m.d.sync += self.nrfd_o.eq(0)
                    m.next = "Listen: DAV unassert"

            with m.State("Listen: DAV unassert"):
                with m.If(self.dav_i):
                    m.d.sync += self.ndac_o.eq(0)
                    m.next = "Control: Begin"

        return m


class GPIBControllerInterface:
    def __init__(self, interface, logger, port_spec, listen_pull_high, talk_pull_high):
        self.interface = interface
        self.logger = logger

        self.port_spec = port_spec
        self.listen_pull_high = listen_pull_high
        self.talk_pull_high = talk_pull_high

    async def write(self, message: GPIBMessage, data=bytes([0])):
        await self.interface.device.set_pulls(self.port_spec, high={pin.number for pin in self.talk_pull_high})

        for b in data:
            await self.interface.write(bytes([message.value]))
            await self.interface.write(bytes([b]))
            ack = (await self.interface.read(1))[0]
            assert GPIBMessage(ack) == GPIBMessage._Acknowledge

    async def read(self, to_eoi=True):
        await self.device.set_pulls(self.port_spec, high={pin.number for pin in self.listen_pull_high})

        eoi = False
        while not eoi:
            await self.interface.write(bytes([GPIBMessage.Listen]))
            await self.interface.write(bytes([0]))
            await self.interface.flush()

            eoi = bool((await self.interface.read(1)).tobytes()[0] & 2)
            if not to_eoi:
                eoi = True

            yield (await self.interface.read(1)).tobytes()


class GPIBCommandApplet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "talk to a gpib device"
    description = """
    Talk to a GPIB device
    """
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_set_argument(parser, "dio", width=range(0, 8), default=(0,1,2,3,15,14,13,12))
        access.add_pin_argument(parser, "eoi",  default=4)
        access.add_pin_argument(parser, "dav",  default=5)
        access.add_pin_argument(parser, "nrfd", default=6)
        access.add_pin_argument(parser, "ndac", default=7)
        access.add_pin_argument(parser, "srq",  default=9)
        access.add_pin_argument(parser, "ifc",  default=10)
        access.add_pin_argument(parser, "atn",  default=8)
        access.add_pin_argument(parser, "ren",  default=11)

    def build(self, target, args):
        status,    self.__addr_status    = target.registers.add_ro(8)

        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(GPIBSubtarget(
            ports=iface.get_port_group(
                dio  = args.pin_set_dio,
                eoi  = args.pin_eoi,
                dav  = args.pin_dav,
                nrfd = args.pin_nrfd,
                ndac = args.pin_ndac,
                srq  = args.pin_srq,
                ifc  = args.pin_ifc,
                atn  = args.pin_atn,
                ren  = args.pin_ren,
            ),
            in_fifo=iface.get_in_fifo(),
            out_fifo=iface.get_out_fifo(),
            status=status
        ))

        self._sample_freq = target.sys_clk_freq

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)


    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        gpib_interface = GPIBControllerInterface(
            interface=iface,
            logger=self.logger,
            port_spec=args.port_spec,
            listen_pull_high={*args.pin_set_dio, args.pin_eoi, args.pin_dav},
            talk_pull_high={args.pin_nrfd, args.pin_ndac, args.pin_srq}
        )
        return gpib_interface

    @classmethod
    def add_interact_arguments(cls, parser):
        def check_address(value):
            address = int(value)
            if address < 0 or address > 30:
                raise argparse.ArgumentTypeError("%s is not a correct GPIB address." % address)
            return address

        parser.add_argument(
            "--address", metavar="ADDRESS", type=check_address, default=0,
            help="target GPIB device address")
        parser.add_argument(
            "--command", metavar="CMD",
            help="command to send to target. listen only if empty")
        parser.add_argument(
            "--read-eoi", action="store_true",
            help="read until EOI, omit if no response expected")

    async def interact(self, device, args, iface):
        if args.command:
            await iface.write(GPIBMessage.Command, bytes([GPIBCommand.MTA.value | address]))
            await iface.write(GPIBMessage.Data, bytes(command.encode("ascii")))
            await iface.write(GPIBMessage.DataEOI, b'\n')
            await iface.write(GPIBMessage.Command, bytes([GPIBCommand.UNT.value]))

        if args.read_eoi:
            await gpib.write(GPIBMessage.Command, bytes([GPIBCommand.MLA.value | args.address]))
            async for data in gpib.read(True):
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()

    @classmethod
    def tests(cls):
        from . import test
        return test.GPIBCommandAppletTestCase
