import argparse
import logging
import enum
from typing import Any, Optional
from amaranth import *
from amaranth.lib.memory import Memory

from ....access import (
    AccessArguments,
    AccessDemultiplexerInterface,
    AccessMultiplexer,
)
from ....applet import GlasgowApplet
from ....device.hardware import GlasgowHardwareDevice
from ....gateware.i2c import I2CTarget
from ....gateware.ports import PortGroup
from ....target.analyzer import GlasgowAnalyzer
from ....target.hardware import GlasgowHardwareTarget


class Event(enum.IntEnum):
    READ = 0x10
    "Memory read performed. Followed by the current address and the data byte returned in the read"
    WRITE = 0x20
    "Memory write performed. Followed by the current address and the data byte written to our memory"


class Memory24xEmuSubtarget(Elaboratable):
    def __init__(
        self,
        ports: PortGroup,
        in_fifo,
        i2c_address: int,
        address_width: int,
        initial_data: bytearray,
        analyzer: GlasgowAnalyzer = None,
    ):
        self.ports = ports
        self.in_fifo = in_fifo
        self.i2c_address = i2c_address

        self.address_width = address_width
        self.initial_data = initial_data

        self.current_address = Signal(8 * self.address_width)
        self.incoming_write_data = Signal(8)
        self.incoming_address_byte_index = Signal(range(self.address_width))
        self.incoming_address = Signal(8 * self.address_width)

        self.i2c_target = I2CTarget(self.ports, analyzer=analyzer)

    def elaborate(self, platform):
        m = Module()

        m.submodules.memory = memory = Memory(
            shape=unsigned(8), depth=len(self.initial_data), init=self.initial_data
        )
        wr_port = memory.write_port()
        rd_port = memory.read_port(domain="comb")
        m.d.comb += [
            wr_port.addr.eq(self.current_address),
            rd_port.addr.eq(self.current_address),
        ]

        m.submodules.i2c_target = i2c_target = self.i2c_target
        m.d.comb += [
            i2c_target.address.eq(self.i2c_address),
            i2c_target.data_o.eq(rd_port.data),
        ]

        # TODO: handle invalid command ordering
        with m.FSM():
            m.d.comb += i2c_target.busy.eq(1)

            with m.State("IDLE"):
                m.d.comb += i2c_target.busy.eq(0)

                with m.If(i2c_target.start):
                    m.next = "TRANSACTION-STARTED"

            with m.State("TRANSACTION-STARTED"):
                m.d.comb += i2c_target.busy.eq(0)

                with m.If(i2c_target.write):
                    m.d.sync += [
                        self.incoming_address.eq(i2c_target.data_i),
                        self.incoming_address_byte_index.eq(0),
                    ]
                    m.d.comb += i2c_target.ack_o.eq(1)
                    m.next = "RECEIVING-ADDRESS"

                with m.Elif(i2c_target.read):
                    m.next = "BEING-READ-SEND-EVENT"

                with m.Elif(i2c_target.stop):
                    m.next = "IDLE"

            with m.State("RECEIVING-ADDRESS"):
                m.d.comb += i2c_target.busy.eq(0)

                with m.If(
                    (self.incoming_address_byte_index < self.address_width - 1)
                    & i2c_target.write
                ):
                    m.d.sync += [
                        self.incoming_address.eq(
                            self.incoming_address << 8 | i2c_target.data_i
                        ),
                        self.incoming_address_byte_index.eq(
                            self.incoming_address_byte_index + 1
                        ),
                    ]
                    m.d.comb += i2c_target.ack_o.eq(1)
                    m.next = "RECEIVING-ADDRESS"

                with m.Elif(i2c_target.write):
                    m.d.sync += [
                        self.incoming_write_data.eq(i2c_target.data_i),
                        self.current_address.eq(
                            self.incoming_address % len(self.initial_data)
                        ),
                    ]
                    m.d.comb += i2c_target.ack_o.eq(1)
                    m.next = "BEING-WRITTEN-SEND-EVENT"

                with m.Elif(i2c_target.read):
                    m.d.sync += self.current_address.eq(
                        self.incoming_address % len(self.initial_data)
                    )
                    m.next = "BEING-READ-SEND-EVENT"

                with m.Elif(i2c_target.stop):
                    m.d.sync += self.current_address.eq(
                        self.incoming_address % len(self.initial_data)
                    )
                    m.next = "IDLE"

            # --- Reading ---

            with m.State("BEING-READ-SEND-EVENT"):
                m.d.comb += [
                    self.in_fifo.w_data.eq(Event.READ),
                    self.in_fifo.w_en.eq(1),
                ]
                m.next = "BEING-READ-SEND-ADDRESS"

            with m.State("BEING-READ-SEND-ADDRESS"):
                m.d.comb += [
                    self.in_fifo.w_data.eq(self.current_address),
                    self.in_fifo.w_en.eq(1),
                ]
                m.next = "BEING-READ-SEND-DATA"

            with m.State("BEING-READ-SEND-DATA"):
                m.d.comb += [
                    self.in_fifo.w_data.eq(rd_port.data),
                    self.in_fifo.w_en.eq(1),
                ]
                m.d.sync += self.current_address.eq(
                    (self.current_address + 1) % len(self.initial_data)
                )
                m.next = "BEING-READ"

            with m.State("BEING-READ"):
                m.d.comb += i2c_target.busy.eq(0)

                with m.If(i2c_target.read):
                    m.next = "BEING-READ-SEND-EVENT"

                with m.If(i2c_target.stop):
                    m.next = "IDLE"

            # --- Writing ---

            with m.State("BEING-WRITTEN-SEND-EVENT"):
                m.d.comb += [
                    self.in_fifo.w_data.eq(Event.WRITE),
                    self.in_fifo.w_en.eq(1),
                    wr_port.en.eq(1),
                ]

                m.d.sync += wr_port.data.eq(self.incoming_write_data)

                m.next = "BEING-WRITTEN-SEND-ADDRESS"

            with m.State("BEING-WRITTEN-SEND-ADDRESS"):
                m.d.comb += [
                    self.in_fifo.w_data.eq(self.current_address),
                    self.in_fifo.w_en.eq(1),
                ]
                m.next = "BEING-WRITTEN-SEND-DATA"

            with m.State("BEING-WRITTEN-SEND-DATA"):
                m.d.comb += [
                    self.in_fifo.w_data.eq(self.incoming_write_data),
                    self.in_fifo.w_en.eq(1),
                ]
                m.d.sync += self.current_address.eq(
                    (self.current_address + 1) % len(self.initial_data)
                )
                m.next = "BEING-WRITTEN"

            with m.State("BEING-WRITTEN"):
                m.d.comb += i2c_target.busy.eq(0)

                with m.If(i2c_target.write):
                    m.d.sync += self.incoming_write_data.eq(i2c_target.data_i)
                    m.d.comb += i2c_target.ack_o.eq(1)
                    m.next = "BEING-WRITTEN-SEND-EVENT"

                with m.Elif(i2c_target.stop):
                    m.next = "IDLE"

        return m


