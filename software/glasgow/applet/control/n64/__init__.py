import os
import sys
import logging
import asyncio
import argparse
from amaranth import *
from amaranth.lib import io, cdc

from ....support.endpoint import *
from ... import *


def seek_skip(f, num):
    if f.seekable():
        f.seek(num, 1)
    else:
        f.read(num)

def parse_tas(f):
    signature = f.peek(4)
    if signature[0:4] != b'M64\x1A':
        print(f"Unrecognized header, probably raw file: {signature}")
        if f.seekable():
            size = f.seek(0, 2)
            f.seek(0)
            return size // 4
        return -1
    f.read(4)

    version = f.read(4)
    if len(version) != 4:
        raise
    version = int.from_bytes(version, "little")

    seek_skip(f, 0x010)

    frame_count = f.read(4)
    if len(frame_count) != 4:
        raise
    frame_count = int.from_bytes(frame_count, "little")

    if version == 1 or version == 2:
        seek_skip(f, 0x1e4)
    elif version == 3:
        seek_skip(f, 0x3e4)
    else:
        raise

    print(f'VERSION: {version}, frames: {frame_count}\n')

    return frame_count

def open_tas(path):
    f = open(path, 'rb')

    frame_count = parse_tas(f)

    return f, frame_count

class ControlN64Subtarget(Elaboratable):
    def __init__(self, ports, out_fifo, in_fifo, micro_cyc, path):
        self.ports = ports
        self.out_fifo = out_fifo
        self.in_fifo = in_fifo
        self.micro_cyc = micro_cyc
        self.path = path

        self.log_size = 64
        self.log = Signal(self.log_size * 8)
        self.log_r = Signal(range(0, self.log_size - 1))
        self.log_w = Signal.like(self.log_r)

    def send_log(self, data, size):
        return [
            self.log.bit_select(self.log_w * 8, size * 8).eq(data),
            self.log_w.eq((self.log_w + size) % self.log_size),
        ]

    def send_byte(self, byte):
        return self.send_log(byte, 1)

    def char_byte(self, char):
        return bytes(char, 'ascii')[0]

    def hex_char(self, nibble):
        return self.char_byte('0') + nibble + (nibble >= 10) * 7

    def send_hex(self, byte):
        return self.send_log(Cat(self.hex_char(byte[0:4]), self.hex_char(byte[4:8])), 2)

    def send_char(self, char):
        return self.send_byte(self.char_byte(char))

    def elaborate(self, platform):
        m = Module()

        frames = 1024
        frame_size = 4
        init = [0] * frames

        if self.path:
            f, frame_count = open_tas(self.path)
            frames = frame_count + 1
            data = f.read(frame_count * 4)
            frame_list = zip(*(iter(data),) * 4)
            init = [int.from_bytes(frame, 'big') for frame in frame_list] + [0]

        m.submodules.mem = mem = Memory(width=32, depth=frames, init=init)

        di = Signal(1)
        m.submodules.d_buffer = d_buffer = io.Buffer("io", self.ports.data)
        m.submodules.isync = cdc.FFSynchronizer(d_buffer.i, di)

        rdport = mem.read_port()
        wrport = mem.write_port()

        read_index = Signal(range(frames))
        write_index = Signal.like(read_index)
        length = Signal(32)

        m.d.sync += rdport.addr.eq(read_index)
        m.d.sync += wrport.addr.eq(write_index)

        with m.If(self.in_fifo.w_rdy & (self.log_r != self.log_w)):
            m.d.comb += [
                self.in_fifo.w_data.eq(self.log.word_select(self.log_r, 8)),
                self.in_fifo.w_en.eq(1),
            ]
            m.d.sync += self.log_r.eq((self.log_r + 1) % self.log_size)

        if not self.path:
            fifo_buffer = Signal((frame_size - 1) * 8)
            fifo_offset = Signal(range(0, frame_size - 1))
            m.d.comb += self.out_fifo.r_en.eq((write_index + 1) % frames != read_index)
            with m.If(self.out_fifo.r_rdy & self.out_fifo.r_en):
                got_buffer = Signal(frame_size * 8)
                m.d.comb += got_buffer.eq((fifo_buffer << 8) | self.out_fifo.r_data)
                with m.If(fifo_offset == frame_size - 1):
                    m.d.sync += [
                        wrport.data.eq(got_buffer),
                        wrport.en.eq(1),
                        write_index.eq((write_index + 1) % frames),
                        fifo_buffer.eq(0),
                        fifo_offset.eq(0),
                    ]
                with m.Else():
                    m.d.sync += [
                        fifo_buffer.eq(got_buffer),
                        fifo_offset.eq(fifo_offset + 1),
                    ]
        else:
            m.d.comb += write_index.eq(frames - 1)

        timeout_cyc = self.micro_cyc * 10
        low_timer = Signal(range(timeout_cyc))
        high_timer = Signal.like(low_timer)

        got_byte = Signal(8)
        got_bits = Signal(range(7))

        got_data = Signal(8 * 37)
        got_bytes = Signal(range(36))
        want_bytes = Signal(range(36))

        send_data = Signal(8 * 34)
        send_len = Signal(range(33 * 8))
        send_index = Signal.like(send_len)
        send_index_inv = Signal.like(send_len)
        m.d.comb += send_index_inv.eq(send_len - send_index - 1)

        send_bit = Signal(1)
        m.d.comb += send_bit.eq(send_data.bit_select(send_index_inv, 1))

        edge_len = Signal(range(3 * self.micro_cyc))
        m.d.comb += edge_len.eq((3 - 2 * (send_bit != d_buffer.o)) * self.micro_cyc)

        wide_stop = Signal(1)
        m.d.comb += wide_stop.eq(1)
        stop_low_len = Signal.like(edge_len)
        m.d.comb += stop_low_len.eq((1 + wide_stop) * self.micro_cyc)
        stop_high_len = Signal.like(edge_len)
        m.d.comb += stop_high_len.eq((2 - wide_stop) * self.micro_cyc)

        byte_read = Signal(8)
        bit = Signal(1)
        m.d.comb += bit.eq(low_timer < high_timer)
        m.d.comb += byte_read.eq((got_byte << 1) | bit)

        with m.FSM():
            with m.State("RESET"):
                with m.If(di):
                    m.next = "IDLE"
            with m.State("IDLE"):
                m.d.sync += got_bits.eq(0)
                m.d.sync += got_bytes.eq(0)
                m.d.sync += want_bytes.eq(0)
                m.d.sync += low_timer.eq(0)
                m.d.sync += send_index.eq(0)
                with m.If(~di):
                    m.next = "RECV_LOW"
            with m.State("RECV_LOW"):
                m.d.sync += low_timer.eq(low_timer + 1)
                m.d.sync += high_timer.eq(0)
                with m.If(di):
                    m.next = "RECV_HIGH"
                with m.Elif(low_timer == timeout_cyc):
                    m.next = "TIMEOUT"
            with m.State("RECV_HIGH"):
                m.d.sync += high_timer.eq(high_timer + 1)
                with m.If(~di):
                    m.d.sync += got_byte.eq(byte_read)

                    m.d.sync += low_timer.eq(0)
                    with m.If(got_bits == 7):
                        m.d.sync += got_bits.eq(0)
                        m.d.sync += got_data.word_select(got_bytes, 8).eq(byte_read)
                        with m.If(got_bytes == 0):
                            with m.Switch(byte_read):
                                with m.Case(0x03):
                                    m.d.sync += want_bytes.eq(34)
                                    m.next = "RECV_LOW"
                                with m.Case(0x02):
                                    m.d.sync += want_bytes.eq(2)
                                    m.next = "RECV_LOW"
                                with m.Default():
                                    m.next = "RECV_LOW_STOP"
                        with m.Else():
                            with m.If(got_bytes == want_bytes):
                                m.next = "RECV_LOW_STOP"
                            with m.Else():
                                m.next = "RECV_LOW"
                        m.d.sync += got_bytes.eq(got_bytes + 1)
                    with m.Else():
                        m.d.sync += got_bits.eq(got_bits + 1)
                        m.next = "RECV_LOW"
                with m.Elif(high_timer == timeout_cyc):
                    m.next = "TIMEOUT"
            with m.State("RECV_LOW_STOP"):
                with m.If(di):
                    m.d.sync += high_timer.eq(0)
                    m.next = "RECV_HIGH_STOP"
            with m.State("RECV_HIGH_STOP"):
                m.d.sync += high_timer.eq(high_timer + 1)
                m.d.sync += low_timer.eq(0)
                with m.If(high_timer >= self.micro_cyc * 3):
                    with m.Switch(got_data[:8]):
                        with m.Case(0x00, 0xFF):
                            m.d.sync += self.send_char('P')
                            m.d.sync += send_len.eq(3 * 8)
                            m.d.sync += send_data[0:24].eq(0x050002)
                            m.d.sync += read_index.eq(0)
                            m.next = "SEND_LOW"
                        with m.Case(0x01):
                            m.d.sync += send_len.eq(4 * 8)
                            with m.If(read_index != write_index):
                                m.d.sync += self.send_char('D')
                                m.d.sync += send_data[0:32].eq(rdport.data)
                                m.d.sync += read_index.eq((read_index + 1) % frames)
                            with m.Else():
                                m.d.sync += self.send_char('F')
                                m.d.sync += send_data[0:32].eq(0)
                            m.next = "SEND_LOW"
                        with m.Default():
                            m.d.sync += self.send_char('U')
                            m.next = "LOG_UNKNOWN"
            with m.State("SEND_LOW"):
                m.d.comb += d_buffer.oe.eq(1)
                m.d.comb += d_buffer.o.eq(0)
                m.d.sync += low_timer.eq(low_timer + 1)
                with m.If(low_timer == edge_len):
                    m.d.sync += high_timer.eq(0)
                    m.next = "SEND_HIGH"
            with m.State("SEND_HIGH"):
                m.d.comb += d_buffer.oe.eq(1)
                m.d.comb += d_buffer.o.eq(1)
                m.d.sync += high_timer.eq(high_timer + 1)
                with m.If(high_timer == edge_len):
                    m.d.sync += low_timer.eq(0)
                    with m.If(send_index + 1 == send_len):
                        m.next = "SEND_LOW_STOP"
                    with m.Else():
                        m.d.sync += send_index.eq(send_index + 1)
                        m.next = "SEND_LOW"
            with m.State("SEND_LOW_STOP"):
                m.d.comb += d_buffer.oe.eq(1)
                m.d.comb += d_buffer.o.eq(0)
                m.d.sync += low_timer.eq(low_timer + 1)
                with m.If(low_timer == stop_low_len):
                    m.d.sync += high_timer.eq(0)
                    m.next = "SEND_HIGH_STOP"
            with m.State("SEND_HIGH_STOP"):
                m.d.comb += d_buffer.oe.eq(1)
                m.d.comb += d_buffer.o.eq(1)
                m.d.sync += high_timer.eq(high_timer + 1)
                with m.If(high_timer == stop_high_len):
                    m.next = "WAIT_IDLE"
            with m.State("LOG_UNKNOWN"):
                m.next = "WAIT_IDLE"
            with m.State("TIMEOUT"):
                m.next = "WAIT_IDLE"
            with m.State("WAIT_IDLE"):
                with m.If(di):
                    with m.If(high_timer == self.micro_cyc * 4):
                        m.next = "IDLE"
                    with m.Else():
                        m.d.sync += high_timer.eq(high_timer + 1)
                with m.Else():
                    m.d.sync += high_timer.eq(0)

        return m


