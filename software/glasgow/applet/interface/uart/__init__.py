import os
import sys
import logging
import asyncio
import argparse
from nmigen.compat import *

from ....support.endpoint import *
from ....gateware.pads import *
from ....gateware.uart import *
from ... import *


class UARTAutoBaud(Module):
    """
    Automatic UART baud rate determination.

    Unlike the algorithm usually called "autobaud" that only works on the initial "A" letter
    (as in "AT command"), the algorithm implemented here does not require any particular alphabet
    to be used for transfers, only that an instance of ...010... or ...101... appears sufficiently
    often in the bitstream. (E.g. if the only transmitted byte is ``11110000``, the autobaud
    algorithm will not correctly lock onto this sequence. In fact, it would determine the baud rate
    that is 5× slower than the actual one.)

    This algorithm works by training on a fixed-length sequence of pulses, choosing the length
    of the shortest one as the bit time. After the sequence ends, it retrains again from scratch,
    discarding the previous estimate.

    Such an algorithm can be left running unattended and with no configuration, and only be
    consulted when frame errors are detected.
    """
    def __init__(self, uart, auto_cyc, seq_size=32):
        # Edge detector
        rx_i = uart.bus.rx_i
        rx_r = Signal()
        edge = Signal()

        self.sync += rx_r.eq(rx_i)
        self.comb += edge.eq(rx_i != rx_r)

        # Training state machine
        seq_count = Signal(max=seq_size)
        cyc_count = Signal.like(uart.bit_cyc)
        cyc_latch = Signal.like(uart.bit_cyc)

        self.submodules.fsm = FSM()
        self.fsm.act("EDGE",
            If(seq_count == seq_size - 1,
                NextValue(auto_cyc,  cyc_latch),
                NextValue(cyc_latch, ~0),
                NextValue(seq_count, 0),
            ).Else(
                NextValue(seq_count, seq_count + 1),
            ),
            NextValue(cyc_count, 1),
            NextState("COUNT")
        )
        self.fsm.act("COUNT",
            NextValue(cyc_count, cyc_count + 1),
            If(cyc_count == cyc_latch,
                # This branch also handles overflow of cyc_count.
                NextState("SKIP")
            ).Elif(edge,
                NextValue(cyc_latch, cyc_count + 1),
                NextState("EDGE")
            )
        )
        self.fsm.act("SKIP",
            If(edge,
                NextState("EDGE")
            )
        )


class UARTSubtarget(Module):
    def __init__(self, pads, out_fifo, in_fifo, parity, max_bit_cyc,
                 manual_cyc, auto_cyc, use_auto, bit_cyc, rx_errors, invert_rx, invert_tx):
        self.submodules.uart = uart = UART(pads, bit_cyc=max_bit_cyc, parity=parity,
                                           invert_rx=invert_rx, invert_tx=invert_tx)
        self.submodules.auto_baud = auto_baud = UARTAutoBaud(uart, auto_cyc)

        self.comb += uart.bit_cyc.eq(bit_cyc)
        self.sync += [
            If(use_auto,
                If((uart.rx_ferr | uart.rx_perr) & (auto_cyc != ~0),
                    bit_cyc.eq(auto_cyc)
                )
            ).Else(
                bit_cyc.eq(manual_cyc)
            )
        ]

        self.comb += [
            in_fifo.din.eq(uart.rx_data),
            in_fifo.we.eq(uart.rx_rdy),
            uart.rx_ack.eq(in_fifo.writable)
        ]
        self.sync += [
            If(uart.rx_ferr | uart.rx_perr,
                rx_errors.eq(rx_errors + 1),
            )
        ]

        self.comb += [
            uart.tx_data.eq(out_fifo.dout),
            out_fifo.re.eq(uart.tx_rdy),
            uart.tx_ack.eq(out_fifo.readable),
        ]


