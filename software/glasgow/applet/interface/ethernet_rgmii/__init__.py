# Ref: IEEE Std 802.3-2018 §??
# Accession: G00098

import time
import struct
import logging
import asyncio
import argparse
from amaranth import *
from amaranth.utils import ceil_log2
from amaranth.lib import data, wiring, stream, cdc, io, fifo
from amaranth.lib.wiring import In, Out
from amaranth.lib.crc.catalog import CRC32_ETHERNET

from glasgow.support.logging import dump_hex
from glasgow.support.os_network import OSNetworkInterface
from glasgow.arch.ieee802_3 import *
from glasgow.protocol.snoop import *
from glasgow.gateware.accumulator import Accumulator
from glasgow.gateware.stream import Queue, AsyncQueue
from glasgow.applet import GlasgowAppletV2
from glasgow.applet.control.mdio import ControlMDIOInterface


class IODelay(wiring.Elaboratable):
    def __init__(self, i, o, *, length=8): # approx. 5 ns by default
        self.i = i
        self.o = o
        self.length = length
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        i = self.i
        for n in range(self.length):
            o = Signal()
            m.submodules[f"lut{n}"] = Instance("SB_LUT4",
                a_keep=1,
                p_LUT_INIT=C(2, 16),
                i_I0=i,
                i_I1=C(0),
                i_I2=C(0),
                i_I3=C(0),
                o_O=o)
            i = o
        m.d.comb += self.o.eq(o)

        return m


class EthernetRGMIIBus(wiring.Component):
    rx_data:  Out(4)
    rx_valid: Out(1)

    tx_data:  In(4)
    tx_valid: In(1)

    def __init__(self, ports, *, rx_delay, tx_delay):
        self._ports = ports
        self._rx_delay = rx_delay
        self._tx_delay = tx_delay

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.rx_clk_buffer  = rx_clk_buffer  = io.Buffer("i", self._ports.rx_clk)
        m.submodules.rx_ctl_buffer  = rx_ctl_buffer  = io.Buffer("i", self._ports.rx_ctl)
        m.submodules.rx_data_buffer = rx_data_buffer = io.Buffer("i", self._ports.rx_data)

        # Receiver with pseudo IO registers
        if self._rx_delay:
            m.submodules.rx_clk_delay = IODelay(rx_clk_buffer.i, ClockSignal("rx"), length=8)
        else:
            m.d.comb += ClockSignal("rx").eq(rx_clk_buffer.i)
        m.d.rx += [
            # posedge: rx_dv, negedge: rx_dv xor rx_err; ignore rx_err to avoid the need for DDR buffers
            self.rx_valid.eq(rx_ctl_buffer.i),
            self.rx_data.eq(rx_data_buffer.i),
        ]

        m.submodules.tx_clk_buffer  = tx_clk_buffer  = io.Buffer("o", self._ports.tx_clk)
        m.submodules.tx_ctl_buffer  = tx_ctl_buffer  = io.Buffer("o", self._ports.tx_ctl)
        m.submodules.tx_data_buffer = tx_data_buffer = io.Buffer("o", self._ports.tx_data)

        # Transmitter with pseudo IO registers
        if self._tx_delay:
            m.submodules.tx_clk_delay = IODelay(ClockSignal("tx"), tx_clk_buffer.o, length=8)
        else:
            m.d.comb += tx_clk_buffer.o.eq(ClockSignal("tx"))
        m.d.tx += [
            # posedge: tx_dv, negedge: tx_dv xor tx_err; ignore tx_err to avoid the need for DDR buffers
            tx_ctl_buffer.o.eq(self.tx_valid),
            tx_data_buffer.o.eq(self.tx_data),
        ]

        return m