class ControlN64Applet(GlasgowApplet):
    logger = logging.getLogger(__name__)
    help = "tool-assisted speedrun playback for Nintendo 64"
    description = """
    Play back tool-assisted speedruns on a Nintendo 64 console.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_argument(parser, "data", default=True)

        parser.add_argument(
            "--preload", default=None, help="file to play back (default: stream at runtime)")

    def build(self, target, args):
        micro_cyc = self.derive_clock(input_hz=target.sys_clk_freq, output_hz=1000000) + 1

        print(f'micro_cyc: {micro_cyc}')

        self.__sys_clk_freq = target.sys_clk_freq

        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(ControlN64Subtarget(
            ports=iface.get_port_group(data=args.pin_data),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(),
            micro_cyc=micro_cyc,
            path=args.preload,
        ))

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

    async def run(self, device, args):
        pulls_high = {args.pin_data}

        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args,
                                                           pull_high=pulls_high)

        await device.set_voltage(args.port_spec, 3.3)

        return iface

    @classmethod
    def add_interact_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_tty = p_operation.add_parser("tty", help="read TAS from stdin")

        p_file = p_operation.add_parser("file", help="read TAS from file")
        p_file.add_argument(
            "file", metavar="FILE", type=argparse.FileType("rb"),
            help="read commands from file (.m64)")

    async def _forward(self, in_file, out_file, uart, quit_sequence=False):
        bytes_left = parse_tas(in_file)
        if bytes_left > 0:
            bytes_left = bytes_left * 4
        quit = 0
        dev_fut = uart_fut = None
        while True:
            if dev_fut is None:
                def handler():
                    nonlocal bytes_left
                    nonlocal in_file
                    if bytes_left < 0:
                        return in_file.read(1024)
                    elif bytes_left == 0:
                        return b''
                    else:
                        ret = in_file.read1(bytes_left)
                        bytes_left -= len(ret)
                        return ret
                dev_fut = asyncio.get_event_loop().run_in_executor(None, handler)
            if uart_fut is None:
                uart_fut = asyncio.ensure_future(uart.read())

            await asyncio.wait([uart_fut, dev_fut], return_when=asyncio.FIRST_COMPLETED)

            if dev_fut.done():
                data = await dev_fut
                dev_fut = None

                if in_file.isatty():
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
                if (not in_file.isatty()) and len(data) == 0:
                    break

            if uart_fut.done():
                data = await uart_fut
                uart_fut = None

                self.logger.trace("UART->out: <%s>", data.hex())
                out_file.write(data)

        for fut in [uart_fut, dev_fut]:
            if fut is not None and not fut.done():
                fut.cancel()

    async def _interact_tty(self, uart):
        in_file  = sys.stdin.buffer
        out_file = sys.stdout.buffer
        quit_sequence = False

        if in_file.isatty():
            quit_sequence = True
            self.logger.info("running on a TTY; enter `Ctrl+\\ q` to quit")

        await self._forward(in_file, out_file, uart, quit_sequence=quit_sequence)

    async def _interact_file(self, uart, f):
        await self._forward(f, sys.stdout.buffer, uart)

    async def interact(self, device, args, uart):
        if args.operation is None or args.operation == "tty":
            await self._interact_tty(uart)
        if args.operation == "file":
            await self._interact_file(uart, args.file)

    @classmethod
    def tests(cls):
        from . import test
        return test.ControlN64AppletTestCase
