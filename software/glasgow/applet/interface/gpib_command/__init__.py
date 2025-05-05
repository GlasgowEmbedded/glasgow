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

        self.dio_i  = Signal(8, init=0xFF)  # Data Lines            Listen
        self.dio_o  = Signal(8, init=0xFF)  #                       Talk
        self.eoi_i  = Signal(1, init=1)     # End or Identify       Listen
        self.eoi_o  = Signal(1, init=1)     #                       Talk
        self.dav_i  = Signal(1, init=1)     # Data Valid            Listen
        self.dav_o  = Signal(1, init=1)     #                       Talk
        self.nrfd_i = Signal(1, init=1)     # Not Ready For Data    Talk
        self.nrfd_o = Signal(1, init=1)     #                       Listen
        self.ndac_i = Signal(1, init=1)     # Not Data Accepted     Talk
        self.ndac_o = Signal(1, init=1)     #                       Listen
        self.srq_i  = Signal(1, init=1)     # Service Request       Any
        self.ifc_o  = Signal(1, init=1)     # Interface Clear       Any
        self.atn_o  = Signal(1, init=1)     # Attention             Any
        self.ren_o  = Signal(1, init=1)     # Remote Enable         Any

        self.direction = Signal()  # Talkng (HIGH) or Listening (LOW)

    def elaborate(self, platform):
        m = Module()

        m.submodules.dio_buffer  = dio_buffer  = io.Buffer("io", self.ports.dio)
        m.submodules.eoi_buffer  = eoi_buffer  = io.Buffer("io", self.ports.eoi)
        m.submodules.dav_buffer  = dav_buffer  = io.Buffer("io", self.ports.dav)
        m.submodules.nrfd_buffer = nrfd_buffer = io.Buffer("io", self.ports.nrfd)
        m.submodules.ndac_buffer = ndac_buffer = io.Buffer("io", self.ports.ndac)
        m.submodules.srq_buffer  = srq_buffer  = io.Buffer("i", self.ports.srq)
        m.submodules.ifc_buffer  = ifc_buffer  = io.Buffer("o", self.ports.ifc)
        m.submodules.atn_buffer  = atn_buffer  = io.Buffer("o", self.ports.atn)
        m.submodules.ren_buffer  = ren_buffer  = io.Buffer("o", self.ports.ren)

        # To make the rest of this easier to follow, we can break out
        # the direction into two signals.
        talking   = Signal()
        listening = Signal()
        m.d.comb += [
            talking.eq(self.direction),
            listening.eq(~self.direction),
        ]

        # and use that to determine if an output should be enabled.
        # srq is input only, so it does not get an oe signal.
        m.d.comb += [
            dio_buffer.oe.eq(talking),
            eoi_buffer.oe.eq(talking),
            dav_buffer.oe.eq(talking),
            nrfd_buffer.oe.eq(listening),
            ndac_buffer.oe.eq(listening),
            ifc_buffer.oe.eq(talking),
            atn_buffer.oe.eq(talking),
            ren_buffer.oe.eq(talking),
        ]

        # Some lines never change from the controller's perspective.
        m.d.comb += [
            self.srq_i.eq(srq_buffer.i),
            ifc_buffer.o.eq(self.ifc_o),
            atn_buffer.o.eq(self.atn_o),
            ren_buffer.o.eq(self.ren_o),
        ]

        with m.If(listening):
            m.d.comb += [
                self.dio_i.eq(dio_buffer.i),
                self.eoi_i.eq(eoi_buffer.i),
                self.dav_i.eq(dav_buffer.i),
                nrfd_buffer.o.eq(self.nrfd_o),
                ndac_buffer.o.eq(self.ndac_o),
            ]

        with m.If(talking):
            m.d.comb += [
                dio_buffer.o.eq(self.dio_o),
                eoi_buffer.o.eq(self.eoi_o),
                dav_buffer.o.eq(self.dav_o),
                self.nrfd_i.eq(nrfd_buffer.i),
                self.ndac_i.eq(ndac_buffer.i),
            ]

        return m

