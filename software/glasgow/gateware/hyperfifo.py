from amaranth import *
from amaranth.lib import data, wiring, stream
from amaranth.lib.wiring import In, Out
from amaranth.vendor import SiliconBluePlatform

from . import octoram
from .stream import Queue, StreamBuffer


__all__ = ["HyperFIFO"]


class HyperFIFO(wiring.Component):
    """A FIFO that stores data not fitting in the on-FPGA block or LUT RAM in external DRAM.

    The working principle is as follows. Internally, both the write side and the read side are
    buffered with a small FIFO backed by FPGA memory (block or LUT RAM), with the default depth
    configured to efficiently use platform resources. While the internal write FIFO contains little
    data, it is connected directly to the read FIFO, adding only 3 cycles of latency compared to
    a purely on-FPGA synchronous FIFO. Once the write FIFO level crosses the threshold of a single
    DRAM burst size, it is disconnected from the internal read FIFO and data is written into DRAM
    instead. From that point on, while there is any data still contained in DRAM, it is alternately
    written to and read from DRAM in full bursts.
    """

    dram: Out(octoram.Signature())
    w_data: In(stream.Signature(8))
    r_data: Out(stream.Signature(8))

    def __init__(self, *, w_depth=None, r_depth=None, spill_base, spill_size, burst_size=64):
        assert w_depth is None or w_depth >= 2 * burst_size
        assert r_depth is None or r_depth >= 2 * burst_size
        assert spill_base % burst_size == 0
        assert spill_size % burst_size == 0
        assert burst_size in (1 << n for n in range(1, 11))

        # All of the following attributes are in words/beats (16-bit units).
        # Note that the constructor arguments are in bytes.
        self._w_depth    = w_depth
        self._r_depth    = r_depth
        self._spill_base = spill_base >> 1
        self._spill_size = spill_size >> 1
        self._spill_last = self._spill_base + self._spill_size
        self._burst_size = burst_size >> 1

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        match platform:
            case SiliconBluePlatform():
                # no LUTRAM and only 512-byte BRAMs; any depth under 512 wastes space
                default_depth = 512
            case _:
                # unknown platform, assume LUTRAM exists and minimize resource use
                default_depth = 4 * self._burst_size

        # These queues are 8-bit to ensure that if just a single byte is written into the FIFO,
        # it would not cause a deadlock while waiting to fill the other half of a 16-byte FIFO.
        # It reduces maximum efficiency, but this implementation is written to handle buffering
        # for USB 2 packets, where the memory is over 4x faster than the USB interface, so it is
        # inconsequential in practice.
        m.submodules.w_queue = w_queue = Queue(
            shape=data.ArrayLayout(8, 2), depth=self._w_depth or default_depth)
        m.submodules.r_queue = r_queue = Queue(
            shape=data.ArrayLayout(8, 2), depth=self._r_depth or default_depth)

        # This buffer stores the command if `self.dram.commands` does not consume it until
        # the entire burst is complete. (Different memory controllers have different behavior.)
        m.submodules.cmd_buf = cmd_buf = StreamBuffer(self.dram.commands.payload.shape())
        wiring.connect(m, cmd_buf.o, wiring.flipped(self.dram.commands))

        ram_w_addr = Signal(31, init=self._spill_base)
        ram_r_addr = Signal(31, init=self._spill_base)
        ram_level  = Signal(range(self._spill_size + 1))
        burst_len  = Signal(range(self._burst_size))

        w_burst_ready = Signal()
        r_burst_ready = Signal()
        m.d.comb += w_burst_ready.eq((w_queue.level >= self._burst_size) &
                                     (ram_level < self._spill_size))
        m.d.comb += r_burst_ready.eq((r_queue.depth - r_queue.level >= self._burst_size) &
                                     (ram_level > 0))

        # Operation concept: there are 3 modes, Level-0, Level-1, and Level-2.
        #  * Level-0: w_data -> r_data                                 (direct port connection)
        #  * Level-1: w_data -> w_queue -> r_queue -> r_data           (connection via FPGA RAM)
        #  * Level-2: w_data -> w_queue -> dram -> r_queue -> r_data   (connection via OPI DRAM)
        #
        # Every time there is sufficient backpressure, HyperFIFO switches one mode higher; every
        # time the queues clear up, HyperFIFO switches one mode lower. Also, it is particularly
        # important to have Level-0 because this is the only mode in which single bytes are
        # handled; every other mode only deals in 16-bit words.

        w_gearbox = stream.Signature(8).flip().create()
        w_partial = Signal()
        w_bypass  = Signal()
        with m.If(~w_partial):
            m.d.sync += w_queue.i.payload[0].eq(w_gearbox.payload)
        m.d.comb += [
            w_queue.i.payload[1].eq(w_gearbox.payload),
            w_queue.i.valid.eq(w_gearbox.valid & w_partial),
            w_gearbox.ready.eq(w_queue.i.ready | ~w_partial),
        ]
        with m.If(w_bypass):
            m.d.sync += w_partial.eq(0)
        with m.Elif(w_gearbox.valid & w_gearbox.ready):
            m.d.sync += w_partial.eq(~w_partial)

        r_gearbox = stream.Signature(8).create()
        r_partial = Signal()
        m.d.comb += [
            r_gearbox.payload.eq(r_queue.o.payload[r_partial]),
            r_gearbox.valid.eq(r_queue.o.valid),
            r_queue.o.ready.eq(r_partial & r_gearbox.ready),
        ]
        with m.If(r_gearbox.valid & r_gearbox.ready):
            m.d.sync += r_partial.eq(~r_partial)

        with m.FSM() as fsm:
            with m.State("Level-0"):
                with m.If(self.r_data.ready):
                    with m.If(w_partial):
                        # Forward the one odd byte stuck in the write gearbox.
                        m.d.comb += [
                            self.r_data.payload.eq(w_queue.i.payload[0]),
                            self.r_data.valid.eq(1),
                            w_bypass.eq(1),
                        ]
                    with m.Else():
                        wiring.connect(m, wiring.flipped(self.w_data), wiring.flipped(self.r_data))
                with m.Else():
                    wiring.connect(m, wiring.flipped(self.w_data), w_gearbox)
                    with m.If(w_partial):
                        m.next = "Level-1"

            with m.State("Level-1"):
                wiring.connect(m, w_queue.o, r_queue.i)
                with m.If((w_queue.level == 0) & (r_queue.level == 0) & ~r_partial):
                    m.next = "Level-0"
                with m.Elif(w_queue.level > self._burst_size):
                    m.next = "Write-Burst-Command"

            with m.State("Level-2"):
                with m.If(ram_level == 0):
                    m.next = "Level-1"
                with m.Else():
                    with m.If(r_burst_ready & w_burst_ready):
                        # Prioritize the queue that has less slack in it.
                        with m.If(w_queue.depth - w_queue.level > r_queue.level):
                            m.next = "Read-Burst-Command"
                        with m.Else():
                            m.next = "Write-Burst-Command"
                    with m.Elif(r_burst_ready):
                        m.next = "Read-Burst-Command"
                    with m.Elif(w_burst_ready):
                        m.next = "Write-Burst-Command"

            with m.State("Write-Burst-Command"):
                m.d.comb += [
                    cmd_buf.i.p.type.eq(octoram.Command.WriteMemRow),
                    cmd_buf.i.p.addr.eq(ram_w_addr << 1),
                    cmd_buf.i.p.size.eq(self._burst_size),
                    cmd_buf.i.valid.eq(1),
                ]
                with m.If(cmd_buf.i.ready):
                    m.next = "Write-Burst-Data"

            with m.State("Read-Burst-Command"):
                m.d.comb += [
                    cmd_buf.i.p.type.eq(octoram.Command.ReadMemRow),
                    cmd_buf.i.p.addr.eq(ram_r_addr << 1),
                    cmd_buf.i.p.size.eq(self._burst_size),
                    cmd_buf.i.valid.eq(1),
                ]
                with m.If(cmd_buf.i.ready):
                    m.next = "Read-Burst-Data"

            with m.State("Write-Burst-Data"):
                m.d.comb += [
                    self.dram.w_data.p[0].data.eq(w_queue.o.payload[0]),
                    self.dram.w_data.p[1].data.eq(w_queue.o.payload[1]),
                    self.dram.w_data.valid.eq(w_queue.o.valid),
                    w_queue.o.ready.eq(self.dram.w_data.ready),
                ]
                with m.If(w_queue.o.valid & w_queue.o.ready):
                    m.d.sync += burst_len.eq(burst_len + 1)
                    with m.If(burst_len + 1 == self._burst_size):
                        m.d.sync += burst_len.eq(0)
                        m.d.sync += ram_level.eq(ram_level + self._burst_size)
                        m.d.sync += ram_w_addr.eq(ram_w_addr + self._burst_size)
                        with m.If(ram_w_addr + self._burst_size == self._spill_last):
                            m.d.sync += ram_w_addr.eq(self._spill_base)
                        m.next = "Level-2"

            with m.State("Read-Burst-Data"):
                m.d.comb += [
                    r_queue.i.payload[0].eq(self.dram.r_data.p[0].data),
                    r_queue.i.payload[1].eq(self.dram.r_data.p[1].data),
                    r_queue.i.valid.eq(self.dram.r_data.valid),
                    self.dram.r_data.ready.eq(r_queue.i.ready),
                ]
                with m.If(r_queue.i.valid & r_queue.i.ready):
                    m.d.sync += burst_len.eq(burst_len + 1)
                    with m.If(burst_len + 1 == self._burst_size):
                        m.d.sync += burst_len.eq(0)
                        m.d.sync += ram_level.eq(ram_level - self._burst_size)
                        m.d.sync += ram_r_addr.eq(ram_r_addr + self._burst_size)
                        with m.If(ram_r_addr + self._burst_size == self._spill_last):
                            m.d.sync += ram_r_addr.eq(self._spill_base)
                        m.next = "Level-2"

        with m.If(~fsm.ongoing("Level-0")):
            wiring.connect(m, wiring.flipped(self.w_data), w_gearbox)
            wiring.connect(m, r_gearbox, wiring.flipped(self.r_data))

        return m
