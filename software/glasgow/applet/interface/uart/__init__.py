import os
import sys
import logging
import asyncio
from migen import *

from ....gateware.pads import *
from ....gateware.uart import *
from ... import *


class UARTSubtarget(Module):
    def __init__(self, pads, out_fifo, in_fifo, max_bit_cyc, parity,
                 bit_cyc, rx_errors):
        self.submodules.uart = uart = UART(pads, bit_cyc=max_bit_cyc, parity=parity)

        self.comb += uart.bit_cyc.eq(bit_cyc)

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

    def build(self, target, args):
        # We support any baud rates, even absurd ones like 60 baud, if you want, but the applet
        # will have to be rebuilt for anything slower than 9600. This is why the baud rate is
        # a build argument, even though the applet will never be rebuilt as long as you stay
        # above 9600.
        max_bit_cyc = self.derive_clock(
            input_hz=target.sys_clk_freq, output_hz=min(9600, args.baud))

        self.__sys_clk_freq = target.sys_clk_freq
        bit_cyc,   self.__addr_bit_cyc = target.registers.add_rw(32)
        rx_errors, self.__addr_rx_errors = target.registers.add_ro(16)

        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(UARTSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(),
            max_bit_cyc=max_bit_cyc,
            parity=args.parity,
            bit_cyc=bit_cyc,
            rx_errors=rx_errors,
        ))

        subtarget.comb += subtarget.uart.bit_cyc.eq(bit_cyc)

    async def run(self, device, args):
        bit_cyc = self.derive_clock(
            input_hz=self.__sys_clk_freq, output_hz=args.baud,
            min_cyc=2, max_deviation_ppm=args.tolerance)
        await device.write_register(self.__addr_bit_cyc, bit_cyc, width=4)
        return await device.demultiplexer.claim_interface(self, self.mux_interface, args)

    @classmethod
    def add_interact_arguments(cls, parser):
        # TODO(py3.7): add required=True
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_tty = p_operation.add_parser(
            "tty", help="connect UART to stdin/stdout")
        p_tty.add_argument(
            "-s", "--stream", action="store_true", default=False,
            help="continue reading from I/O port even after an end-of-file condition on stdin")

        p_pty = p_operation.add_parser(
            "pty", help="connect UART to a pseudo-terminal device file")

    async def _monitor_errors(self, device):
        cur_count = 0
        while True:
            await asyncio.sleep(1)

            new_count = await device.read_register(self.__addr_rx_errors, width=2)
            delta = new_count - cur_count
            if new_count < cur_count:
                delta += 1 << 16
            cur_count = new_count

            if delta > 0:
                self.logger.warning("%d frame or parity errors detected", delta)

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

    async def interact(self, device, args, uart):
        asyncio.create_task(self._monitor_errors(device))

        if args.operation == "tty":
            await self._interact_tty(uart, args.stream)
        if args.operation == "pty":
            await self._interact_pty(uart)

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