class GPIB(Elaboratable):
    def __init__(self, ports, in_fifo, out_fifo):
        self.bus = GPIBBus(ports)
        self.in_fifo  = in_fifo
        self.out_fifo = out_fifo

        self.direction   = Signal(1) # Talk = HIGH,  Listen = LOW
        self.status      = Signal(8)

    def elaborate(self, platform):
        m = Module()

        m.submodules.bus = self.bus
        settle_delay = math.ceil(platform.default_clk_frequency * 1e-6)
        timer = Signal(range(1 + settle_delay))

        m.d.comb += [
            self.bus.direction.eq(self.direction),
            platform.request("led", 0).o.eq(self.status == 0),
            platform.request("led", 1).o.eq(self.status == 1),
            platform.request("led", 2).o.eq(self.status == 2),
            platform.request("led", 3).o.eq(self.status == 4),
            platform.request("led", 4).o.eq(self.status == 8),
        ]

        with m.If(~self.direction):
            with m.FSM():
                with m.State("Listen: Begin"):
                    m.d.sync += [
                        self.bus.ndac_o.eq(0),
                        self.bus.nrfd_o.eq(1),
                        self.status.eq(8),
                    ]
                    with m.If(~self.bus.dav_i):
                        m.d.comb += self.in_fifo.w_en.eq(1)
                        m.d.sync += [
                            self.in_fifo.w_data.eq((self.bus.eoi_i << 1) | 1),
                            self.status.eq(4),
                        ]
                        m.next = "Listen: Wait for control fifo"

                with m.State("Listen: Wait for control fifo"):
                    with m.If(self.in_fifo.w_rdy):
                        m.next = "Listen: Read data lines"

                with m.State("Listen: Read data lines"):
                    m.d.comb += self.in_fifo.w_en.eq(1)
                    m.d.sync += [
                        self.in_fifo.w_data.eq(~self.bus.dio_i),
                        self.bus.nrfd_o.eq(0),
                        self.status.eq(2),
                    ]
                    with m.If(self.in_fifo.w_rdy):
                        m.d.sync += [
                            self.bus.ndac_o.eq(1),
                            self.status.eq(1),
                        ]
                        m.next = "Listen: Wait for DAV unasserted"

                with m.State("Listen: Wait for DAV unasserted"):
                    with m.If(self.bus.dav_i):
                        m.d.sync += [
                            self.bus.ndac_o.eq(0),
                            self.status.eq(0),
                        ]
                        m.next = "Listen: Begin"


        with m.If(self.direction):
            latched = Signal(8)

            with m.FSM(init="Talk: Initialise"):
                with m.State("Talk: Initialise"):
                    m.d.sync += [
                        self.bus.dio_o.eq(0xFF),
                        self.bus.eoi_o.eq(1),
                        self.bus.dav_o.eq(1),
                        self.bus.ifc_o.eq(1),
                        self.bus.atn_o.eq(1),
                        self.bus.ren_o.eq(1),
                    ]
                    m.next = "Talk: Await control"

                with m.State("Talk: Await control"):
                    m.d.sync += self.status.eq(0)
                    m.d.comb += self.out_fifo.r_en.eq(1)
                    with m.If(self.out_fifo.r_rdy):
                        m.d.sync += latched.eq(self.out_fifo.r_data)
                        m.next = "Talk: Set control lines"

                with m.State("Talk: Set control lines"):
                    m.d.sync += [
                        self.bus.ren_o.eq(latched[4]),
                        self.bus.ifc_o.eq(latched[3]),
                        self.bus.eoi_o.eq(latched[1]),
                        self.bus.atn_o.eq(latched[2]),
                        self.bus.dav_o.eq(1),
                        self.status.eq(1),
                    ]
                    with m.If(latched[0]):
                        m.next = "Talk: Await bus ready"
                    with m.If(~latched[0]):
                        m.next = "Talk: Await control"

                with m.State("Talk: Await bus ready"):
                    with m.If(~self.bus.ndac_i):
                        m.next = "Talk: Set data lines"

                with m.State("Talk: Set data lines"):
                    m.d.sync += self.status.eq(2)
                    m.d.comb += self.out_fifo.r_en.eq(1)
                    with m.If(self.out_fifo.r_rdy):
                        m.d.sync += [
                            self.bus.dio_o.eq(~self.out_fifo.r_data),
                            timer.eq(settle_delay),
                        ]
                        m.next = "Talk: Wait for lines to settle"

                with m.State("Talk: Wait for lines to settle"):
                    m.d.sync += timer.eq(timer - 1)
                    with m.If(timer == 0):
                        m.next = "Talk: Tell everyone the data is valid"

                with m.State("Talk: Tell everyone the data is valid"):
                    with m.If(self.bus.nrfd_i):
                        m.d.sync += self.status.eq(4)
                        m.d.sync += self.bus.dav_o.eq(0),
                        m.next = "Talk: Wait for bus acknowledgement"

                with m.State("Talk: Wait for bus acknowledgement"):
                    with m.If(self.bus.ndac_i):
                        m.d.sync += self.status.eq(8)
                        m.next = "Talk: Await control"

        return m

