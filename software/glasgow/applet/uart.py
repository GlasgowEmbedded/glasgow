import argparse
import logging
from migen import *
from migen.genlib.fsm import *

from . import *
from ..gateware.pads import *
from ..gateware.uart import *


logger = logging.getLogger(__name__)


class UARTSubtarget(Module):
    def __init__(self, pads, out_fifo, in_fifo, bit_cyc):
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
    logger = logger
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
            "-b", "--baud", metavar="RATE", type=int, default=115200,
            help="set baud rate to RATE bits per second (default: %(default)s)")
        parser.add_argument(
            "--tolerance", metavar="PPM", type=int, default=50000,
            help="verify that actual baud rate is within PPM parts per million of specified"
                 " (default: %(default)s)")

    def build(self, target, args):
        try:
            bit_cyc, actual_baud = uart_bit_cyc(target.sys_clk_freq, args.baud, args.tolerance)
            logger.debug("requested baud rate %d, actual %d",
                         args.baud, actual_baud)
        except ValueError as e:
            raise GlasgowAppletError(e)

        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        target.submodules += UARTSubtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(streaming=False),
            bit_cyc=bit_cyc,
        )

    async def run(self, device, args):
        kwargs = {"async": True}
        return device.demultiplexer.claim_interface(self, self.mux_interface, args, **kwargs)

    @classmethod
    def add_interact_arguments(cls, parser):
        parser.add_argument(
            "-s", "--stream", action="store_true", default=False,
            help="continue reading from I/O port even after an end-of-file condition on stdin")

    async def interact(self, device, args, uart):
        import termios
        import atexit
        import select
        import fcntl
        import sys
        import os

        old_stdin_fl = fcntl.fcntl(sys.stdin, fcntl.F_GETFL)
        fcntl.fcntl(sys.stdin, fcntl.F_SETFL, old_stdin_fl | os.O_NONBLOCK)

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
                fcntl.fcntl(sys.stdin, fcntl.F_SETFL, old_stdin_fl)
                termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_stdin_attrs)

            logger.info("running on a TTY; enter `Ctrl+\\ q` to quit")

        quit = 0
        try:
            stdin_err_hup = False

            while True:
                fds = uart.poll()
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
                    uart.write(data)
                    uart.flush()

                elif stdin_events & (select.POLLERR | select.POLLHUP):
                    poller.unregister(sys.stdin)
                    stdin_err_hup = True

                data = uart.read()
                os.write(sys.stdout.fileno(), data)

                if not stdin_events & select.POLLIN and stdin_err_hup and not args.stream:
                    return

        except KeyboardInterrupt:
            # We can receive ^C if we're not reading from a TTY.
            pass

# -------------------------------------------------------------------------------------------------

class UARTAppletTestCase(GlasgowAppletTestCase, applet=UARTApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()

    def setup_loopback(self):
        self.build_applet_on_mock_target()
        mux_iface = self.applet.mux_interface
        mux_iface.comb += mux_iface.pads.rx_t.i.eq(mux_iface.pads.tx_t.o)

    @applet_run_test("setup_loopback", ["--baud", "5000000"])
    async def test_loopback(self):
        uart_iface = await self.run_applet_on_mock_device()
        await uart_iface.write(bytes([0xAA, 0x55]))
        self.assertEqual(await uart_iface.read(2), bytes([0xAA, 0x55]))