class EthernetTransmitPath(wiring.Component):
    i: In(stream.Signature(data.StructLayout({
        "data": 8,
        "end":  1,
    })))
    o: Out(stream.Signature(data.StructLayout({
        "data": 8,
        "idle": 1,
    })))

    def elaborate(self, platform):
        m = Module()

        m.submodules.crc = crc = CRC32_ETHERNET(8).create()
        m.d.comb += crc.data.eq(self.o.p.data)

        count = Signal(16)
        with m.If(self.o.valid & self.o.ready):
            m.d.sync += count.eq(count + 1)

        with m.FSM():
            m.d.comb += self.o.valid.eq(1)

            with m.State("Wait"):
                m.d.comb += self.o.valid.eq(0)
                with m.If(self.i.valid):
                    m.d.sync += count.eq(0)
                    m.next = "Preamble"

            with m.State("Preamble"):
                m.d.comb += self.o.p.data.eq(0x55)
                with m.If(self.o.ready & (count == 7 - 1)):
                    m.next = "Frame-Start"

            with m.State("Frame-Start"):
                m.d.comb += self.o.p.data.eq(0xd5)
                m.d.comb += crc.start.eq(1)
                with m.If(self.o.ready):
                    m.next = "Frame-Data-Short"

            with m.State("Frame-Data-Short"):
                m.d.comb += self.o.p.data.eq(self.i.p.data)
                m.d.comb += self.o.valid.eq(self.i.valid)
                m.d.comb += self.i.ready.eq(self.o.ready)
                with m.If(self.i.valid & self.o.ready):
                    m.d.comb += crc.valid.eq(1)
                    with m.If(self.i.p.end):
                        m.next = "Frame-Padding"
                    with m.Elif(count == 8 + 64 - 4 - 2):
                        m.next = "Frame-Data"

            with m.State("Frame-Data"):
                m.d.comb += self.o.p.data.eq(self.i.p.data)
                m.d.comb += self.o.valid.eq(self.i.valid)
                m.d.comb += self.i.ready.eq(self.o.ready)
                with m.If(self.i.valid & self.o.ready):
                    m.d.comb += crc.valid.eq(1)
                    with m.If(self.i.p.end):
                        m.d.sync += count.eq(0)
                        m.next = "Frame-Check"

            with m.State("Frame-Padding"):
                m.d.comb += self.o.p.data.eq(0x00)
                with m.If(self.o.ready):
                    m.d.comb += crc.valid.eq(1)
                    with m.If(count == 8 + 64 - 4 - 1):
                        m.d.sync += count.eq(0)
                        m.next = "Frame-Check"

            with m.State(f"Frame-Check"):
                m.d.comb += self.o.p.data.eq(crc.crc.word_select(count[:2], 8))
                with m.If(self.o.ready):
                    with m.If(count == 4 - 1):
                        m.d.sync += count.eq(0)
                        m.next = "Interpacket-Gap"

            with m.State("Interpacket-Gap"):
                m.d.comb += self.o.p.idle.eq(1)
                with m.If(self.o.ready):
                    with m.If(count == 12 - 1):
                        m.next = "Wait"

        return m


