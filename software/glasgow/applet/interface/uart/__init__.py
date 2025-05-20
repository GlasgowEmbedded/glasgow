import os
import sys
import logging
import asyncio
import typing
from amaranth import *
from amaranth.lib import wiring, stream, io
from amaranth.lib.wiring import In, Out

from ....support.arepl import AsyncInteractiveConsole
from ....support.logging import dump_hex
from ....support.endpoint import ServerEndpoint
from ....gateware.uart import UART
from ... import GlasgowAppletV2


class UARTAutoBaud(wiring.Component):
    """
    Automatic UART baud rate determination.

    Unlike the algorithm usually called "autobaud" that only works on the initial "A" letter
    (as in "AT command"), the algorithm implemented here does not require any particular alphabet
    to be used for transfers, only that an instance of ...010... or ...101... appears sufficiently
    often in the bitstream. (E.g. if the only transmitted byte is ``11110000``, the autobaud
    algorithm will not correctly lock onto this sequence. In fact, it would determine the baud rate
    that is 5× slower than the actual one.)

    When running on an ASCII stream, approximately 82% of the printable characters will allow this
    algorithm to produce a valid baud rate (17 characters do not have a single bit-time)... an
    extended series of the characters listed below may cause issues when combined with framing or
    parity errors (e.g: due to glitches).

        01389<?`acgpqsxy|

    This algorithm works by training on a fixed-length sequence of pulses, choosing the length
    of the shortest one as the bit time. After the sequence ends, it retrains again from scratch,
    discarding the previous estimate.

    Such an algorithm can be left running unattended and with no configuration, and only be
    consulted when frame errors are detected.
    """

    rx:  In(1)
    cyc: Out(20)

    def __init__(self, seq_size=32):
        self.seq_size = seq_size

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # Edge detector
        rx_r = Signal()
        edge = Signal()

        m.d.sync += rx_r.eq(self.rx)
        m.d.comb += edge.eq(self.rx != rx_r)

        # Training state machine
        seq_count = Signal(range(self.seq_size))
        cyc_count = Signal.like(self.cyc)
        cyc_latch = Signal.like(self.cyc)

        with m.FSM():
            with m.State("EDGE"):
                with m.If(seq_count == (self.seq_size - 1)):
                    m.d.sync += [
                        self.cyc.eq(cyc_latch),
                        cyc_latch.eq(~0),
                        seq_count.eq(0),
                    ]
                with m.Else():
                    m.d.sync += seq_count.eq(seq_count + 1)
                m.d.sync += cyc_count.eq(1)
                m.next = "COUNT"

            with m.State("COUNT"):
                m.d.sync += cyc_count.eq(cyc_count + 1)
                with m.If(cyc_count == cyc_latch):
                    # This branch also handles overflow of cyc_count.
                    m.next = "SKIP"
                with m.Elif(edge):
                    m.d.sync += cyc_latch.eq(cyc_count + 1)
                    m.next = "EDGE"

            with m.State("SKIP"):
                with m.If(edge):
                    m.next = "EDGE"

        return m


class UARTComponent(wiring.Component):
    i_stream:   In(stream.Signature(8))
    o_stream:   Out(stream.Signature(8))

    use_auto:   In(1)
    manual_cyc: In(20)
    auto_cyc:   Out(20)

    bit_cyc:    Out(20)
    rx_errors:  Out(16)

    def __init__(self, ports, *, parity: str):
        self.ports  = ports
        self.parity = parity

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        # TODO: `uart.bit_cyc` is only used to set the width of the register; the actual initial
        # value is zero (same as `self.bit_cyc`); this is a footgun and should be fixed by rewriting
        # the UART to use lib.wiring
        m.submodules.uart = uart = UART(self.ports,
            bit_cyc=(1 << len(self.manual_cyc)) - 1,
            parity=self.parity)
        m.submodules.auto_baud = auto_baud = UARTAutoBaud()

        m.d.comb += auto_baud.rx.eq(uart.bus.rx_i)
        m.d.comb += self.auto_cyc.eq(auto_baud.cyc)

        with m.If(self.use_auto):
            with m.If((uart.rx_ferr | uart.rx_perr) & (self.auto_cyc > 2)):
                m.d.sync += uart.bit_cyc.eq(self.auto_cyc)
        with m.Else():
            m.d.sync += uart.bit_cyc.eq(self.manual_cyc)
        m.d.comb += self.bit_cyc.eq(uart.bit_cyc)

        with m.If(uart.rx_ferr | uart.rx_perr):
            m.d.sync += self.rx_errors.eq(self.rx_errors + 1)

        m.d.comb += [
            uart.tx_data.eq(self.i_stream.payload),
            uart.tx_ack.eq(self.i_stream.valid),
            self.i_stream.ready.eq(uart.tx_rdy),
            self.o_stream.payload.eq(uart.rx_data),
            self.o_stream.valid.eq(uart.rx_rdy),
            uart.rx_ack.eq(self.o_stream.ready),
        ]

        return m


