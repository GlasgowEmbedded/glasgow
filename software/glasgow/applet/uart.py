import argparse
import logging
from migen import *
from migen.genlib.fsm import *

from . import GlasgowApplet
from ..gateware.pads import *
from ..gateware.uart import *


logger = logging.getLogger(__name__)


class UARTSubtarget(Module):
    def __init__(self, pads, out_fifo, in_fifo, baud_rate, max_deviation):
        bit_cyc, actual_baud_rate = uart_bit_cyc(30e6, baud_rate, max_deviation)
        logger.debug("requested baud rate %d, actual %d", baud_rate, actual_baud_rate)

        self.submodules.uart = UART(pads, bit_cyc)

        ###

        self.comb += [
            in_fifo.din.eq(self.uart.rx_data),
            in_fifo.we.eq(self.uart.rx_rdy),
            self.uart.rx_ack.eq(in_fifo.writable)
        ]

        self.comb += [
            self.uart.tx_data.eq(out_fifo.dout),
            out_fifo.re.eq(self.uart.tx_rdy),
            self.uart.tx_ack.eq(out_fifo.readable),
        ]


class UARTApplet(GlasgowApplet, name="uart"):
    help = "communicate via UART"
    description = """
    Transmit and receive data via UART.

    Any baud rate is supported. Only 8n1 mode is supported.

    Port voltage is sensed and monitored.
    """

    @classmethod
    def add_build_arguments(cls, parser):
        parser.add_argument(
            "-b", "--baud-rate", metavar="BPS", type=int, default=115200,
            help="set UART baud rate to BPS bits per second (default: %(default)s)")
        parser.add_argument(
            "--max-deviation", metavar="PPM", type=int, default=50000,
            help="verify that actual baud rate is within PPM parts per million of specified"
                 " (default: %(default)s)")

        cls.add_port_argument(parser, default="A")
        cls.add_pin_argument(parser, "rx", default=0)
        cls.add_pin_argument(parser, "tx", default=1)

    def build(self, target, args):
        io_port = target.get_io_port(args.port)
        target.submodules += UARTSubtarget(
            pads=Pads(rx=io_port[args.pin_rx],
                      tx=io_port[args.pin_tx]),
            out_fifo=target.get_out_fifo(args.port),
            in_fifo=target.get_in_fifo(args.port, streaming=False),
            baud_rate=args.baud_rate,
            max_deviation=args.max_deviation,
        )

    @classmethod
    def add_run_arguments(cls, parser):
        g_voltage = parser.add_mutually_exclusive_group(required=True)
        g_voltage.add_argument(
            "-V", "--voltage", metavar="VOLTS", type=float, nargs="?", default=None,
            help="set I/O port voltage explicitly")
        g_voltage.add_argument(
            "-M", "--mirror-voltage", action="store_true", default=False,
            help="sense and mirror I/O port voltage")

        parser.add_argument(
            "-s", "--stream", action="store_true", default=False,
            help="continue reading from I/O port even after an end-of-file condition on stdin")

    def run(self, device, args):
        import termios
        import atexit
        import select
        import fcntl
        import sys
        import os

        stdin_fl = fcntl.fcntl(sys.stdin, fcntl.F_GETFL)
        fcntl.fcntl(sys.stdin, fcntl.F_SETFL, stdin_fl | os.O_NONBLOCK)

        poller = device.get_poller()
        poller.register(sys.stdin,  select.POLLERR | select.POLLHUP | select.POLLIN)
        poller.register(sys.stdout, select.POLLERR | select.POLLHUP)

        if sys.stdin.isatty():
            old_stdin_attrs = termios.tcgetattr(sys.stdin)
            [iflag, oflag, cflag, lflag, ispeed, ospeed, cc] = old_stdin_attrs
            lflag &= ~(termios.ECHO | termios.ICANON | termios.ISIG)
            cc[termios.VMIN]  = 0
            cc[termios.VTIME] = 0
            new_stdin_attrs = [iflag, oflag, cflag, lflag, ispeed, ospeed, cc]
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, new_stdin_attrs)

            @atexit.register
            def restore_stdin_attrs():
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_stdin_attrs)

            logger.info("running on a TTY; enter `Ctrl+\\ q` to quit")

        if args.mirror_voltage:
            device.mirror_voltage(args.port)
        else:
            device.set_voltage(args.port, args.voltage)

        device.timeout = None
        port = device.get_port(args.port, async=True)

        quit = 0
        try:
            stdin_err_hup = False

            while True:
                fds = device.poll()
                try:
                    stdin_events = [ev[1] for ev in fds if ev[0] == sys.stdin.fileno()][0]
                except IndexError:
                    stdin_events = 0

                if stdin_events & select.POLLIN:
                    data = os.read(sys.stdin.fileno(), 1024)
                    if os.isatty(sys.stdin.fileno()):
                        if quit == 0 and data == b"\034":
                            quit = 1
                            continue
                        elif quit == 1 and data == b"q":
                            return
                        else:
                            quit = 0
                    port.write(data)
                    port.flush()

                elif stdin_events & (select.POLLERR | select.POLLHUP):
                    poller.unregister(sys.stdin)
                    stdin_err_hup = True

                data = port.read()
                os.write(sys.stdout.fileno(), data)

                if not stdin_events & select.POLLIN and stdin_err_hup and not args.stream:
                    return

        except KeyboardInterrupt:
            # We can receive ^C if we're not reading from a TTY.
            pass
