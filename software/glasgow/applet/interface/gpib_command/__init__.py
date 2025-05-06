import logging
import argparse
import math
import sys
import time
from amaranth import *
from amaranth.lib import io

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

INTERFACE

In order to accommodate the additional control signals, each word
transmitted requires two bytes. Control lines can be toggled by only
sending one byte.

During transmission, the first byte sent to the FIFO will determine
which bus management lines should be set. If the least significant bit
(TX) is high, the next byte will be the word which gets transmitted.

     BIT     Description
      0      Expect another byte, the word to transmit over the bus.
      1      Raise EOI
      2      Raise ATN
      3      Raise IFC
      4      Raise REN

During receiving, the



TESTING

The applet has been tested with the following pieces of test equipment:

  Tektronix TDS420A Oscilloscope
  Tektronix TDS3014 Oscilloscope
  Rigol DM3068 Multimeter
  HP 1630D Logic Analyser
"""

CMD_MLA = 0x40  # My Listen Address (+ Address)
CMD_MTA = 0x20  # My Talk Address (+ Address)
CMD_PPE = 0x60  # Parallel Poll Enable (+ Secondary Address)
CMD_PPD = 0x70  # Parallel Poll Disable (+ Secondary Address)
CMD_UNL = 0x3F  # Unlisten
CMD_UNT = 0x5F  # Untalk
CMD_SPE = 0x18  # Serial Poll Enable
CMD_SPD = 0x19  # Serial Poll Disable
CMD_LLO = 0x11  # Local Lock Out

class GPIBBus(Elaboratable):
    def __init__(self, ports):
        self.ports = ports

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

        # and use that to determine if an output should be enabled.
        # srq is input only, so it does not get an oe signal.
        m.d.comb += [
            dio_buffer.oe.eq(self.talking),
            eoi_buffer.oe.eq(self.talking),
            dav_buffer.oe.eq(self.talking),
            nrfd_buffer.oe.eq(self.listening),
            ndac_buffer.oe.eq(self.listening),
            ifc_buffer.oe.eq(self.talking),
            atn_buffer.oe.eq(self.talking),
            ren_buffer.oe.eq(self.talking),

            self.srq_i.eq(srq_buffer.i),
            ifc_buffer.o.eq(self.ifc_o),
            atn_buffer.o.eq(self.atn_o),
            ren_buffer.o.eq(self.ren_o),

            self.dio_i.eq(dio_buffer.i),
            self.eoi_i.eq(eoi_buffer.i),
            self.dav_i.eq(dav_buffer.i),
            nrfd_buffer.o.eq(self.nrfd_o),
            ndac_buffer.o.eq(self.ndac_o),

            dio_buffer.o.eq(self.dio_o),
            eoi_buffer.o.eq(self.eoi_o),
            dav_buffer.o.eq(self.dav_o),
            self.nrfd_i.eq(nrfd_buffer.i),
            self.ndac_i.eq(ndac_buffer.i),
        ]

        return m

class GPIBSubtarget(Elaboratable):
    def __init__(self, ports, in_fifo, out_fifo):
        self.bus = GPIBBus(ports)
        self.in_fifo  = in_fifo
        self.out_fifo = out_fifo

        self.status      = Signal(8)

    def elaborate(self, platform):
        m = Module()

        m.submodules.bus = self.bus
        settle_delay = math.ceil(platform.default_clk_frequency * 1e-6)
        timer = Signal(range(1 + settle_delay))

        m.d.comb += [
            platform.request("led", 0).o.eq(self.status == 0),
            platform.request("led", 1).o.eq(self.status == 1),
            platform.request("led", 2).o.eq(self.status == 2),
            platform.request("led", 3).o.eq(self.status == 4),
            platform.request("led", 4).o.eq(self.status == 8),
        ]

        with m.FSM():
            l_control = Signal(8)
            l_data    = Signal(8)

            ctrl_tx     = Signal()
            ctrl_eoi    = Signal()
            ctrl_atn    = Signal()
            ctrl_ifc    = Signal()
            ctrl_ren    = Signal()
            ctrl_listen = Signal()
            ctrl_talk   = Signal()

            m.d.comb += [
                ctrl_tx.eq(l_control[0]),
                ctrl_eoi.eq(l_control[1]),
                ctrl_atn.eq(l_control[2]),
                ctrl_ifc.eq(l_control[3]),
                ctrl_ren.eq(l_control[4]),
                ctrl_listen.eq(l_control[6]),
                ctrl_talk.eq(l_control[7]),
            ]

            with m.State("Control: Check for data"):
                m.d.comb += self.out_fifo.r_en.eq(1)
                with m.If(~self.out_fifo.r_rdy):
                    m.d.sync += l_control.eq(self.out_fifo.r_data)
                    m.next = "Control: Read data byte"

            with m.State("Control: Read data byte"):
                m.d.comb += self.out_fifo.r_en.eq(1)
                with m.If(self.out_fifo.r_rdy):
                    m.d.sync += l_data.eq(self.out_fifo.r_data)
                    m.next = "Control: Parse"

            with m.State("Control: Parse"):
                m.d.sync += [
                    self.bus.talking.eq(ctrl_talk),
                    self.bus.listening.eq(ctrl_listen),
                ]
                with m.If(ctrl_talk & ctrl_listen):
                    m.next = "Control: Error"
                with m.If(ctrl_talk & ~ctrl_listen):
                    m.d.sync += self.status.eq(1)
                    m.next = "Talk: Begin"
                with m.If(ctrl_listen & ~ctrl_talk):
                    m.d.sync += self.status.eq(2)
                    m.next = "Listen: Begin"

            with m.State("Control: Error"):
                m.d.sync += self.status.eq(0)

            with m.State("Control: Acknowledge Transmit"):
                # send a byte back with the MSB set to 1
                m.next = "Control: Check for data"


            with m.State("Talk: Begin"):
                m.d.sync += [
                    self.bus.eoi_o.eq(ctrl_eoi),
                    self.bus.atn_o.eq(ctrl_atn),
                    self.bus.ifc_o.eq(ctrl_ifc),
                    self.bus.ren_o.eq(ctrl_ren),
                    self.bus.dav_o.eq(1),
                ]
                with m.If(~ctrl_tx):
                    m.next = "Control: Check for data"
                with m.If(self.bus.ndac_i & ctrl_tx):
                    m.d.sync += [
                        self.bus.dio_o.eq(l_data),
                        timer.eq(settle_delay),
                    ]
                    m.next = "Talk: DIO Stabalise"

            with m.State("Talk: DIO Stabalise"):
                m.d.sync += timer.eq(timer - 1)
                with m.If(timer == 0):
                    m.next = "Talk: NRFD"

            with m.State("Talk: NRFD"):
                with m.If(~self.bus.nrfd_i):
                    m.d.sync += self.bus.dav_o.eq(1)
                    m.next = "Talk: NDAC"

            with m.State("Talk: NDAC"):
                with m.If(self.bus.ndac_i):
                    m.next = "Control: Acknowledge Transmit"


            with m.State("Listen: Begin"):
                m.d.sync += [
                    self.bus.ndac_o.eq(1),
                    self.bus.nrfd_o.eq(0),
                ]
                with m.If(self.bus.dav_i):
                    m.next = "Listen: Management lines"

            with m.State("Listen: Management lines"):
                m.d.sync += [
                    self.in_fifo.w_data.eq((self.bus.eoi_i << 1) | 1)
                ]
                m.next = "Listen: Management lines acknowledge"

            with m.State("Listen: Management lines acknowledge"):
                m.d.comb += self.in_fifo.w_en.eq(1)
                with m.If(self.in_fifo.w_rdy):
                    m.next = "Listen: DIO lines"

            with m.State("Listen: DIO lines"):
                m.d.sync += [
                    self.in_fifo.w_data.eq(self.bus.dio_i),
                    self.bus.nrfd_o.eq(1),
                ]
                m.next = "Listen: DIO lines acknowledge"

            with m.State("Listen: DIO lines acknowledge"):
                m.d.comb += self.in_fifo.w_en.eq(1)
                with m.If(self.in_fifo.w_rdy):
                    m.d.sync += [
                        self.bus.ndac_o.eq(0),
                    ]
                    m.next = "Listen: DAV unassert"

            with m.State("Listen: DAV unassert"):
                with m.If(~self.bus.dav_i):
                    m.d.sync += [
                        self.bus.ndac_o.eq(1)
                    ]
                    m.next = "Control: Check for data"


        return m

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
            out_fifo=iface.get_out_fifo()
        ))

        self._sample_freq = target.sys_clk_freq

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)


    async def run(self, device, args):
        self.listen_pull_high = default_pull_high = set(args.pin_set_dio).union({
            args.pin_eoi, args.pin_dav
        })
        self.talk_pull_high   = set().union({
            args.pin_nrfd, args.pin_ndac,  args.pin_srq
        })

        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        return iface

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

    async def write(self, control, data=bytes([0])):
        await self._device.set_pulls(self._args.port_spec, high={pin.number for pin in self.talk_pull_high})
        await self._gpib.write(bytes([ x for b in data for x in (control, b) ]))

    async def read(self, gpib, to_eoi=False):
        await self._device.set_pulls(self._args.port_spec, high={pin.number for pin in self.listen_pull_high})

        eoi = True
        while eoi:
            await self.write(0b0100_0000)
            eoi = (await self._gpib.read(1)).tobytes()[0] & 2
            yield (await self._gpib.read(1)).tobytes()

    async def interact(self, device, args, gpib):
        self._device = device
        self._args = args
        self._gpib = gpib

        LISTEN = 0b0100_0000 # 0x40
        DATA   = 0b1001_1111 # 0x9F
        CMD    = 0b1001_1011 # 0x9B
        EOI    = 0b1001_1101 # 0x9D
        #REN   = 0b01110
        #IFC   = 0b10110

        if args.command:
            await self.write(CMD, bytes([CMD_MTA + args.address]))
            await self.write(DATA, bytes(args.command.encode("ascii")))
            # await self.write(DATA, b'*')
            # await self.write(DATA, b'I')
            # await self.write(DATA, b'D')
            # await self.write(DATA, b'N')
            # await self.write(DATA, b'?')
            await self.write(DATA & EOI, b'\n')
            await self.write(CMD, bytes([CMD_MLA + args.address]))

        # await self.write(CMD, bytes([CMD_MLA + args.address]))
        time.sleep(1)

        # time.sleep(0.5)
        if args.read_eoi:
            async for data in self.read(True):
                sys.stdout.buffer.write(data)

        time.sleep(0.1)

        # if args.command:
        #     await self.write(CMD, bytes([CMD_UNT]))

    @classmethod
    def tests(cls):
        from . import test
        return test.GPIBCommandAppletTestCase
