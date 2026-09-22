# Ref: Configuring Trion FPGAs
# Document Number: AN006
# Accession: G00133
#
# Ref: Configuring Titanium FPGAs
# Document Number: AN033
# Accession: G00134

from collections.abc import Buffer
import argparse
import asyncio

from amaranth import *
from amaranth.lib import io, enum, wiring, stream, data
from amaranth.lib.wiring import In, Out
from amaranth.utils import exact_log2

from glasgow.support import logging
from glasgow.abstract import AbstractAssembly, GlasgowPin, ClockDivisor

from glasgow.gateware.iostream import IOStreamer
from glasgow.gateware.cobs import encode, Decoder
from glasgow.gateware.ports import PortGroup

from glasgow.applet import GlasgowAppletError, GlasgowAppletV2
from glasgow.applet.control.gpio import GPIOInterface


T_RESET_MIN = 320e-9
T_DATA_MIN  = 1.2e-6
C_DUMMY_MIN = 128


__all__ = ["EfinixSRAMInterface"]


class Operation(enum.Enum, shape=3):
    RESET    = 0
    SETUP    = 1
    PUT      = 2
    DUMMY    = 3
    FINALIZE = 4


class Status(enum.Enum, shape=2):
    SHIFTED   = 0
    WAITING   = 1
    FINALIZED = 2


class Deframer(wiring.Component):
    def __init__(self, ports):
        super().__init__({
            "frames": In(IOStreamer.o_signature(
                ports, ratio=2, meta_layout=data.StructLayout({"finalize": 1, "shifted": 1})
            )),
            "o": Out(stream.Signature(Status)),
        })

    def elaborate(self, platform):
        m = Module()
        m.d.comb += self.frames.ready.eq(1)

        with m.If(self.frames.valid):
            m.d.comb += Assert(~(self.frames.p.meta.finalize & self.frames.p.meta.shifted))
            with m.If(self.frames.p.meta.shifted):
                m.d.comb += [
                    self.o.valid.eq(self.frames.valid),
                    self.frames.ready.eq(self.o.ready),
                    self.o.payload.eq(Status.SHIFTED),
                ]
            with m.Elif(self.frames.p.meta.finalize):
                m.d.comb += [
                    self.o.valid.eq(self.frames.valid),
                    self.frames.ready.eq(self.o.ready),
                ]
                if len(self.frames.p.port.cdone.i[1]) != 0:
                    with m.If(self.frames.p.port.cdone.i[1]):
                        m.d.comb += self.o.payload.eq(Status.FINALIZED)
                    with m.Else():
                        m.d.comb += self.o.payload.eq(Status.WAITING)
                else:
                    m.d.comb += self.o.payload.eq(Status.FINALIZED)

        return m