class UARTInterface:
    def __init__(self, logger, assembly, *, rx, tx, parity="none"):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        ports = assembly.add_port_group(rx=rx, tx=tx)
        assembly.use_pulls({rx: "high"})
        component = assembly.add_submodule(UARTComponent(ports, parity=parity))
        self._pipe = assembly.add_inout_pipe(component.o_stream, component.i_stream)
        self._use_auto   = assembly.add_rw_register(component.use_auto)
        self._manual_cyc = assembly.add_rw_register(component.manual_cyc)
        self._auto_cyc   = assembly.add_ro_register(component.auto_cyc)
        self._bit_cyc    = assembly.add_ro_register(component.bit_cyc)
        self._rx_errors  = assembly.add_ro_register(component.rx_errors)
        self._sys_clk_period = assembly.sys_clk_period

    def _log(self, message, *args):
        self._logger.log(self._level, "UART: " + message, *args)

    async def get_baud(self):
        """Returns the baud rate used by the UART, whether manually or automatically configured."""
        bit_cyc = await self._bit_cyc
        if bit_cyc > 0:
            return 1 / ((await self._bit_cyc) * self._sys_clk_period)
        else:
            return 0 # shouldn't happen, but sometimes does

    async def set_baud(self, baud):
        """Configures baud rate to ``baud`` bits per second, overriding any automatically detected
        baud rate."""
        manual_cyc = round(1 / (baud * self._sys_clk_period))
        if manual_cyc < 2:
            raise GlasgowAppletError(f"baud rate {baud} is too high")
        await self._manual_cyc.set(manual_cyc)
        await self._use_auto.set(0)

    async def use_auto_baud(self):
        """Configures UART to automatically determine baud rate from incoming bit stream."""
        await self._use_auto.set(1)

    async def read(self, length: int, *, flush=True) -> memoryview:
        """Reads one or more bytes from the UART. If ``flush`` is true, transmits any buffered
        writes before starting to receive."""
        self._log("rx len=%d", length)
        if flush:
            await self.flush()
        data = await self._pipe.recv(length)
        self._log("rx data=<%s>", dump_hex(data))
        return data

    async def read_all(self, *, flush=True) -> memoryview:
        """Reads all buffered bytes from the UART, but no less than one byte. If ``flush`` is
        true, transmits any buffered writes before starting to read."""
        self._log("rx all")
        if flush:
            await self.flush()
        if not self._pipe.readable:
            data = await self._pipe.recv(1)
        else:
            data = await self._pipe.recv(self._pipe.readable)
        self._log("rx data=<%s>", dump_hex(data))
        return data

    async def read_until(self, trailer: bytes | typing.Tuple[bytes, ...]) -> memoryview:
        """Reads bytes from the UART until ``trailer``, which can be a single byte sequence
        or a choice of multiple byte sequences, is encountered. The return value includes
        the trailer."""
        buffer = bytearray()
        while not buffer.endswith(trailer):
            buffer += await self.read(1)
        return memoryview(buffer)

    async def write(self, data: bytes | bytearray | memoryview, *, flush=False):
        """Buffers bytes to be transmitted. Until :meth:`flush` is called, bytes are not guaranteed
        to be transmitted (they may or may not be)."""
        data = memoryview(data)
        self._log("tx data=<%s>", dump_hex(data))
        await self._pipe.send(data)
        if flush:
            await self.flush()

    async def flush(self):
        """Transmits all buffered bytes from the UART."""
        self._log("tx flush")
        await self._pipe.flush()

    async def monitor(self, *, interval=1.0):
        """Logs receive errors and automatic baud rate changes."""
        cur_errors = 0
        cur_baud = await self.get_baud()
        while True:
            new_errors = await self._rx_errors
            delta = new_errors - cur_errors
            if new_errors < cur_errors:
                delta += 1 << 16
            if delta > 0:
                self._logger.warning("%d receive errors detected", delta)
            cur_errors = new_errors

            new_baud = await self.get_baud()
            if new_baud != cur_baud:
                self._logger.info("switched to %d baud", await self.get_baud())
            cur_baud = new_baud

            await asyncio.sleep(interval)


class UARTApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "communicate via UART"
    description = """
    Transmit and receive data via UART.

    Any baud rate is supported. Only 8 data bits and 1 stop bits are supported, with configurable
    parity.

    The automatic baud rate determination algorithm works by locking onto the shortest bit time in
    the receive stream. It will determine the baud rate incorrectly in presence of glitches as well
    as insufficiently diverse data (e.g. when receiving data consisting only of the letter "a",
    the baud rate that is determined will be one half of the actual baud rate). To reduce spurious
    baud rate changes, the algorithm is only consulted when frame or (if enabled) parity errors
    are present in received data.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "rx", default=True)
        access.add_pins_argument(parser, "tx", default=True)
        parser.add_argument(
            "--parity", metavar="PARITY",
            choices=("none", "zero", "one", "odd", "even"), default="none",
            help="send and receive parity bit as PARITY (default: %(default)s)")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.uart_iface = UARTInterface(self.logger, self.assembly,
                rx=args.rx, tx=args.tx, parity=args.parity)

    @classmethod
    def add_setup_arguments(cls, parser):
        parser.add_argument(
            "-b", "--baud", metavar="RATE", type=int, default=115200,
            help="set baud rate to RATE bits per second (default: %(default)s)")
        parser.add_argument(
            "-a", "--auto-baud", default=False, action="store_true",
            help="automatically estimate baud rate in response to RX errors")

    async def setup(self, args):
        await self.uart_iface.set_baud(args.baud)
        if args.auto_baud:
            await self.uart_iface.use_auto_baud()

    @classmethod
    def add_run_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_tty = p_operation.add_parser(
            "tty", help="connect UART to stdin/stdout")
        p_tty.add_argument(
            "-s", "--stream", action="store_true", default=False,
            help="continue reading from I/O port even after an end-of-file condition on stdin")

        p_pty = p_operation.add_parser(
            "pty", help="connect UART to a pseudo-terminal device file")

        p_socket = p_operation.add_parser(
            "socket", help="connect UART to a socket")
        ServerEndpoint.add_argument(p_socket, "endpoint")

    async def _forward_fd(self, args, in_fileno, out_fileno, quit_sequence=False):
        async def forward_out():
            quit = 0
            while True:
                data = await asyncio.get_event_loop().run_in_executor(None,
                    lambda: os.read(in_fileno, 1024))
                if len(data) == 0 and not args.stream:
                    raise EOFError

                if os.isatty(in_fileno):
                    if quit == 0 and data == b"\034":
                        quit = 1
                        continue
                    elif quit == 1 and data == b"q":
                        raise EOFError
                    else:
                        quit = 0

                await self.uart_iface.write(data, flush=True)

        async def forward_in():
            while True:
                data = await self.uart_iface.read_all(flush=False)
                await asyncio.get_event_loop().run_in_executor(None,
                    lambda: os.write(out_fileno, data))

        try:
            async with asyncio.TaskGroup() as group:
                group.create_task(self.uart_iface.monitor())
                group.create_task(forward_out())
                group.create_task(forward_in())
        except* EOFError:
            pass

    async def _run_tty(self, args):
        in_fileno  = sys.stdin.fileno()
        out_fileno = sys.stdout.fileno()

        if os.isatty(in_fileno) and os.name != "nt":
            import termios

            old_stdin_attrs = termios.tcgetattr(sys.stdin)
            [iflag, oflag, cflag, lflag, ispeed, ospeed, cc] = old_stdin_attrs
            lflag &= ~(termios.ECHO | termios.ICANON | termios.ISIG)
            iflag &= ~termios.ICRNL
            cc[termios.VMIN] = 1
            new_stdin_attrs = [iflag, oflag, cflag, lflag, ispeed, ospeed, cc]
            termios.tcsetattr(in_fileno, termios.TCSADRAIN, new_stdin_attrs)

            self.logger.info("running on a TTY; enter `Ctrl+\\ q` to quit")
            try:
                await self._forward_fd(args, in_fileno, out_fileno, quit_sequence=True)
            finally:
                termios.tcsetattr(in_fileno, termios.TCSADRAIN, old_stdin_attrs)

        else:
            await self._forward_fd(args, in_fileno, out_fileno)

    async def _run_pty(self, args):
        import pty

        master, slave = pty.openpty()
        print(os.ttyname(slave))

        await self._forward_fd(args, in_fileno=master, out_fileno=master)

    async def _run_socket(self, args):
        endpoint = await ServerEndpoint("socket", self.logger, args.endpoint)

        async def forward_out():
            while True:
                try:
                    data = await endpoint.recv()
                except EOFError:
                    continue
                await self.uart_iface.write(data, flush=True)

        async def forward_in():
            while True:
                data = await self.uart_iface.read_all(flush=False)
                await endpoint.send(data)

        async with asyncio.TaskGroup() as group:
            group.create_task(self.uart_iface.monitor())
            group.create_task(forward_out())
            group.create_task(forward_in())

    async def run(self, args):
        match args.operation:
            case "tty" | None:
                await self._run_tty(args)
            case "pty":
                await self._run_pty(args)
            case "socket":
                await self._run_socket(args)

    async def repl(self, args):
        self.logger.info("dropping to REPL; use 'help(iface)' to see available APIs")
        await AsyncInteractiveConsole(
            locals={"iface": self.uart_iface},
            run_callback=self.assembly.flush
        ).interact()

    @classmethod
    def tests(cls):
        from . import test
        return test.UARTAppletTestCase