class GPIBSubtarget(Elaboratable):

    def __init__(self, ports, in_fifo, out_fifo, direction, status):
        self.ports     = ports
        self.in_fifo   = in_fifo
        self.out_fifo  = out_fifo
        self.direction = direction
        self.status    = status

        self.gpib = GPIB(ports, in_fifo, out_fifo)

    def elaborate(self, platform):
        m = Module()

        m.submodules.gpib = gpib = self.gpib

        m.d.comb += [
            gpib.direction.eq(self.direction),
            self.status.eq(gpib.status),
        ]

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
        direction, self.__addr_direction = target.registers.add_rw(1)
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
            direction=direction, status=status
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

    async def talk(self, control, data=b""):
        await self._device.set_pulls(self._args.port_spec, high={pin.number for pin in self.talk_pull_high})
        await self._device.write_register(self.__addr_direction, 1)

        if control & 0x01:
            await self._gpib.write([ x for x in data for x in (control, data) ])
        else:
            await self._gpib.write(bytes([control]))

        # for b in data:
        #     self.logger.trace("in->GPIB: control=%s", bin(control))
        #     await self._gpib.write(bytes([control]))
        #     await self._gpib.flush()
        #     if control & 1:
        #         self.logger.trace("in->GPIB: data=%s", bin(b))
        #         await self._gpib.write(bytes([b]))
        #         await self._gpib.flush()

        # if not (control & 1):
        #     self.logger.trace("in->GPIB: control=%s", bin(control))
        #     await self._gpib.write(bytes([control]))
        #     await self._gpib.flush()

    async def listen(self, gpib, to_eoi=False):
        await self._device.set_pulls(self._args.port_spec, high={pin.number for pin in self.listen_pull_high})
        await self._device.write_register(self.__addr_direction, 0)

        if to_eoi:
            eoi = True
            while eoi:
                # eoi = await self._device.read_register(self.__addr_eoi_i)
                status = (await self._gpib.read(1)).tobytes()
                eoi = not ((status >> 1) & 1)
                print(eoi)
                yield (await self._gpib.read(1)).tobytes()
        else:
            yield (await self._gpib.read(1)).tobytes()

        return

    async def interact(self, device, args, gpib):
        self._device = device
        self._args = args
        self._gpib = gpib

        # await device.set_pulls(self._args.port_spec, high={pin.number for pin in self.talk_pull_high})
        # await self._device.write_register(self.__addr_direction, 1)

        DATA = 0b11111
        CMD  = 0b11011
        EOI  = 0b11101
        #REN  = 0b01110
        #IFC  = 0b10110

        if args.command:
            await self.talk(CMD, bytes([CMD_MTA + args.address]))
            # await self.talk(DATA, bytes(args.command.encode("ascii")))
            await self.talk(DATA, b'*')
            await self.talk(DATA, b'I')
            await self.talk(DATA, b'D')
            await self.talk(DATA, b'N')
            await self.talk(DATA, b'?')
            await self.talk(DATA & EOI, b'\n')

        time.sleep(0.5)
        if args.read_eoi:
            async for data in self.listen(True):
                sys.stdout.buffer.write(data)
            # await self.talk(CMD, bytes([CMD_UNL]))

        time.sleep(0.1)

        # if args.command:
        #     await self.talk(CMD, bytes([CMD_UNT]))

    @classmethod
    def tests(cls):
        from . import test
        return test.GPIBCommandAppletTestCase