class UARTApplet(GlasgowApplet, name="uart"):
    logger = logging.getLogger(__name__)
    help = "communicate via UART"
    description = """
    Transmit and receive data via UART.

    Any baud rate is supported. Only 8n1 mode is supported.
    """

    __pins = ("rx", "tx")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in cls.__pins:
            access.add_pin_argument(parser, pin, default=True)

        parser.add_argument(
            "--parity", metavar="PARITY", choices=("none", "zero", "one", "odd", "even"),
            default="none",
            help="send and receive parity bit as PARITY (default: %(default)s)")
        parser.add_argument(
            "-b", "--baud", metavar="RATE", type=int, default=115200,
            help="set baud rate to RATE bits per second (default: %(default)s)")
        parser.add_argument(
            "--tolerance", metavar="PPM", type=int, default=50000,
            help="verify that actual baud rate is within PPM parts per million of specified"
                 " (default: %(default)s)")
        parser.add_argument(
            "--invert-rx", default=False, action="store_true",
            help="invert the line signal (=idle low) on RX")
        parser.add_argument(
            "--invert-tx", default=False, action="store_true",
            help="invert the line signal (=idle low) on TX")

    def build(self, target, args):
        # We support any baud rates, even absurd ones like 60 baud, if you want, but the applet
        # will have to be rebuilt for anything slower than 9600. This is why the baud rate is
        # a build argument, even though the applet will never be rebuilt as long as you stay
        # above 9600.
        max_bit_cyc = self.derive_clock(
            input_hz=target.sys_clk_freq, output_hz=min(9600, args.baud))

        self.__sys_clk_freq = target.sys_clk_freq

        manual_cyc, self.__addr_manual_cyc = target.registers.add_rw(32)
        auto_cyc,   self.__addr_auto_cyc   = target.registers.add_ro(32, reset=~0)
        use_auto,   self.__addr_use_auto   = target.registers.add_rw(1)

        bit_cyc,    self.__addr_bit_cyc    = target.registers.add_ro(32)
        rx_errors,  self.__addr_rx_errors  = target.registers.add_ro(16)

        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(UARTSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(),
            parity=args.parity,
            max_bit_cyc=max_bit_cyc,
            manual_cyc=manual_cyc,
            auto_cyc=auto_cyc,
            use_auto=use_auto,
            bit_cyc=bit_cyc,
            rx_errors=rx_errors,
            invert_rx=args.invert_rx,
            invert_tx=args.invert_tx,
        ))

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

        parser.add_argument(
            "--pulls", default=False, action="store_true",
            help="enable integrated pull-ups or pull-downs (when inverted)")
        parser.add_argument(
            "-a", "--auto-baud", default=False, action="store_true",
            help="automatically estimate baud rate in response to RX errors")

    async def run(self, device, args):
        # Load the manually set baud rate.
        manual_cyc = self.derive_clock(
            input_hz=self.__sys_clk_freq, output_hz=args.baud,
            min_cyc=2, max_deviation_ppm=args.tolerance)
        await device.write_register(self.__addr_manual_cyc, manual_cyc, width=4)
        await device.write_register(self.__addr_use_auto, 0)

        # Enable pull-ups or pull-downs, if requested.
        # This reduces the amount of noise received on tristated lines.
        pulls_high = set()
        pulls_low = set()
        if args.pulls:
            if args.invert_rx:
                pulls_low = {args.pin_rx}
            else:
                pulls_high = {args.pin_rx}

        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args,
                                                           pull_high=pulls_high, pull_low=pulls_low)

        # Enable auto-baud, if requested.
        if args.auto_baud:
            await device.write_register(self.__addr_use_auto, 1)

        return iface

    @classmethod
    def add_interact_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

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

    async def _monitor_errors(self, device):
        cur_bit_cyc = await device.read_register(self.__addr_bit_cyc, width=4)
        cur_errors  = 0
        while True:
            new_errors = await device.read_register(self.__addr_rx_errors, width=2)
            delta = new_errors - cur_errors
            if new_errors < cur_errors:
                delta += 1 << 16
            cur_errors = new_errors
            if delta > 0:
                self.logger.warning("%d frame or parity errors detected", delta)

            new_bit_cyc = await device.read_register(self.__addr_bit_cyc, width=4)
            if new_bit_cyc != cur_bit_cyc:
                self.logger.info("switched to %d baud",
                                 self.__sys_clk_freq // (new_bit_cyc + 1))
            cur_bit_cyc = new_bit_cyc

            await asyncio.sleep(1)

    async def _forward(self, in_fileno, out_fileno, uart, quit_sequence=False, stream=False):
        quit = 0
        dev_fut = uart_fut = None
        while True:
            if dev_fut is None:
                dev_fut = asyncio.get_event_loop().run_in_executor(None,
                    lambda: os.read(in_fileno, 1024))
            if uart_fut is None:
                uart_fut = asyncio.ensure_future(uart.read())

            await asyncio.wait([uart_fut, dev_fut], return_when=asyncio.FIRST_COMPLETED)

            if dev_fut.done():
                data = await dev_fut
                dev_fut = None

                if not data and not stream:
                    break

                if os.isatty(in_fileno):
                    if quit == 0 and data == b"\034":
                        quit = 1
                        continue
                    elif quit == 1 and data == b"q":
                        break
                    else:
                        quit = 0

                self.logger.trace("in->UART: <%s>", data.hex())
                await uart.write(data)
                await uart.flush()

            if uart_fut.done():
                data = await uart_fut
                uart_fut = None

                self.logger.trace("UART->out: <%s>", data.hex())
                os.write(out_fileno, data)

        for fut in [uart_fut, dev_fut]:
            if fut is not None and not fut.done():
                fut.cancel()

    async def _interact_tty(self, uart, stream):
        in_fileno  = sys.stdin.fileno()
        out_fileno = sys.stdout.fileno()

        if os.isatty(in_fileno):
            import atexit, termios

            old_stdin_attrs = termios.tcgetattr(sys.stdin)
            [iflag, oflag, cflag, lflag, ispeed, ospeed, cc] = old_stdin_attrs
            lflag &= ~(termios.ECHO | termios.ICANON | termios.ISIG)
            iflag &= ~termios.ICRNL
            cc[termios.VMIN] = 1
            new_stdin_attrs = [iflag, oflag, cflag, lflag, ispeed, ospeed, cc]
            termios.tcsetattr(in_fileno, termios.TCSADRAIN, new_stdin_attrs)

            @atexit.register
            def restore_stdin_attrs():
                termios.tcsetattr(in_fileno, termios.TCSADRAIN, old_stdin_attrs)

            self.logger.info("running on a TTY; enter `Ctrl+\\ q` to quit")

        await self._forward(in_fileno, out_fileno, uart,
                            quit_sequence=True, stream=stream)

    async def _interact_pty(self, uart):
        import pty

        master, slave = pty.openpty()
        print(os.ttyname(slave))

        await self._forward(master, master, uart)

    async def _interact_socket(self, uart, endpoint):
        endpoint = await ServerEndpoint("socket", self.logger, endpoint)
        async def forward_out():
            while True:
                try:
                    data = await asyncio.shield(endpoint.recv())
                except asyncio.CancelledError:
                    continue
                await uart.write(data)
                await uart.flush()
        async def forward_in():
            while True:
                data = await uart.read()
                try:
                    await asyncio.shield(endpoint.send(data))
                except asyncio.CancelledError:
                    continue
        forward_out_fut = asyncio.ensure_future(forward_out())
        forward_in_fut  = asyncio.ensure_future(forward_in())
        await asyncio.wait([forward_out_fut, forward_in_fut],
                           return_when=asyncio.FIRST_EXCEPTION)

    async def interact(self, device, args, uart):
        asyncio.create_task(self._monitor_errors(device))

        if args.operation == "tty":
            await self._interact_tty(uart, args.stream)
        if args.operation == "pty":
            await self._interact_pty(uart)
        if args.operation == "socket":
            await self._interact_socket(uart, args.endpoint)

# -------------------------------------------------------------------------------------------------

class UARTAppletTestCase(GlasgowAppletTestCase, applet=UARTApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    def setup_loopback(self):
        self.build_simulated_applet()
        mux_iface = self.applet.mux_interface
        mux_iface.comb += mux_iface.pads.rx_t.i.eq(mux_iface.pads.tx_t.o)

    @applet_simulation_test("setup_loopback", ["--baud", "5000000"])
    async def test_loopback(self):
        uart_iface = await self.run_simulated_applet()
        await uart_iface.write(bytes([0xAA, 0x55]))
        self.assertEqual(await uart_iface.read(2), bytes([0xAA, 0x55]))
