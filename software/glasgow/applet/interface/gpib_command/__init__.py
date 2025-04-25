import logging
import argparse
import math
import sys
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

Tested against:
  Tektronix TDS420A
  Tektronix TDS3014
"""

CMD_MLA = 0x40  # My Listen Address
CMD_MTA = 0x20  # My Talk Address

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

        self.eoi_i       = Signal(1)
        self.eoi_o       = Signal(1)
        self.atn_o       = Signal(1)
        self.ifc_o       = Signal(1)

    def elaborate(self, platform):
        m = Module()

        m.submodules.bus = self.bus
        settle_delay = math.ceil(platform.default_clk_frequency * 3e-6)
        timer = Signal(range(1 + settle_delay))

        # Some signals need to be accessible as registers.
        # EOI       - Allows the interact know when it should stop reading
        # Direction - Determines whether we are listening or talking.
        #             The state of pull up resistors is handled by interact.
        # ATN       - When active, puts the GPIB into Command mode.
        m.d.comb += [
            self.bus.eoi_o.eq(self.eoi_o),
            self.bus.direction.eq(self.direction),
            self.bus.atn_o.eq(self.atn_o),
            self.bus.ifc_o.eq(self.ifc_o),
        ]

        m.d.comb += [
            platform.request("led", 0).o.eq(self.direction),
            platform.request("led", 1).o.eq(0),
            platform.request("led", 2).o.eq(0),
            platform.request("led", 3).o.eq(0),
            platform.request("led", 4).o.eq(~self.direction),
        ]

        with m.If(~self.direction):
            with m.FSM():
                with m.State("Listen: Begin"):
                    m.d.sync += [
                        self.bus.ndac_o.eq(0),
                        self.bus.nrfd_o.eq(1),
                        self.eoi_i.eq(self.bus.eoi_i),
                    ]
                    with m.If(~self.bus.dav_i):
                        m.next = "Listen: Read data lines"

                with m.State("Listen: Read data lines"):
                    m.d.comb += self.in_fifo.w_en.eq(1)
                    m.d.sync += [
                        self.in_fifo.w_data.eq(~self.bus.dio_i),
                        self.bus.nrfd_o.eq(0),
                        self.eoi_i.eq(self.bus.eoi_i)
                    ]
                    with m.If(self.in_fifo.w_rdy):
                        m.d.sync += [
                            self.bus.ndac_o.eq(1),
                        ]
                        m.next = "Listen: Wait for DAV unasserted"

                with m.State("Listen: Wait for DAV unasserted"):
                    with m.If(self.bus.dav_i):
                        m.d.sync += self.bus.ndac_o.eq(0),
                        m.next = "Listen: Begin"

        with m.If(self.direction):
            with m.FSM():
                with m.State("Talk: Begin"):
                    m.d.sync += [
                        self.bus.dav_o.eq(1),
                        self.bus.ren_o.eq(1),
                    ]
                    with m.If(~self.bus.ndac_i):
                        m.next = "Talk: Set data lines"

                with m.State("Talk: Set data lines"):
                    m.d.comb += self.out_fifo.r_en.eq(1)
                    with m.If(self.out_fifo.r_rdy):
                        m.d.sync += self.bus.dio_o.eq(~self.out_fifo.r_data)
                        m.d.sync += timer.eq(settle_delay),
                        m.next = "Talk: Wait for lines to settle"

                with m.State("Talk: Wait for lines to settle"):
                    m.d.sync += timer.eq(timer - 1)
                    with m.If(timer == 0):
                        m.next = "Talk: Wait for NRFD unasserted"

                with m.State("Talk: Wait for NRFD unasserted"):
                    with m.If(self.bus.nrfd_i):
                        m.d.sync += self.bus.dav_o.eq(0),
                        m.next = "Talk: Await NDAC asserted"

                with m.State("Talk: Await NDAC asserted"):
                    with m.If(self.bus.ndac_i):
                        m.next = "Talk: Begin"

        return m

class GPIBSubtarget(Elaboratable):

    def __init__(self, ports, in_fifo, out_fifo, eoi_o, eoi_i, atn, ifc, direction):
        self.ports     = ports
        self.in_fifo   = in_fifo
        self.out_fifo  = out_fifo
        self.eoi_o     = eoi_o
        self.eoi_i     = eoi_i
        self.atn       = atn
        self.ifc       = ifc
        self.direction = direction

        self.gpib = GPIB(ports, in_fifo, out_fifo)

    def elaborate(self, platform):
        m = Module()

        m.submodules.gpib = gpib = self.gpib

        m.d.comb += [
            self.eoi_i.eq(gpib.eoi_i),
            gpib.eoi_o.eq(self.eoi_o),
            gpib.atn_o.eq(self.atn),
            gpib.ifc_o.eq(self.ifc),
            gpib.direction.eq(self.direction),
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
        eoi_o,     self.__addr_eoi_o     = target.registers.add_rw(1)
        eoi_i,     self.__addr_eoi_i     = target.registers.add_ro(1)
        atn,       self.__addr_atn       = target.registers.add_rw(1)
        direction, self.__addr_direction = target.registers.add_rw(1)
        ifc,       self.__addr_ifc       = target.registers.add_rw(1)

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
            eoi_o=eoi_o, eoi_i=eoi_i, atn=atn, ifc=ifc, direction=direction
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
            help="targer GPIB device address")
        parser.add_argument(
            "--command", metavar="CMD",
            help="command to send to target. listen only if empty")
        parser.add_argument(
            "--read-eoi", action="store_true",
            help="read until EOI, omit if no response expected")

    async def talk(self, device, args, gpib, data):
        await device.set_pulls(args.port_spec, high={pin.number for pin in self.talk_pull_high})
        await device.write_register(self.__addr_direction, 1)

        await gpib.write(data)
        await gpib.flush()

    async def listen(self, device, args, gpib, to_eoi=False):
        await device.set_pulls(args.port_spec, high={pin.number for pin in self.listen_pull_high})
        await device.write_register(self.__addr_direction, 0)

        if to_eoi:
            eoi = True
            while eoi:
                eoi = await device.read_register(self.__addr_eoi_i)
                yield (await gpib.read()).tobytes()
        else:
            yield (await gpib.read()).tobytes()

        return

    async def command(self, device, args, gpib, command):
        await device.write_register(self.__addr_atn, 0)
        await self.talk(device, args, gpib, command)
        await device.write_register(self.__addr_atn, 1)


    async def interact(self, device, args, gpib):
        await device.write_register(self.__addr_eoi_o, 1)
        await device.write_register(self.__addr_atn, 1)
        await device.write_register(self.__addr_ifc, 1)

        if args.command:
            await self.command(device, args, gpib, bytes([CMD_MTA + args.address]))
            await self.talk(device, args, gpib, bytes(args.command.encode("ascii")))
            await device.write_register(self.__addr_eoi_o, 0)
            await self.talk(device, args, gpib, b'\n')
            await device.write_register(self.__addr_eoi_o, 1)

        await self.command(device, args, gpib, bytes([CMD_MLA + args.address]))

        if args.read_eoi:
            async for data in self.listen(device, args, gpib, True):
                sys.stdout.buffer.write(data)

    @classmethod
    def tests(cls):
        from . import test
        return test.GPIBCommandAppletTestCase
