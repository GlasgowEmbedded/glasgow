import argparse
import logging
from migen import *
from migen.genlib.fsm import *

from . import GlasgowApplet


logger = logging.getLogger(__name__)


class UARTSubtarget(Module):
    def __init__(self, rx, tx, out_fifo, in_fifo, baud_rate, max_deviation_ppm):
        sys_freq = int(30e6)
        bit_cyc  = sys_freq // baud_rate
        if bit_cyc <= 0:
            raise ValueError("UART output frequency ({}) is too high"
                             .format(baud_rate))

        actual_baud_rate = sys_freq // bit_cyc
        deviation_ppm = 1000000 * (actual_baud_rate - baud_rate) / baud_rate
        if deviation_ppm > max_deviation_ppm:
            raise ValueError("UART output frequency deviation ({} ppm) is too high"
                             .format(deviation_ppm))

        logger.debug("requested baud rate %d, actual %d", baud_rate, actual_baud_rate)

        ###

        self.comb += tx.oe.eq(1)

        rx_timer = Signal(max=bit_cyc)
        rx_stb   = Signal()
        rx_bitno = Signal(3)
        rx_data  = Signal(8)

        # TODO: make these readable via I2C
        rx_ferrs = Signal(16)
        rx_ovfs  = Signal(16)

        self.sync += [
            If(rx_timer == 0,
                rx_timer.eq(bit_cyc)
            ).Else(
                rx_timer.eq(rx_timer - 1)
            ),
            rx_stb.eq(rx_timer == 0)
        ]

        self.submodules.rx_fsm = FSM(reset_state="IDLE")
        self.rx_fsm.act("IDLE",
            If(~rx.i,
                NextValue(rx_timer, bit_cyc // 2),
                NextState("START")
            )
        )
        self.rx_fsm.act("START",
            If(rx_stb,
                NextState("DATA")
            )
        )
        self.rx_fsm.act("DATA",
            If(rx_stb,
                NextValue(rx_data, Cat(rx_data[1:8], rx.i)),
                NextValue(rx_bitno, rx_bitno + 1),
                If(rx_bitno == 7,
                    NextState("STOP")
                )
            )
        )
        self.rx_fsm.act("STOP",
            If(rx_stb,
                If(~rx.i,
                    rx_ferrs.eq(rx_ferrs + 1),
                    NextState("IDLE")
                ).Else(
                    NextValue(in_fifo.din, rx_data),
                    NextState("DONE")
                )
            )
        )
        self.rx_fsm.act("DONE",
            If(in_fifo.writable,
                in_fifo.we.eq(1),
                NextState("IDLE")
            ).Elif(~rx.i,
                rx_ovfs.eq(rx_ovfs + 1),
                NextState("IDLE")
            )
        )

        ###

        tx_timer  = Signal(max=bit_cyc)
        tx_stb    = Signal()
        tx_bitno  = Signal(3)
        tx_data   = Signal(8)

        self.sync += [
            If(tx_timer == 0,
                tx_timer.eq(bit_cyc)
            ).Else(
                tx_timer.eq(tx_timer - 1)
            ),
            tx_stb.eq(tx_timer == 0)
        ]

        self.submodules.tx_fsm = FSM(reset_state="IDLE")
        self.tx_fsm.act("IDLE",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(tx_timer, bit_cyc - 1),
                NextValue(tx_data, out_fifo.dout),
                NextState("START")
            ).Else(
                NextValue(tx.o, 1)
            )
        )
        self.tx_fsm.act("START",
            If(tx_stb,
                NextValue(tx.o, 0),
                NextState("DATA")
            )
        )
        self.tx_fsm.act("DATA",
            If(tx_stb,
                NextValue(tx.o, tx_data[0]),
                NextValue(tx_data, Cat(tx_data[1:8], 0)),
                NextValue(tx_bitno, tx_bitno + 1),
                If(tx_bitno == 7,
                    NextState("STOP")
                )
            )
        )
        self.tx_fsm.act("STOP",
            If(tx_stb,
                NextValue(tx.o, 1),
                NextState("IDLE")
            )
        )


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
            help="set UART baud rate to BPS bits per second")
        parser.add_argument(
            "--max-deviation", metavar="PPM", type=int, default=50000,
            help="verify that actual baud rate is within PPM parts per million of specified")

        cls.add_port_argument(parser, default="A")
        cls.add_pin_argument(parser, "rx", default=0)
        cls.add_pin_argument(parser, "tx", default=1)

    def build(self, target, args):
        io_port = target.get_io_port(args.port)
        target.submodules += UARTSubtarget(
            rx=io_port[args.pin_rx],
            tx=io_port[args.pin_tx],
            out_fifo=target.get_out_fifo(args.port),
            in_fifo=target.get_in_fifo(args.port, streaming=False),
            baud_rate=args.baud_rate,
            max_deviation_ppm=args.max_deviation,
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