class Memory24xEmuInterface:

    def __init__(self, interface: AccessDemultiplexerInterface, logger: logging.Logger):
        self.lower = interface
        self._logger = logger
        self._level: int = (
            logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        )

    def _log(self, message: str):
        self._logger.log(self._level, "I²C: %s", message)

    async def read_event(self):
        event: int = (await self.lower.read(1))[0]
        if event == Event.WRITE:
            address, data_byte = await self.lower.read(2)

            self._log(
                f"Written to at <0x{address:02x}>: 0x{data_byte:02x} ({bytes([data_byte])!r})"
            )

        elif event == Event.READ:
            address, data_byte = await self.lower.read(2)

            self._log(
                f"Read at <0x{address:02x}>: 0x{data_byte:02x} ({bytes([data_byte])!r})"
            )


class Memory24xEmuApplet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "emulate a 24-series I²C EEPROM"
    description = """
    FIXME: description
    """
    required_revision = "C0"

    mux_interface: AccessMultiplexer

    @classmethod
    def add_build_arguments(
        cls, parser: argparse.ArgumentParser, access: AccessArguments
    ):
        super().add_build_arguments(parser, access)

        access.add_pin_argument(parser, "scl", default=True)
        access.add_pin_argument(parser, "sda", default=True)

        def i2c_address(arg: str) -> int:
            return int(arg, base=0)

        def data_str(arg: str) -> bytes:
            # `unicode_escape` decodes as latin-1, resolving python backslash-escapes
            #
            # The round-trip through latin-1 de-/encoding with resolution of
            # backslash escape sequences preserves byte values of utf-8 encoded chars.
            # The intermediary python unicode string is however not sensible,
            # only the end result.
            return arg.encode("utf_8").decode("unicode_escape").encode("latin_1")

        def filler_byte(arg: str):
            val = int(arg, base=0)
            assert val >= -128 and val <= 255, "filler value must fit into a byte"
            return val

        parser.add_argument(
            "-A",
            "--i2c-address",
            metavar="I2C-ADDR",
            help="I²C address of the target",
            type=i2c_address,
            required=True,
        )
        parser.add_argument(
            "-w",
            "--address-width",
            metavar="ADDR-WIDTH",
            help="Width of the memory addresses in bytes",
            type=int,
            default=1,
        )

        group = parser.add_mutually_exclusive_group()
        group.add_argument(
            "-d",
            "--init-data",
            metavar="INIT-DATA",
            help="Data the memory is initialized with",
            type=data_str,
        )
        group.add_argument(
            "-f",
            "--init-data-file",
            metavar="INIT-DATA-FILE",
            help="File to read data bytes from with which the memory is initialized",
            type=argparse.FileType("rb"),
        )

        parser.add_argument(
            "-s",
            "--memory-size",
            metavar="MEM-SIZE",
            help="Size of the memory in bytes (len(init_data) + init_data_offset by default)",
            type=int,
        )
        parser.add_argument(
            "--init-data-offset",
            metavar="INIT-DATA-OFFSET",
            help="Offset the initial data within the memory by this amount of bytes",
            type=int,
        )
        parser.add_argument(
            "--filler-byte",
            metavar="FILLER-BYTE",
            help="Byte with which to fill the remaining memory not covered by the provided initial data",
            type=filler_byte,
            default=0,
        )

    def build(self, target: GlasgowHardwareTarget, args: argparse.Namespace):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)

        init_data_offset = (
            args.init_data_offset if args.init_data_offset is not None else 0
        )

        init_data = bytes([])
        init_data_not_provided = False
        if args.init_data is not None:
            init_data = args.init_data
        elif args.init_data_file is not None:
            init_data = args.init_data_file.read()
            args.init_data_file.close()
        else:
            init_data_not_provided = True

        if init_data_not_provided and args.init_data_offset is not None:
            raise argparse.ArgumentError(
                None,
                "--init-data-offset requires one of -d/--init-data or -f/--init-data-file to be specified",
            )

        memory_size = (
            args.memory_size
            if args.memory_size is not None
            else len(init_data) + init_data_offset
        )

        if args.memory_size is None and init_data_not_provided:
            memory_size = 4000

        # Pad start according to offset
        init_data = bytes([args.filler_byte]) * init_data_offset + init_data
        # Pad end according to size
        init_data += bytes([args.filler_byte]) * max(0, memory_size - len(init_data))

        if args.memory_size is not None and len(init_data) > args.memory_size:
            self.logger.log(
                "Initial data exceeds specified memory size after applying the offset. Extending size to make it fit"
            )

        ports = iface.get_port_group(scl=args.pin_scl, sda=args.pin_sda)

        subtarget = Memory24xEmuSubtarget(
            ports=ports,
            in_fifo=iface.get_in_fifo(),
            i2c_address=args.i2c_address,
            address_width=args.address_width,
            initial_data=init_data,
            analyzer=target.analyzer,
        )

        if target.analyzer:
            analyzer = target.analyzer

            analyzer.add_generic_event(
                self,
                "memory_24x_emu-current_address",
                subtarget.current_address,
            )
            analyzer.add_generic_event(
                self,
                "memory_24x_emu-incoming_incoming_write_data",
                subtarget.incoming_write_data,
            )
            if args.address_width > 1:
                # With an address_width <= 1 the incoming_address_byte_index is a 0-width signal,
                # because it only requires one state (last and only address byte being received)
                # The analyzer doesn't like zero width signals ^^
                analyzer.add_generic_event(
                    self,
                    "memory_24x_emu-incoming_address_byte_index",
                    subtarget.incoming_address_byte_index,
                )
            analyzer.add_generic_event(
                self, "memory_24x_emu-incoming_address", subtarget.incoming_address
            )

        iface.add_subtarget(subtarget)

    @classmethod
    def add_run_arguments(
        cls, parser: argparse._ArgumentGroup, access: AccessArguments
    ):
        super().add_run_arguments(parser, access)

        parser.add_argument(
            "--pulls",
            default=False,
            action="store_true",
            help="enable integrated pull-ups",
        )

    async def run(self, device: GlasgowHardwareDevice, args: argparse.Namespace):
        pulls = set()
        if args.pulls:
            pulls = {args.pin_scl, args.pin_sda}
        iface = await device.demultiplexer.claim_interface(
            self, self.mux_interface, args, pull_high=pulls
        )
        return Memory24xEmuInterface(iface, self.logger)

    async def interact(
        self,
        device: GlasgowHardwareDevice,
        args: argparse.Namespace,
        iface: Memory24xEmuInterface,
    ):
        while True:
            await iface.read_event()

    @classmethod
    def tests(cls):
        from . import test

        return test.Memory24xEmuAppletTestCase