class EthernetReceivePath(wiring.Component):
    i: In(stream.Signature(data.StructLayout({
        "data": 8,
        "idle": 1,
    })))
    o: Out(stream.Signature(data.StructLayout({
        "data": 8,
        "end":  1,
        "ok":   1,
    })))

    def elaborate(self, platform):
        m = Module()

        m.submodules.crc = crc = CRC32_ETHERNET(8).create()

        buffer = Signal(16)
        m.d.comb += Cat(self.o.p.data, crc.data).eq(buffer)
        with m.If(self.i.valid & self.i.ready):
            m.d.sync += buffer.eq(Cat(buffer[8:], self.i.payload.data))

        with m.FSM():
            n_valid = Signal(range(3))
            with m.State("Preamble"):
                # Sequence in the buffer: [ Empty  ] [ Empty  ] ( Sync 1 )
                #    ... or at n_valid 1: [ Empty  ] [ Sync 1 ] ( Sync 2 )
                #    ... or at n_valid 2: [ Sync 1 ] [ Sync 2 ] ( Sync 3 )
                m.d.comb += self.i.ready.eq(1)
                m.d.comb += crc.start.eq(1)
                with m.If(self.i.valid & self.i.p.idle):
                    m.d.sync += n_valid.eq(0)
                    m.next = "Preamble"
                with m.Elif(self.i.valid):
                    with m.If(n_valid == 2):         # if the buffer is full of valid data...
                        with m.If(buffer == 0xd555): # ... and the data is a valid preamble...
                            m.next = "Frame-Start"   # ... start the frame.
                    with m.Else():
                        m.d.sync += n_valid.eq(n_valid + 1)

            with m.State("Frame-Start"):
                # Sequence in the buffer: [  SFD   ] [ Data 1 ] ( Data 2 )
                # SFD is what triggered the transition to this state. Data 1 is having CRC computed
                # over it. Data 2 is being shifted in on this cycle (and SFD shifted out by that).
                m.d.comb += self.i.ready.eq(1)
                m.d.comb += crc.valid.eq(self.i.valid)
                with m.If(self.i.valid & self.i.p.idle):
                    m.d.sync += n_valid.eq(0)
                    m.next = "Preamble"
                with m.Elif(self.i.valid):
                    m.next = "Frame-Data"

            with m.State("Frame-Data"):
                # Sequence in the buffer: [ Data 1 ] [ Data 2 ] ( Data 3 )
                #                 ... or: [ Data 1 ] [ Data 2 ] ( Empty  )
                # Data 1 is being output on this cycle. Data 2 is having CRC computed over it.
                # Data 3 is being shifted in on this cycle (and Data 1 shifted out by that).
                # If the packet ends at Data 2, then Data 3 will have the idle flag set, and
                # the only thing left to do next cycle is to output the last word of the packet
                # and simultaneously signal end of packet and CRC status.
                m.d.comb += self.o.valid.eq(self.i.valid)
                m.d.comb += self.i.ready.eq(self.o.ready)
                m.d.comb += crc.valid.eq(self.i.valid & self.o.ready)
                with m.If(self.i.valid & self.o.ready & self.i.p.idle):
                    m.next = "Frame-End"

            with m.State("Frame-End"):
                # Sequence in the buffer: [ Data 1 ] [ Empty  ] ( Empty  )
                # The word being shifted in on this cycle is guaranteed to be empty because of
                # the presence of the interpacket gap, so it is disregarded.
                m.d.comb += self.o.p.end.eq(1)
                m.d.comb += self.o.p.ok.eq(crc.match_detected)
                m.d.comb += self.o.valid.eq(1)
                m.d.comb += self.i.ready.eq(self.o.ready)
                with m.If(self.o.ready):
                    m.d.sync += n_valid.eq(0)
                    m.next = "Preamble"

        return m


class PacketQueue(wiring.Component):
    def __init__(self, data_shape, *, data_depth, packet_depth):
        # For simplicity assume that (pointer size) == (length size).
        self._len_width  = ceil_log2(data_depth)
        self._len_depth  = packet_depth
        self._data_width = Shape.cast(data_shape).width
        self._data_depth = data_depth
        super().__init__({
            "w": In(stream.Signature(data_shape)),
            "w_commit":   In(1),
            "w_rollback": In(1),

            "r": Out(stream.Signature(data.StructLayout({
                "data": data_shape,
                "end":  1,
            }))),
            "r_length":   Out(self._len_width),
        })

    def elaborate(self, platform):
        m = Module()

        def incr(addr):
            return Mux(addr + 1 != self._data_depth, addr + 1, 0)

        m.submodules.len_fifo = len_fifo = Queue(shape=16, depth=self._len_depth)
        m.submodules.data_mem = data_mem = Memory(width=self._data_width, depth=self._data_depth)
        data_mem_w = data_mem.write_port()
        data_mem_r = data_mem.read_port()

        queued = Signal(ceil_log2(self._data_depth))

        w_offset = Signal(self._len_width)
        w_initial = Signal(self._len_width)
        m.d.comb += [
            self.w.ready.eq(len_fifo.i.ready & (queued < self._data_depth - 1)),
            len_fifo.i.payload.eq(w_offset + (self.w.ready & self.w.valid)),
            data_mem_w.data.eq(self.w.payload),
            data_mem_w.en.eq(self.w.valid),
        ]
        with m.If(self.w_rollback):
            m.d.sync += data_mem_w.addr.eq(w_initial)
            m.d.sync += w_offset.eq(0)
        with m.Elif(self.w.ready):
            with m.If(self.w.valid):
                m.d.sync += data_mem_w.addr.eq(incr(data_mem_w.addr))
                m.d.sync += w_offset.eq(w_offset + 1)
            with m.If(self.w_commit):
                m.d.comb += len_fifo.i.valid.eq(1)
                m.d.sync += w_initial.eq(Mux(self.w.valid, incr(data_mem_w.addr), data_mem_w.addr))
                m.d.sync += w_offset.eq(0)

        r_offset = Signal(self._len_width)
        r_pointer = Signal(self._len_width)
        m.d.comb += [
            self.r.valid.eq(len_fifo.o.valid),
            self.r_length.eq(len_fifo.o.payload),
            self.r.p.data.eq(data_mem_r.data),
            self.r.p.end.eq(r_offset + 1 == self.r_length),
        ]
        with m.If(self.r.ready & self.r.valid):
            m.d.comb += data_mem_r.addr.eq(incr(r_pointer))
            m.d.sync += r_pointer.eq(data_mem_r.addr)
            with m.If(self.r.p.end):
                m.d.comb += len_fifo.o.ready.eq(1)
                m.d.sync += r_offset.eq(0)
            with m.Else():
                m.d.sync += r_offset.eq(r_offset + 1)
        with m.Else():
            m.d.comb += data_mem_r.addr.eq(r_pointer)

        m.d.sync += queued.eq(queued
            - Mux(self.w_rollback, w_offset, 0)
            + (self.w.ready & self.w.valid & ~self.w_rollback)
            - (self.r.ready & self.r.valid)
        )

        return m


class EthernetRGMIIComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))
    o_flush:  Out(1)

    forwarded_packets: Out(16)
    forwarded_octets:  Out(32)
    dropped_packets:   Out(16)
    dropped_octets:    Out(32)

    def __init__(self, ports):
        self._ports = ports

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.bus = bus = EthernetRGMIIBus(self._ports, tx_delay=True, rx_delay=True)

        # RGMII clock tree
        phy_clk = Signal()
        platform.add_clock_constraint(phy_clk, 125e6)
        m.d.comb += [
            phy_clk.eq(ClockSignal("rx")),
            ClockSignal("tx").eq(phy_clk),
        ]

        # TX clock domain
        m.domains.tx = ClockDomain(clk_edge="pos")
        m.submodules += cdc.ResetSynchronizer(ResetSignal(), domain="tx")

        # OUT-FIFO -> TX-PACKET
        m.submodules.tx_packet = tx_packet = PacketQueue(8, data_depth=2048, packet_depth=32)
        with m.FSM() as tx_packet_fsm:
            tx_length = Signal(16)

            with m.State("Length-H"):
                m.d.sync += tx_length[8:16].eq(self.i_stream.payload)
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid & self.i_stream.ready):
                    m.next = "Length-L"

            with m.State("Length-L"):
                m.d.sync += tx_length[0:8].eq(self.i_stream.payload)
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid & self.i_stream.ready):
                    m.next = "Data"

            with m.State("Data"):
                m.d.comb += tx_packet.w.payload.eq(self.i_stream.payload)
                m.d.comb += tx_packet.w.valid.eq(self.i_stream.valid)
                m.d.comb += self.i_stream.ready.eq(tx_packet.w.ready)
                with m.If(self.i_stream.valid & self.i_stream.ready):
                    m.d.sync += tx_length.eq(tx_length - 1)
                    with m.If(tx_length == 1):
                        m.next = "Commit"

            with m.State("Commit"):
                m.d.comb += tx_packet.w_commit.eq(1)
                with m.If(tx_packet.w.ready):
                    m.next = "Length-H"

        # TX-PACKET -> TX-PATH
        m.submodules.tx_path = tx_path = EthernetTransmitPath()
        wiring.connect(m, tx_packet.r, tx_path.i)

        # TX-PATH -> TX-FIFO
        m.submodules.tx_fifo = tx_fifo = \
            AsyncQueue(shape=9, depth=8, i_domain="sync", o_domain="tx")
        wiring.connect(m, tx_fifo.i, tx_path.o)

        # TX-FIFO -> TX-BUS
        tx_nibble = Signal()
        with m.If(tx_fifo.o.valid):
            m.d.comb += tx_fifo.o.ready.eq(tx_nibble == 1)
            m.d.tx += tx_nibble.eq(tx_nibble + 1)
            m.d.tx += bus.tx_data.eq(tx_fifo.o.payload.word_select(tx_nibble, 4))
            m.d.tx += bus.tx_valid.eq(~tx_fifo.o.payload[8])
        with m.Else():
            m.d.tx += bus.tx_data.eq(0)
            m.d.tx += bus.tx_valid.eq(0)

        # RX clock domain
        m.domains.rx = ClockDomain(clk_edge="pos")
        m.submodules += cdc.ResetSynchronizer(ResetSignal(), domain="rx")

        # IN-FIFO <- RX-PACKET
        m.submodules.rx_packet = rx_packet = PacketQueue(8, data_depth=2048, packet_depth=32)
        with m.FSM() as rx_packet_fsm:
            with m.State("Length-H"):
                m.d.comb += self.o_stream.payload.eq(rx_packet.r_length[8:16])
                m.d.comb += self.o_stream.valid.eq(rx_packet.r.valid)
                with m.If(self.o_stream.ready & self.o_stream.valid):
                    m.next = "Length-L"
                with m.Else():
                    m.d.comb += self.o_flush.eq(1)

            with m.State("Length-L"):
                m.d.comb += self.o_stream.payload.eq(rx_packet.r_length[0:8])
                m.d.comb += self.o_stream.valid.eq(1)
                with m.If(self.o_stream.ready & self.o_stream.valid):
                    m.next = "Data"

            with m.State("Data"):
                m.d.comb += self.o_stream.payload.eq(rx_packet.r.p.data)
                m.d.comb += self.o_stream.valid.eq(rx_packet.r.valid)
                m.d.comb += rx_packet.r.ready.eq(self.o_stream.ready)
                with m.If(rx_packet.r.valid & rx_packet.r.ready & rx_packet.r.p.end):
                    m.next = "Length-H"

        # RX-PACKET <- RX-PATH
        m.submodules.rx_path = rx_path = EthernetReceivePath()

        rx_packet_length = Signal(16) # for statistics
        with m.If(rx_path.o.valid & rx_path.o.ready):
            with m.If(rx_path.o.p.end):
                m.d.sync += rx_packet_length.eq(1)
            with m.Else():
                m.d.sync += rx_packet_length.eq(rx_packet_length + 1)

        rx_packet_dropped = Signal() # for statistics
        rx_packet_forwarded = Signal() # for statistics
        with m.FSM() as rx_path_fsm:
            with m.State("Passthrough"):
                m.d.comb += [
                    rx_packet.w.payload.eq(rx_path.o.p.data),
                    rx_packet.w.valid.eq(rx_path.o.valid),
                    rx_path.o.ready.eq(1),
                ]
                with m.If(rx_path.o.valid & rx_packet.w.ready):
                    # Commit the packet if it's complete, but discard it if the CRC is bad.
                    # Discard takes priority over commit.
                    with m.If(rx_path.o.p.end & ~rx_path.o.p.ok):
                        m.d.comb += rx_packet.w_rollback.eq(1)
                        m.d.comb += rx_packet_dropped.eq(1)
                    with m.Elif(rx_path.o.p.end):
                        m.d.comb += rx_packet.w_commit.eq(1)
                        m.d.comb += rx_packet_forwarded.eq(1)
                with m.Elif(rx_path.o.valid):
                    # Discard the rest of an overlong packet, or a packet we can't receive due to
                    # the buffer being too full.
                    m.d.comb += rx_packet.w_rollback.eq(1)
                    m.next = "Discard"

            with m.State("Discard"):
                # Accept and discard the packet bytes until it ends. This is undesirable but also
                # unavoidable since buffer size is limited; protocols like TCP rely on packet loss
                # to adjust to network conditions, so, counterintuitively, this improves throughput.
                m.d.comb += rx_path.o.ready.eq(1)
                with m.If(rx_path.o.valid & rx_path.o.p.end):
                    m.d.comb += rx_packet_dropped.eq(1)
                    m.next = "Passthrough"

        # RX statistics
        m.submodules.dropped_octets_acc = dropped_octets_acc = \
            Accumulator(len(self.dropped_octets))
        m.submodules.forwarded_octets_acc = forwarded_octets_acc = \
            Accumulator(len(self.forwarded_octets))
        m.d.comb += self.dropped_octets.eq(dropped_octets_acc.sum)
        m.d.comb += self.forwarded_octets.eq(forwarded_octets_acc.sum)
        with m.If(rx_packet_dropped):
            m.d.sync += self.dropped_packets.eq(self.dropped_packets + 1)
            m.d.comb += dropped_octets_acc.addend.eq(rx_packet_length)
        with m.If(rx_packet_forwarded):
            m.d.sync += self.forwarded_packets.eq(self.forwarded_packets + 1)
            m.d.comb += forwarded_octets_acc.addend.eq(rx_packet_length)

        # RX-PATH <- RX-CDC
        m.submodules.rx_fifo = rx_fifo = \
            AsyncQueue(shape=9, depth=8, o_domain="sync", i_domain="rx")
        wiring.connect(m, rx_path.i, rx_fifo.o)

        # RX-CDC <- RX-BUS
        rx_data = Signal(8)
        rx_valid = Signal(2)
        m.d.rx += rx_data.eq(Cat(rx_data[4:], bus.rx_data))
        m.d.rx += rx_valid.eq(Cat(rx_valid[1:], bus.rx_valid))

        with m.FSM(domain="rx"):
            m.d.rx += rx_fifo.i.payload.eq(Cat(rx_data, ~rx_valid.all()))
            m.d.rx += rx_fifo.i.valid.eq(~rx_fifo.i.valid)

            with m.State("10/100-Sync"):
                with m.If(rx_valid.all() & (rx_data == 0xd5)):
                    m.d.rx += rx_fifo.i.valid.eq(1)
                    m.next = "10/100-Data"

            with m.State("10/100-Data"):
                with m.If(~rx_valid.all()):
                    m.next = "10/100-Sync"

        return m


