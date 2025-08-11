# Ref: SH7254R Group User's Manual: Hardware §21.1 §21.4
# Document Number: R01UH0480EJ0400
# Accession: G00106
#
# This applet implements part of the SuperH AUD-II protocol. This protocol
# supports rich features such as branch and data tracing. However, it also
# supports a "RAM Monitoring Mode" wich has simple read and write command. This
# applet implements the RAM Monitoring Mode read command to be able to dump a
# target's memory.

import argparse
import logging
import sys
from typing import Literal

from amaranth import *
from amaranth.lib import io, wiring, stream, cdc, enum
from amaranth.lib.wiring import In, Out

from glasgow.abstract import AbstractAssembly, GlasgowPin, ClockDivisor
from glasgow.applet import GlasgowAppletV2, GlasgowAppletError


class AUDError(GlasgowAppletError):
    pass


class _AUDMonitorSize(enum.Enum):
    Byte = 0b00
    Word = 0b01
    LongWord = 0b10


class _AUDMonitorCommand(enum.Enum):
    Read = 0b1000
    Write = 0b1100


class AUDCommand(enum.Enum, shape=8):
    Reset = 0x00
    Run = 0x01
    Sync = 0x02
    Out = 0x03
    Inp = 0x04


class AUDComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))

    divisor:  In(16)

    def __init__(self, ports):
        self._ports      = ports

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # Add IO buffers
        m.submodules.audsync_buffer = audsync = io.Buffer("o", self._ports.audsync)
        m.submodules.audmd_buffer = audmd = io.Buffer("o", self._ports.audmd)
        m.submodules.audrst_buffer = audrst = io.Buffer("o", self._ports.audrst)
        m.submodules.audck_buffer = audck = io.Buffer("o", self._ports.audck)
        m.submodules.audata_buffer = audata = io.Buffer("io", self._ports.audata)

        # Always in RAM monitoring mode
        m.d.comb += audmd.o.eq(1)

        # Create signal for reading AUDATA pins
        audata_i  = Signal(4)
        m.submodules += cdc.FFSynchronizer(audata.i, audata_i)

        # FSM related signals
        timer = Signal.like(self.divisor)
        data = Signal(4)

        # Main State Machine
        with m.FSM():
            # Receive command and switch to the appropriate handler state
            with m.State("RECV-COMMAND"):
                with m.If(self.i_stream.valid):
                    m.d.comb += self.i_stream.ready.eq(1)
                    m.d.sync += data.eq(self.i_stream.payload >> 4)
                    with m.Switch(self.i_stream.payload & 0xF):
                        with m.Case(AUDCommand.Reset):
                            m.next = "RESET"
                        with m.Case(AUDCommand.Run):
                            m.next = "RUN"
                        with m.Case(AUDCommand.Sync):
                            m.next = "SYNC"
                        with m.Case(AUDCommand.Out):
                            m.next = "OUT"
                        with m.Case(AUDCommand.Inp):
                            m.next = "INP"

            # Assert Reset and put pins into a known state
            with m.State("RESET"):
                # Put pins into known state
                m.d.sync += audck.o.eq(0)
                m.d.sync += audata.oe.eq(1)
                m.d.sync += audata.o.eq(0b0000)
                m.d.sync += audsync.o.eq(1)

                # Put into reset
                m.d.sync += audrst.o.eq(0)
                m.next = "RECV-COMMAND"

            # Release Reset
            with m.State("RUN"):
                # Release reset
                m.d.sync += audrst.o.eq(1)
                m.next = "RECV-COMMAND"

            # Set Sync pin to provided value
            with m.State("SYNC"):
                m.d.sync += audsync.o.eq(data != 0b0000)
                m.next = "RECV-COMMAND"

            # Send 1 nibble of data on the bus, then strobe clock
            with m.State("OUT"):
                m.d.sync += audata.oe.eq(1) # Switch AUDATA pins to output
                m.d.sync += audata.o.eq(data)

                # Strobe clock
                m.d.sync += audck.o.eq(0)
                m.d.sync += timer.eq(0)
                m.next = "OUT-CLOCK-0"

            # Wait for clock period to pass, then set clock high
            with m.State("OUT-CLOCK-0"):
                with m.If(timer == self.divisor):
                    m.d.sync += audck.o.eq(1)
                    m.d.sync += timer.eq(0)
                    m.next = "OUT-CLOCK-1"
                with m.Else():
                    m.d.sync += timer.eq(timer + 1)

            # Wait for clock period to pass, then return to command reception
            with m.State("OUT-CLOCK-1"):
                with m.If(timer == self.divisor):
                    m.next = "RECV-COMMAND"
                with m.Else():
                    m.d.sync += timer.eq(timer + 1)

            # Strobe clock, then read data on the rising edge. Send to PC
            with m.State("INP"):
                m.d.sync += audata.oe.eq(0) # Switch AUDATA pins to input

                # Strobe clock
                m.d.sync += audck.o.eq(0)
                m.d.sync += timer.eq(9)
                m.next = "INP-CLOCK-0"

            # Wait for clock period to pass, then sample data and set clock high
            with m.State("INP-CLOCK-0"):
                with m.If(timer == self.divisor):
                    m.d.sync += audck.o.eq(1)
                    m.d.sync += timer.eq(0)

                    # Sample data on rising edge
                    m.d.sync += data.eq(audata_i)

                    m.next = "INP-CLOCK-1"
                with m.Else():
                    m.d.sync += timer.eq(timer + 1)

            # Wait for clock period to pass, then send data to PC
            with m.State("INP-CLOCK-1"):
                with m.If(timer == self.divisor):
                    m.next = "SEND-DATA"
                with m.Else():
                    m.d.sync += timer.eq(timer + 1)

            # Send the sampled data to the output stream, return to command reception
            with m.State("SEND-DATA"):
                m.d.comb += self.o_stream.valid.eq(1)
                m.d.comb += self.o_stream.payload.eq(data)

                with m.If(self.o_stream.ready):
                    m.next = "RECV-COMMAND"

        return m


class AUDInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
        audata: GlasgowPin, audsync: GlasgowPin, audck: GlasgowPin, audmd: GlasgowPin, audrst: GlasgowPin):
        self._logger = logger
        self._level  = logging.TRACE

        ports = assembly.add_port_group(audata=audata, audsync=audsync, audck=audck, audmd=audmd, audrst=audrst)
        component = assembly.add_submodule(AUDComponent(
            ports,
        ))
        self._pipe = assembly.add_inout_pipe(component.o_stream, component.i_stream)
        self._clock = assembly.add_clock_divisor(component.divisor,
            ref_period=assembly.sys_clk_period, name="audclk")

    @property
    def clock(self) -> ClockDivisor:
        return self._clock

    async def _cmd(self, cmd: AUDCommand, val=0):
        assert val <= 0xF, "Value must be less than 0xF"
        self._logger.log(self._level, "AUD: write CMD: %s DATA: <%02x>", cmd.name, val)
        await self._pipe.send([cmd.value | (val << 4)])

    async def reset(self):
        await self._cmd(AUDCommand.Reset)

    async def run(self):
        await self._cmd(AUDCommand.Run)

    async def out(self, val):
        await self._cmd(AUDCommand.Out, val)

    async def inp(self):
        await self._cmd(AUDCommand.Inp)

         # This is the only place we need to flush, as we're going to wait for a response
        await self._pipe.flush()

        data = await self._pipe.recv(1)
        self._logger.log(self._level, "AUD: read <%02x>", data[0])
        return data[0]

    async def sync(self, val):
        await self._cmd(AUDCommand.Sync, val)

    async def init(self):
        await self.reset()

        # Strobe clock a couple times
        for i in range(10):
            await self.out(0)

        await self.run()

        # Strobe clock a couple times
        for i in range(10):
            await self.out(0)

    async def read(self, addr: int, sz: Literal[1,2,4 ] = 4, timeout: int = 100):
        assert addr in range(0, 1<<32), "Address must be a 32-bit value"
        assert sz in (1, 2, 4), "Size must be one of 1, 2, or 4 bytes"

        await self.sync(0)
        await self.out(0)

        # Send the Read command
        cmd = _AUDMonitorCommand.Read.value | \
           {
               1: _AUDMonitorSize.Byte,
               2: _AUDMonitorSize.Word,
               4: _AUDMonitorSize.LongWord,
            }[sz].value
        await self.out(cmd)

        # Clock out Addr
        for i in range(8):
            await self.out((addr >> (i * 4)) & 0b1111)

        # Wait for data ready
        for _ in range(timeout):
            data = await self.inp()
            if data == 1:
                break
        else:
            raise AUDError(f"timeout waiting for data ready; got {data:#06b}")

        # Set AUDSYNC high to indicate we're ready to read
        await self.sync(1)
        await self.inp()

        # Clock in the data
        out = 0
        for i in range(2*sz):
            out  |= (await self.inp() << (i * 4))
        return out.to_bytes(sz, byteorder='big')


class AUDApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "SuperH AUD-II Applet"
    description = """
    Read memory using the SuperH AUD-II protocol.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)

        access.add_pins_argument(parser, "audata", width=4, required=True)
        access.add_pins_argument(parser, "audsync", required=True)
        access.add_pins_argument(parser, "audck", required=True)
        access.add_pins_argument(parser, "audrst", required=True)
        access.add_pins_argument(parser, "audmd", required=True)

    @classmethod
    def add_setup_arguments(cls, parser):
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=100,
            help="set clock period to FREQ kHz (default: %(default)s)")

    @classmethod
    def add_run_arguments(cls, parser):
        def address(x):
            addr = int(x, 0)

            # Check alignment
            if addr % 4:
                raise argparse.ArgumentTypeError(f"address {x} is not 4 byte aligned")

            return addr

        def length(x):
            sz = int(x, 0)
            # Check alignment
            if sz % 4:
                raise argparse.ArgumentTypeError(f"length {x} is not a multiple of 4")

            return sz

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_read = p_operation.add_parser(
            "read", help="read memory")
        p_read.add_argument(
            "address", metavar="ADDRESS", type=address,
            help="read memory starting at address ADDRESS, needs to be 4 byte aligned")
        p_read.add_argument(
            "length", metavar="LENGTH", type=length,
            help="read LENGTH bytes from memory, needs to be a multiple of 4")
        p_read.add_argument(
            "-f", "--file", metavar="FILENAME", type=argparse.FileType("wb"),
            required=True,
            help="write memory contents to FILENAME")

    async def setup(self, args):
        await self.aud_iface.clock.set_frequency(args.frequency * 1000)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.aud_iface = AUDInterface(
                self.logger,
                self.assembly,
                audata=args.audata,
                audsync=args.audsync,
                audck=args.audck,
                audmd=args.audmd,
                audrst=args.audrst)

    @staticmethod
    def _show_progress(done, total, status):
        if sys.stdout.isatty():
            sys.stdout.write("\r\033[0K")
            if done < total:
                sys.stdout.write(f"{done}/{total} bytes done ({done / total * 100:.2f}%)")
                if status:
                    sys.stdout.write(f"; {status}")
            sys.stdout.flush()

    async def run(self, args):
        self.logger.trace("Initializing AUD-II interface")
        await self.aud_iface.init()

        self.logger.trace("Reading data")
        bs = 4

        for i in range(args.address, args.address + args.length, bs):
            data = await self.aud_iface.read(i, sz=bs)
            args.file.write(data)
            self._show_progress(i - args.address + bs, args.length, f"Read {data.hex()}")

        self.logger.trace("Done")