class Enframer(wiring.Component):
    def __init__(self, ports):
        super().__init__({
            "octets": In(stream.Signature(data.StructLayout({
                "oper": Operation,
                "data": 8
            }))),
            "frames": Out(IOStreamer.i_signature(
                ports, ratio=2,
                meta_layout=data.StructLayout({"finalize": 1, "shifted": 1})
            )),
            "divisor": In(16),
        })

    def elaborate(self, platform):
        m = Module()

        width = len(self.frames.p.port.cdi.o[0])
        cycle = Signal(range(8 // width), init=0)
        timer = Signal.like(self.divisor)

        # CDONE is open drain and can be held low to prevent the FPGA from
        # entering user mode until all the config pins are tristated
        m.d.comb += [
            self.frames.p.port.cs   .o   .eq(0b11),
            self.frames.p.port.cdone.o   .eq(0b00),
            self.frames.p.port.cck  .o   .eq(0b11),
            self.frames.p.port.cdi  .o[0].eq(0xff),
            self.frames.p.port.cdi  .o[1].eq(0xff),
            self.frames.p.port.cbus .o[0].eq(~Const(exact_log2(width), 3)),
            self.frames.p.port.cbus .o[1].eq(~Const(exact_log2(width), 3)),
        ]

        # MSB first but lower bits on lower pins when in wide mode
        data = self.octets.p.data[::-1]
        with m.Switch(self.octets.p.oper):
            with m.Case(Operation.RESET):
                m.d.comb += [
                    self.frames.p.port.reset.oe.eq(1),

                    self.frames.p.port.reset.o .eq(0b11),
                ]
            with m.Case(Operation.SETUP):
                m.d.comb += [
                    self.frames.p.port.reset.oe.eq(1),
                    self.frames.p.port.cs   .oe.eq(1),
                    self.frames.p.port.cdone.oe.eq(1),
                    self.frames.p.port.cbus .oe.eq(1),
                    self.frames.p.port.cck  .oe.eq(1),
                    self.frames.p.port.cdi  .oe.eq(1),

                    self.frames.p.port.reset.o   .eq(data),
                ]
            with m.Case(Operation.PUT):
                m.d.comb += [
                    self.frames.p.port.reset.oe.eq(1),
                    self.frames.p.port.cs   .oe.eq(1),
                    self.frames.p.port.cdone.oe.eq(1),
                    self.frames.p.port.cbus .oe.eq(1),
                    self.frames.p.port.cck  .oe.eq(1),
                    self.frames.p.port.cdi  .oe.eq(1),

                    self.frames.p.port.cck  .o[0].eq(timer * 2 >  self.divisor),
                    self.frames.p.port.cck  .o[1].eq(timer * 2 >= self.divisor),
                    self.frames.p.port.cdi  .o[0].eq(data.word_select(cycle, width)[::-1]),
                    self.frames.p.port.cdi  .o[1].eq(data.word_select(cycle, width)[::-1]),
                ]
            with m.Case(Operation.DUMMY):
                m.d.comb += [
                    self.frames.p.port.cs   .oe.eq(1),
                    self.frames.p.port.cdone.oe.eq(1),
                    self.frames.p.port.cck  .oe.eq(1),

                    self.frames.p.port.cck  .o[0].eq(timer * 2 >  self.divisor),
                    self.frames.p.port.cck  .o[1].eq(timer * 2 >= self.divisor),
                ]
                m.d.comb += self.frames.p.meta.shifted .eq(data[0] & (cycle == 0))
            with m.Case(Operation.FINALIZE): # The FPGA is now breathing manually
                m.d.comb += self.frames.p.meta.finalize.eq(1)

        m.d.comb += self.frames.valid.eq(self.octets.valid)
        with m.If(self.frames.valid & self.frames.ready):
            with m.If(
                (self.octets.p.oper == Operation.RESET) |
                (self.octets.p.oper == Operation.SETUP) |
                (self.octets.p.oper == Operation.FINALIZE)):
                m.d.comb += self.octets.ready.eq(self.frames.ready)
            with m.Else():
                m.d.sync += [
                    timer   .eq(timer + 1),
                ]
                with m.If(timer == self.divisor):
                    m.d.sync += [
                        cycle.eq(cycle + 1),
                        timer.eq(0),
                    ]
                    with m.If(cycle == (8 // width) - 1):
                        m.d.sync += cycle.eq(0)
                        m.d.comb += self.octets.ready.eq(1)

        return m


class Controller(wiring.Component):
    def __init__(self, ports, *, clock_period):
        assert (len(ports.reset) == 1 and
                ports.reset.direction in (io.Direction.Output, io.Direction.Bidir))
        assert (len(ports.cs) == 1 and
                ports.cs.direction in (io.Direction.Output, io.Direction.Bidir))
        assert (ports.cdone is None) or (len(ports.cdone) == 1 and
                ports.cdone.direction == io.Direction.Bidir)
        assert (ports.cbus is None or (len(ports.cbus) in [0, 2, 3] and
                ports.cbus.direction in (io.Direction.Output, io.Direction.Bidir)))
        assert (len(ports.cck) == 1 and
                ports.cck.direction in (io.Direction.Output, io.Direction.Bidir))
        assert (len(ports.cdi) in [1, 2, 4, 8] and
                ports.cdi.direction in (io.Direction.Output, io.Direction.Bidir))

        cdone = None if ports.cdone is None else ports.cdone.with_direction("io")
        cbus  = None if ports.cbus  is None else ports.cbus .with_direction("o")
        self._clock_period = clock_period
        self._width = len(ports.cdi)
        self._ports = PortGroup(
            reset=~ports.reset.with_direction("o"),
            cs   =~ports.cs   .with_direction("o"),
            cdone= cdone,
            cbus = cbus,
            cck  = ports.cck  .with_direction("o"),
            cdi  = ports.cdi  .with_direction("o"),
        )

        super().__init__({
            "i": In(stream.Signature(data.StructLayout({
                "data": 8,
                "end":  1,
            }))),
            "o": Out(stream.Signature(Status)),
            "divisor":  In(16)
        })

    def elaborate(self, platform):
        m = Module()

        m.submodules.enframer = enframer = Enframer(ports=self._ports)
        m.submodules.deframer = deframer = Deframer(ports=self._ports)

        m.submodules.io_streamer = io_streamer = \
            IOStreamer(self._ports, ratio=2,
                       meta_layout=data.StructLayout({"finalize": 1, "shifted": 1}))

        wiring.connect(m, io_streamer=io_streamer.i, enframer=enframer.frames)
        wiring.connect(m, deframer=deframer.frames, io_streamer=io_streamer.o)
        m.d.comb += enframer.divisor.eq(self.divisor)

        wiring.connect(m, deframer.o, wiring.flipped(self.o))
        with m.If(deframer.o.valid & (deframer.o.payload == Status.WAITING)):
            m.d.comb += [
                self.o.valid.eq(0),
                deframer.o.ready.eq(1),
            ]

        treset_cycles = int(T_RESET_MIN // self._clock_period) + 1
        tdata_cycles  = int(T_DATA_MIN / self._clock_period) + 1
        cdummy_cycles = C_DUMMY_MIN // (8 // self._width) + 1

        timer = Signal(range(max(treset_cycles, tdata_cycles, cdummy_cycles)))
        def repeat(count, next):
            with m.If(enframer.octets.valid & enframer.octets.ready):
                m.d.sync += timer.eq(timer + 1)
                with m.If(timer + 1 == count):
                    m.d.sync += timer.eq(0)
                    m.next = next

        with m.FSM():
            with m.State("IDLE"):
                with m.If(self.i.valid):
                    m.next = "RESET"
            with m.State("RESET"):
                m.d.comb += [
                    enframer.octets.valid .eq(1),
                    enframer.octets.p.oper.eq(Operation.RESET),
                ]
                repeat(treset_cycles, "SETUP")
            with m.State("SETUP"):
                m.d.comb += [
                    enframer.octets.valid .eq(1),
                    enframer.octets.p.oper.eq(Operation.SETUP),
                    enframer.octets.p.data.eq(0xff),
                ]
                repeat(treset_cycles, "DATA_WAIT")
            with m.State("DATA_WAIT"):
                m.d.comb += [
                    enframer.octets.valid .eq(1),
                    enframer.octets.p.oper.eq(Operation.SETUP),
                ]
                repeat(tdata_cycles, "DATA")
            with m.State("DATA"):
                m.d.comb += [
                    enframer.octets.p.oper.eq(Operation.PUT),
                    enframer.octets.p.data.eq(self.i.p.data),
                ]
                with m.If(~self.i.p.end):
                    m.d.comb += [
                        self.i.ready.eq(enframer.octets.ready),
                        enframer.octets.valid.eq(self.i.valid),
                    ]
                with m.If(self.i.p.end & self.i.valid):
                    m.d.comb += self.i.ready.eq(1)
                    m.next = "SHIFTED"
            with m.State("SHIFTED"):
                m.d.comb += [
                    enframer.octets.valid .eq(1),
                    enframer.octets.p.oper.eq(Operation.DUMMY),
                    enframer.octets.p.data.eq(0xff)
                ]
                repeat(1, "DUMMY")
            with m.State("DUMMY"):
                m.d.comb += [
                    enframer.octets.valid .eq(1),
                    enframer.octets.p.oper.eq(Operation.DUMMY),
                ]
                repeat(cdummy_cycles, "FINALIZE")
            with m.State("FINALIZE"):
                m.d.comb += [
                    enframer.octets.valid .eq(1),
                    enframer.octets.p.oper.eq(Operation.FINALIZE)
                ]
                with m.If(enframer.octets.valid & enframer.octets.ready):
                    m.next = "FINALIZE_WAIT"
            with m.State("FINALIZE_WAIT"):
                with m.If(deframer.o.valid & deframer.o.ready):
                    with m.If(deframer.o.payload == Status.FINALIZED):
                        m.next = "IDLE"
                    with m.If(deframer.o.payload == Status.WAITING):
                        m.next = "FINALIZE"

        return m


class EfinixConfigComponent(wiring.Component):
    def __init__(self, ports, *, clock_period):
        self._ports        = ports
        self._clock_period = clock_period

        super().__init__({
            "bitstream": In(stream.Signature(8)),
            "status":    Out(stream.Signature(8)),
            "divisor":   In(16),
        })

    def elaborate(self, platform):
        m = Module()

        m.submodules.ctl = ctl = Controller(self._ports, clock_period=self._clock_period)
        m.d.comb += ctl.divisor.eq(self.divisor)

        m.submodules.dec = dec = Decoder()
        wiring.connect(m, wiring.flipped(self.bitstream), dec.i)
        wiring.connect(m, dec.o, ctl.i)
        m.d.comb += [
            self.status.p.eq(ctl.o.p),
            self.status.valid.eq(ctl.o.valid),
            ctl.o.ready.eq(self.status.ready),
        ]

        return m


class EfinixSRAMError(GlasgowAppletError):
    pass


class EfinixSRAMInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 creset: GlasgowPin, cs: GlasgowPin, cck: GlasgowPin, cdi: GlasgowPin,
                 cbus: GlasgowPin | None = None, cdone: GlasgowPin | None = None,
                 freset: GlasgowPin | None = None):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._width  = len(cdi)
        self._sim    = False

        if cdone is None:
            cdone = assembly.add_port(None, "cdone")
        if cbus is None:
            cbus  = assembly.add_port(None, "cbus")
        ports = assembly.add_port_group(reset=creset, cs=cs, cck=cck,
                                        cdi=cdi, cbus=cbus, cdone=cdone)
        self._component = component = assembly.add_submodule(
            EfinixConfigComponent(ports, clock_period=assembly.sys_clk_period)
        )

        self._pipe = assembly.add_inout_pipe(component.status, component.bitstream)
        self._clock = assembly.add_clock_divisor(
            component.divisor,
            ref_period=assembly.sys_clk_period,
            name="clock"
        )

        self._freset_iface = None
        if freset is not None:
            self._freset_iface = GPIOInterface(logger, assembly, pins=(~freset,), name="freset")

    def _log(self, message: str, *args):
        self._logger.log(self._level, "efinix: " + message, *args)

    @property
    def clock(self) -> ClockDivisor:
        return self._clock

    @property
    def width(self) -> int:
        return self._width

    async def load(self, bitstream: Buffer):
        """Load :py:`bitstream` into configuration SRAM.

        Raises
        ------
        EfinixError
            If the CDONE pin is present and was not asserted within 10 ms after the bitstream
            has been shifted in.
        """
        if self._freset_iface:
            await self._freset_iface.output(0, True)
        await self._pipe.send(encode(bitstream))
        await self._pipe.send(b"\x00")
        await self._pipe.flush()

        status = (await self._pipe.recv(1))[0]
        assert status == Status.SHIFTED.value

        async def finish():
            status = (await self._pipe.recv(1))[0]
            assert status == Status.FINALIZED.value
            if self._freset_iface:
                await self._freset_iface.output(0, False)
                await self._freset_iface.input(0)
        if self._sim:
            await finish()
        else:
            async with asyncio.timeout(0.010):
                await finish()


class ProgramEfinixSRAMApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "program SRAM of Efinix FPGAs"
    description = """
    Program the volatile bitstream memory of Efinix FPGAs.
    """
    required_revision = "A0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "creset", default=True, required=True)
        access.add_pins_argument(parser, "cs",     default=True, required=True,
                                 help="Called SS_N on some boards")
        access.add_pins_argument(parser, "cck",    default=True, required=True)
        access.add_pins_argument(parser, "cdi",    default=1,    required=True,
                                 width=[1, 2, 4, 8])
        access.add_pins_argument(parser, "cbus",   width=3)
        access.add_pins_argument(parser, "cdone",  width=1)

        access.add_pins_argument(parser, "freset",
                                 help="FTDI Reset present on all the efinix dev boards")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.efinix_iface = EfinixSRAMInterface(
                self.logger, self.assembly,
                creset=args.creset, cs=args.cs, cck=args.cck, cdi=args.cdi,
                cbus=args.cbus, cdone=args.cdone
            )

    @classmethod
    def add_setup_arguments(cls, parser):
        # T55+/Nook has an errata that limits the config clock to 10MHz for the lower
        # speed grades and 12.5MHz for the higher speed grades as opposed to it being
        # 25MHz in X1 mode for every other part in every speed grade. In practice
        # this appears to work out to 48MHz for T20/Rebecca
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=9_600,
            help="set SCK frequency to FREQ kHz (default: %(default)s)")

    async def setup(self, args):
        await self.efinix_iface.clock.set_frequency(args.frequency * 1000)

    @classmethod
    def add_run_arguments(cls, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument(
            "--hex", metavar="HEX", type=argparse.FileType("r"),
            help=".hex file emitted by the toolchain")
        group.add_argument(
            "--bin", metavar="BINARY", type=argparse.FileType("rb"),
            help="a binary serialization of the .hex file, emitted as .bin by the toolchain")

    async def run(self, args):
        self.logger.info("loading bitstream")
        if args.bin is not None:
            await self.efinix_iface.load(args.bin.read())
        else:
            # The fact that this is the bitstream interchange format is frankly
            # baffling to me
            parsed = bytes.fromhex(args.hex.read())
            await self.efinix_iface.load(parsed)

    @classmethod
    def tests(cls):
        from . import test
        return test.ProgramEfinixSRAMAppletTestCase