class Statistic:
    def __init__(self, *, wraps_at=1 << 32):
        self._current  = 0
        self._previous = 0
        self._wraps_at = wraps_at

    def update(self, value):
        self._current = value % self._wraps_at

    def increment(self, amount=1):
        self._current = (self._current + amount) % self._wraps_at

    def average(self, period):
        delta = (self._current - self._previous) % self._wraps_at
        self._previous = self._current
        return delta / period


class NetworkStatistics:
    def __init__(self):
        self.packets_forwarded = Statistic(wraps_at=1 << 16)
        self.octets_forwarded  = Statistic()
        self.packets_dropped   = Statistic(wraps_at=1 << 16)
        self.octets_dropped    = Statistic()

    def display(self, logger, *, title, period):
        def si_prefix(measurement):
            if measurement < 1e3:
                return measurement / 1e0, " "
            elif measurement < 1e6:
                return measurement / 1e3, "k"
            elif measurement < 1e9:
                return measurement / 1e6, "M"
            else:
                return measurement / 1e9, "G"

        packets_forwarded = self.packets_forwarded.average(period)
        octets_forwarded  = self.octets_forwarded.average(period)
        packets_dropped   = self.packets_dropped.average(period)
        octets_dropped    = self.octets_dropped.average(period)

        logger.info("%s statistics:", title)
        logger.info("  forwarded: %5.1f %sbps (%5.1f %spps)",
            *si_prefix(octets_forwarded * 8),
            *si_prefix(packets_forwarded))
        logger.info("  dropped:   %5.1f %sbps (%5.1f %spps)",
            *si_prefix(octets_dropped * 8),
            *si_prefix(packets_dropped))


class EthernetRGMIIApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "transmit and receive Ethernet packets using an RGMII PHY"
    preview = True
    description = """
    TODO

    ::
        sudo ip tuntap add glasgow0 mode tap user $USER
        sudo ip link set glasgow0 up
    """
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "rx_clk", default=True, required=True)
        access.add_pins_argument(parser, "rx_ctl", default=True, required=True)
        access.add_pins_argument(parser, "rx_data", width=4, default=True, required=True)
        access.add_pins_argument(parser, "tx_clk", default=True, required=True)
        access.add_pins_argument(parser, "tx_ctl", default=True, required=True)
        access.add_pins_argument(parser, "tx_data", width=4, default=True, required=True)
        access.add_pins_argument(parser, "mdc", default=True, required=True)
        access.add_pins_argument(parser, "mdio", default=True, required=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            ports = self.assembly.add_port_group(
                rx_clk=args.rx_clk, rx_ctl=args.rx_ctl, rx_data=args.rx_data,
                tx_clk=args.tx_clk, tx_ctl=args.tx_ctl, tx_data=args.tx_data,
            )
            component = self.assembly.add_submodule(EthernetRGMIIComponent(ports))
            self.__pipe = self.assembly.add_inout_pipe(component.o_stream, component.i_stream,
                in_flush=component.o_flush)
            # Combine all registers to support atomic capture for readout.
            self.__reg_statistics = self.assembly.add_ro_register(Cat(
                component.forwarded_packets,
                component.forwarded_octets,
                component.dropped_packets,
                component.dropped_octets,
            ))

            self.mdio_iface = ControlMDIOInterface(self.logger, self.assembly,
                mdc=args.mdc, mdio=args.mdio)

    async def setup(self, args):
        # Configure for 100 Mbps full duplex, no autonegotiation
        await self.mdio_iface.c22_write(0, REG_BASIC_CONTROL_addr,
            REG_BASIC_CONTROL(DUPLEXMD=1, SPD_SEL_0=1).to_int())

    @classmethod
    def add_run_arguments(cls, parser: argparse.ArgumentParser):
        parser.add_argument("interface", nargs="?", type=str, default="glasgow0",
            metavar="INTERFACE", help="forward packets to and from this TAP interface")
        parser.add_argument("--snoop", dest="snoop_file", type=argparse.FileType("wb"),
            metavar="SNOOP-FILE", help="save communication log to a file in RFC 1761 format")

    async def run(self, args):
        os_iface = OSNetworkInterface(args.interface)

        tx_stats = NetworkStatistics()
        rx_stats = NetworkStatistics()

        if args.snoop_file:
            snoop_writer = SnoopWriter(args.snoop_file, datalink_type=SnoopDatalinkType.Ethernet)
            def snoop_packet(packet):
                snoop_writer.write(SnoopPacket(packet, timestamp_ns=time.time_ns()))
                return packet
        else:
            def snoop_packet(packet):
                return packet

        async def forward_tx():
            os_task = usb_task = None
            buffer, buffered = [], 0
            while True:
                if os_task is None:
                    os_task = asyncio.create_task(os_iface.recv())
                if usb_task is None and buffered > 0:
                    data = []
                    for packet in buffer:
                        tx_stats.octets_forwarded.increment(len(packet))
                        tx_stats.packets_forwarded.increment()
                        data.append(struct.pack(">H", len(packet)))
                        data.append(packet)
                    await self.__pipe.send(b"".join(data))
                    usb_task = asyncio.create_task(self.__pipe.flush())
                    buffer.clear()
                    buffered = 0
                done, pending = await asyncio.wait([
                    task for task in (os_task, usb_task) if task
                ], return_when=asyncio.FIRST_COMPLETED)
                if os_task in done:
                    for packet in await os_task:
                        packet = snoop_packet(packet)
                        self.logger.debug("tx queue data=<%s>", dump_hex(packet))
                        buffer.append(packet)
                        buffered += len(packet)
                        while buffered > 4096 * 512: # the same as demultiplexer buffer size
                            self.logger.debug("tx drop data=<%s>", dump_hex(buffer[0]))
                            tx_stats.octets_dropped.increment(len(buffer[0]))
                            tx_stats.packets_dropped.increment()
                            buffered -= len(buffer[0])
                            del buffer[0]
                        os_task = None
                if usb_task in done:
                    usb_task = None

        async def forward_rx():
            while True:
                length, = struct.unpack(">H", await self.__pipe.recv(2))
                packet = snoop_packet(await self.__pipe.recv(length))
                if length < 64:
                    self.logger.warning("rx runt frame length=%d", length)
                if length >= 14: # must be at least ETH_HLEN, or we'll get EINVAL on Linux
                    self.logger.debug("rx queue data=<%s>", dump_hex(packet))
                    await os_iface.send([packet])

        async def poll_stats(period=1.):
            while True:
                await asyncio.sleep(period)
                # This is a lot of ceremony for counter readout, but it prevents infeasible numbers
                # from confusingly appearing in the results (like ≥99.5% utilization, which would
                # suggest no IPG at all).
                statistics_cat = await self.__reg_statistics.get()
                forwarded_packets, forwarded_octets, dropped_packets, dropped_octets = \
                    struct.unpack("<HLHL", statistics_cat.to_bytes(12, byteorder="little"))
                rx_stats.packets_forwarded.update(forwarded_packets)
                rx_stats.octets_forwarded.update(forwarded_octets)
                rx_stats.packets_dropped.update(dropped_packets)
                rx_stats.octets_dropped.update(dropped_octets)

        async def log_stats(period=5.):
            while True:
                await asyncio.sleep(period)
                tx_stats.display(self.logger, title="tx", period=period)
                rx_stats.display(self.logger, title="rx", period=period)

        async with asyncio.TaskGroup() as group:
            group.create_task(forward_rx())
            group.create_task(forward_tx())
            group.create_task(poll_stats())
            group.create_task(log_stats())

    @classmethod
    def tests(cls):
        from . import test
        return test.EthernetRGMIIAppletTestCase
