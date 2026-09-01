# Ref: APS51208N-OBRx DDR Octal SPI PSRAM Datasheet
# Accession: G00130

from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io
from amaranth.lib.wiring import In, Out, connect, flipped
from amaranth.sim import SimulatorContext

from .ports import PortGroup
from .stream import Queue, AsyncQueue, StreamBuffer, stream_get, stream_put
from .iostream import IOStreamer, HalfRateIOStreamer


__all__ = [
    "Operation", "Enframer", "Deframer", "Streamer",
    "Command", "Signature", "MemoryType", "Controller", "SimulationController",
    "InterfaceQueue",
]


class Operation(enum.Enum, shape=2):
    Idle   = 0
    Write  = 1
    Read   = 2


class Sample(data.Struct):
    valid: 1
    epoch: 1


class Enframer(wiring.Component):
    def __init__(self, ports, *, chip_count=None):
        super().__init__({
            "octets": In(stream.Signature(data.StructLayout({
                "oper": Operation,
                "chip": range(1 + (chip_count or len(ports.cs))),
                "data": data.ArrayLayout(8, 2),
                "mask": data.ArrayLayout(1, 2),
                "epoch": 1,
            }))),
            "frames": Out(IOStreamer.i_signature(ports, ratio=4, meta_layout=Sample)),
        })

    def elaborate(self, platform):
        m = Module()

        for n in range(4):
            m.d.comb += self.frames.p.port.cs.o[n].eq((1 << self.octets.p.chip)[1:])
        m.d.comb += self.frames.p.port.cs.oe.eq(1)

        with m.If(self.octets.p.chip != 0):
            m.d.comb += [
                self.frames.p.port.clk.o[0].eq(0),
                self.frames.p.port.clk.o[1].eq(1),
                self.frames.p.port.clk.o[2].eq(1),
                self.frames.p.port.clk.o[3].eq(0),
            ]
        m.d.comb += self.frames.p.port.clk.oe.eq(1)

        with m.If(self.octets.p.oper == Operation.Write):
            m.d.comb += [
                self.frames.p.port.dq.o[0].eq(self.octets.p.data[0]),
                self.frames.p.port.dq.o[1].eq(self.octets.p.data[0]),
                self.frames.p.port.dq.o[2].eq(self.octets.p.data[1]),
                self.frames.p.port.dq.o[3].eq(self.octets.p.data[1]),
                self.frames.p.port.dq.oe.eq(1),
                self.frames.p.port.dqs.o[0].eq(self.octets.p.mask[0]),
                self.frames.p.port.dqs.o[1].eq(self.octets.p.mask[0]),
                self.frames.p.port.dqs.o[2].eq(self.octets.p.mask[1]),
                self.frames.p.port.dqs.o[3].eq(self.octets.p.mask[1]),
                self.frames.p.port.dqs.oe.eq(1),
            ]

        m.d.comb += self.frames.p.meta.epoch.eq(self.octets.p.epoch)
        with m.If(self.octets.p.oper == Operation.Read):
            m.d.comb += self.frames.p.meta.valid.eq(1)

        m.d.comb += self.frames.valid.eq(self.octets.valid)
        m.d.comb += self.octets.ready.eq(self.frames.ready)

        return m


class Deframer(wiring.Component):
    def __init__(self, ports):
        super().__init__({
            "frames": In(IOStreamer.o_signature(ports, ratio=4, meta_layout=Sample)),
            "octets": Out(stream.Signature(data.StructLayout({
                "data": data.ArrayLayout(8, 2),
                "epoch": 1,
            }))),
        })

    def elaborate(self, platform):
        m = Module()

        dq0  = self.frames.p.port.dq.i[0]
        dq1  = self.frames.p.port.dq.i[2]
        dqs0 = self.frames.p.port.dqs.i[0]
        dqs1 = self.frames.p.port.dqs.i[2]

        dq1_prev = Signal.like(dq1)
        has_prev = Signal()
        with m.If(self.frames.valid):
            m.d.sync += dq1_prev.eq(dq1)
            m.d.sync += has_prev.eq(dqs1 & self.frames.p.meta.valid)
            with m.If(dqs0):
                m.d.comb += [
                    self.octets.p.data[0].eq(dq0),
                    self.octets.p.data[1].eq(dq1),
                    self.octets.valid.eq(self.frames.p.meta.valid),
                ]
            with m.If(dqs1 & has_prev):
                m.d.comb += [
                    self.octets.p.data[0].eq(dq1_prev),
                    self.octets.p.data[1].eq(dq0),
                    self.octets.valid.eq(self.frames.p.meta.valid),
                ]

        m.d.comb += self.octets.p.epoch.eq(self.frames.p.meta.epoch)
        m.d.comb += self.frames.ready.eq(self.octets.ready | ~self.octets.valid)

        return m


class Streamer(wiring.Component):
    def __init__(self, ports, *, offset=0, chip_count=None, half_rate):
        assert chip_count is None or len(ports.cs) <= chip_count
        assert (len(ports.cs) >= 1 and
                ports.cs.direction in (io.Direction.Output, io.Direction.Bidir))
        assert (len(ports.clk) == 1 and
                ports.clk.direction in (io.Direction.Output, io.Direction.Bidir))
        assert (len(ports.dq) == 8 and
                ports.dq.direction == io.Direction.Bidir)
        assert (len(ports.dqs) == 1 and
                ports.dqs.direction == io.Direction.Bidir)

        self._ports = PortGroup(
            cs =ports.cs .with_direction("o"),
            clk=ports.clk.with_direction("o"),
            dq =ports.dq .with_direction("io"),
            dqs=ports.dqs.with_direction("io"),
        )
        self._offset = offset
        self._chip_count = chip_count or len(ports.cs)

        self._half_rate = half_rate

        super().__init__({
            "i_stream": In(stream.Signature(data.StructLayout({
                "oper": Operation,
                "chip": range(1 + self._chip_count),
                "data": data.ArrayLayout(8, 2),
                "mask": data.ArrayLayout(1, 2),
                "epoch": 1,
            }))),
            "o_stream": Out(stream.Signature(data.StructLayout({
                "data": data.ArrayLayout(8, 2),
                "epoch": 1,
            }))),
        })

    def elaborate(self, platform):
        m = Module()

        if self._half_rate:
            io_streamer_cls = HalfRateIOStreamer
        else:
            io_streamer_cls = IOStreamer

        m.submodules.enframer = enframer = Enframer(ports=self._ports, chip_count=self._chip_count)
        connect(m, enframer=enframer.octets, controller=flipped(self.i_stream))

        m.submodules.io_streamer = io_streamer = io_streamer_cls(self._ports, ratio=4,
            offset=self._offset, meta_layout=Sample, init={
                "cs":  {"o": 0, "oe": 1}, # deselected
                "clk": {"o": 0, "oe": 1}, # idles low
            })
        connect(m, io_streamer=io_streamer.i, enframer=enframer.frames)

        m.submodules.o_buf = o_buf = StreamBuffer.shaped_like(io_streamer.o)
        connect(m, buffer=o_buf.i, io_streamer=io_streamer.o)

        m.submodules.deframer = deframer = Deframer(ports=self._ports)
        connect(m, deframer=deframer.frames, io_streamer=o_buf.o)

        connect(m, controller=flipped(self.o_stream), deframer=deframer.octets)

        return m


class MemoryType(enum.Enum, shape=2):
    OctalSPI = 0
    HyperRAM = 1


class Command(enum.Enum, shape=3):
    GlobalReset  = 0
    ReadMemWrap  = 1
    WriteMemWrap = 2
    ReadMemRow   = 3
    WriteMemRow  = 4
    ReadReg      = 5
    WriteReg     = 6


class Signature(wiring.Signature):
    """Native Octal DDR PSRAM memory bus signature."""

    def __init__(self):
        super().__init__({
            "commands": Out(stream.Signature(data.StructLayout({
                "type": Command,
                "addr": 32,
                "size": range(self.max_burst_size), # in beats; 0 means `self.max_burst_size`
            }))),
            "w_data": Out(stream.Signature(data.ArrayLayout(data.StructLayout({
                "data": 8,
                "mask": 1,
            }), 2))),
            "r_data": In(stream.Signature(data.ArrayLayout(data.StructLayout({
                "data": 8,
            }), 2))),
        })

    @property
    def max_burst_size(self):
        """Largest burst supported by the interface; equal to DRAM row size."""
        # AP Memory APSxxx08N-OBR
        # return 2048
        # Winbond W957D8MFYA
        return 1024


class Controller(wiring.Component):
    """Octal DDR PSRAM controller.

    The following devices have been tested with this controller:

    * AP Memory APSxxx08N-OBR devices (OctalSPI)
    * Winbond W957D8MFYA (HyperRAM)

    ECP5 Platform Support
    ---------------------

    On this platform, the controller requires a clock domain named ``edge`` connected to a PLL
    ``CLKOP`` or ``CLKOS`` output, and a clock domain named ``sync`` produced using a ``CLKDIVF``
    instance as follows:

    .. code::

        m.domains.sync = ClockDomain()
        m.submodules.sync_rst = cdc.ResetSynchronizer(ResetSignal("edge"), domain="sync")
        m.submodules.sync_div = Instance("CLKDIVF",
            i_RST=ResetSignal("edge"),
            i_CLKI=ClockSignal("edge"),
            o_CDIVX=ClockSignal("sync"),
        )

    There are only four ``CLKDIVF`` primitives per device. When using multiple memory controllers,
    these primitives should be shared if at all possible.

    The memory chip will be clocked at one half of the ``edge`` domain frequency, and transfer
    one ``w_data`` or ``r_data`` payload per clock.
    """

    # ECP5 has a peculiar clocking arrangement where there are two types of clock interconnect,
    # "primary clocks" (PCLK) and "edge clocks" (ECLK). Ignoring fabric inputs/outputs (which
    # generally have high delay and jitter):
    #  - Only edge clocks can be used to drive IO gearboxes like ODDRX2.
    #  - Primary clocks may be generated from edge clocks via CLKDIVF, and no other way.
    #  - Edge clocks can be driven by dedicated clock input pins, injected by PLLs,
    #    bridged via ECLKBRIDGE, or produced by DLLDEL primitives.
    #  - PLLs can inject edge clocks (via CLKOP/CLKOS) or primary clocks (via any output), this
    #    can only generate edge clocks on the same side of the device (east/west).
    #  - ECLKBRIDGECS can be used to bridge an edge clock from one side's PLL to another's IOs.
    #
    # Assuming we don't want to burn an entire PLL on the memory controller, by far the best
    # implementation strategy is to bring in an edge clock (only), which is generated outside
    # of the controller. The controller will then generate a logic clock with the appropriate
    # phase via CLKDIVF. Regardless of its frequency, commands and data are transferred via
    # async FIFOs; the memory clock frequency can now be changed by adjusting the memory
    # controller edge clock frequency, which is convenient.

    bus: In(Signature())

    mem_type: In(MemoryType)
    latency: In(range(32))

    def __init__(self, ports, *, offset: int = 0, half_rate: bool):
        self._ports     = ports
        self._offset    = offset
        self._half_rate = half_rate

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        max_burst_size = self.bus.signature.max_burst_size

        m.submodules.streamer = ram = Streamer(self._ports,
            offset=self._offset, half_rate=self._half_rate)

        m.submodules.ram_i_buffer = ram_i_buffer = StreamBuffer.shaped_like(ram.i_stream)
        wiring.connect(m, ram_i_buffer.o, ram.i_stream)

        # Command/address FSM and data read FSM have to synchronize for variable latency to work
        # because the former will continue issuing reads until stopped, and the latter will cause
        # the former to stop but cannot do anything about "in-flight" reads.
        # Note: the logic below assumes zero-length reads/writes are impossible (which they are
        # because of how `size` is encoded.)
        wr_epoch = Signal()
        rd_epoch = Signal()
        m.submodules.fifo = fifo = Queue(shape=range(max_burst_size + 1), depth=1)

        def perform(oper: Operation, *,
                    data: tuple[Value, Value] = (C(0), C(0)),
                    mask: tuple[Value, Value] = (C(0), C(0)),
                    valid: Value = C(1),
                    ready: Value | None = None):
            m.d.comb += [
                ram_i_buffer.i.p.oper.eq(oper),
                ram_i_buffer.i.p.chip.eq(1),
                ram_i_buffer.i.p.data[0].eq(data[0]),
                ram_i_buffer.i.p.mask[0].eq(mask[0]),
                ram_i_buffer.i.p.data[1].eq(data[1]),
                ram_i_buffer.i.p.mask[1].eq(mask[1]),
                ram_i_buffer.i.p.epoch.eq(wr_epoch),
                ram_i_buffer.i.valid.eq(valid),
            ]
            if ready is not None:
                m.d.comb += ready.eq(ram_i_buffer.i.ready)

        command = Signal(8)
        with m.Switch(self.bus.commands.p.type):
            with m.Case(Command.GlobalReset):   m.d.comb += command.eq(0xFF)
            with m.Case(Command.ReadMemWrap):   m.d.comb += command.eq(0x00)
            with m.Case(Command.WriteMemWrap):  m.d.comb += command.eq(0x80)
            with m.Case(Command.ReadMemRow):    m.d.comb += command.eq(0x20)
            with m.Case(Command.WriteMemRow):   m.d.comb += command.eq(0xA0)
            with m.Case(Command.ReadReg):       m.d.comb += command.eq(0x40)
            with m.Case(Command.WriteReg):      m.d.comb += command.eq(0xC0)

        address = self.bus.commands.p.addr

        cmd_addr = Signal(48)
        with m.Switch(self.mem_type):
            with m.Case(MemoryType.OctalSPI):
                # on APS*-OBx devices, the 1st negedge must have the same data as the posedge
                m.d.comb += cmd_addr[40:48].eq(command)
                m.d.comb += cmd_addr[32:40].eq(command)
                # on APS*-OBx devices, RA and CA have no gaps
                m.d.comb += cmd_addr[ 0:32].eq(address)

            with m.Case(MemoryType.HyperRAM):
                # on APS*-OBx and HyperRAM devices, the command encoding differs by flipping
                # the high bit, and the address encroaches on the 1st (command) byte; note that
                # there is no `GlobalReset` command
                m.d.comb += cmd_addr[40:48].eq(command ^ 0x80)
                # on HyperRAM devices, the address encoding contains a gap within the CA part;
                # the code below works with W957D8MFYA
                m.d.comb += cmd_addr[16:45].eq(address[ 4:32])
                m.d.comb += cmd_addr[ 0: 3].eq(address[ 1: 4])
                # on APS*-OCx, yet another encoding is used :(

        count = Signal(range(max_burst_size + 1))
        m.d.comb += fifo.i.payload.eq(count)

        with m.FSM(name="wr_fsm"):
            t_lat = Signal(len(self.latency) + 1) # latency timer
            t_rec = Signal(range(16))             # CE recovery timer

            with m.State("Command/Address[32:48]"):
                m.d.sync += count.eq(
                    Mux(self.bus.commands.p.size == 0, max_burst_size, self.bus.commands.p.size))
                m.d.sync += t_rec.eq(3)
                with m.If(self.bus.commands.valid):
                    with m.If((self.mem_type == MemoryType.HyperRAM) &
                              (self.bus.commands.p.type == Command.GlobalReset)):
                        m.next = "Deselect"
                    with m.Else():
                        perform(Operation.Write, data=(cmd_addr[40:48], cmd_addr[32:40]))
                        with m.If(ram_i_buffer.i.valid & ram_i_buffer.i.ready):
                            m.next = "Command/Address[16:32]"

            with m.State("Command/Address[16:32]"):
                # these bits are Don't Care for `Command.GlobalReset`
                perform(Operation.Write, data=(cmd_addr[24:32], cmd_addr[16:24]))
                with m.If(ram_i_buffer.i.valid & ram_i_buffer.i.ready):
                    m.next = "Command/Address[ 0:16]"

            with m.State("Command/Address[ 0:16]"):
                # these bits are Don't Care for `Command.GlobalReset`
                perform(Operation.Write, data=(cmd_addr[ 8:16], cmd_addr[ 0: 8]))
                with m.If(ram_i_buffer.i.valid & ram_i_buffer.i.ready):
                    # Latency Code table (HyperRAM):
                    # - Memory Read:    LC or LC×2 (exact) (variable latency mode)
                    #                         LC×2 (exact) (fixed latency mode)
                    # - Memory Write:   as above
                    # - Register Read:  as above
                    # - Register Write: 0
                    # Latency Code table (APS*-OBx):
                    # - Memory Read:    LC to LC×2 (range)
                    # - Memory Write:   LC
                    # - Register Read:  LC
                    # - Register Write: 0
                    # latency is counted from 2nd address byte, not 1st dummy byte, so we subtract
                    # 1 from the computed latency here
                    with m.Switch(self.bus.commands.p.type):
                        with m.Case(Command.GlobalReset):
                            # valids one more CLK pulse
                            m.next = "Reset Clock"
                        with m.Case(Command.WriteReg):
                            m.d.sync += count.eq(1)
                            m.next = "Write Data"
                        with m.Case(Command.ReadReg):
                            m.next = "Read Sync"
                        with m.Case(Command.WriteMemWrap, Command.WriteMemRow):
                            with m.Switch(self.mem_type):
                                with m.Case(MemoryType.OctalSPI):
                                    m.d.sync += t_lat.eq(self.latency - 1)
                                with m.Case(MemoryType.HyperRAM):
                                    m.d.sync += t_lat.eq((self.latency << 1) - 1)
                            m.next = "Write Latency"
                        with m.Case(Command.ReadMemWrap, Command.ReadMemRow):
                            m.next = "Read Sync"
                        with m.Default():
                            m.next = "Error"

            with m.State("Reset Clock"):
                perform(Operation.Idle)
                with m.If(ram_i_buffer.i.valid & ram_i_buffer.i.ready):
                    m.next = "Deselect"

            with m.State("Write Latency"):
                perform(Operation.Idle)
                with m.If(ram_i_buffer.i.valid & ram_i_buffer.i.ready):
                    m.d.sync += t_lat.eq(t_lat - 1)
                    with m.If(t_lat - 1 == 0):
                        m.next = "Write Data"

            with m.State("Write Data"):
                perform(Operation.Write,
                    data=(self.bus.w_data.p[0].data, self.bus.w_data.p[1].data),
                    mask=(self.bus.w_data.p[0].mask, self.bus.w_data.p[1].mask),
                    valid=self.bus.w_data.valid,
                    ready=self.bus.w_data.ready
                )
                with m.If(ram_i_buffer.i.valid & ram_i_buffer.i.ready):
                    m.d.sync += count.eq(count - 1)
                    with m.If(count - 1 == 0):
                        m.next = "Deselect"

            with m.State("Read Sync"):
                m.d.comb += fifo.i.valid.eq(1)
                with m.If(fifo.i.valid & fifo.i.ready):
                    m.next = "Read Data"

            with m.State("Read Data"):
                perform(Operation.Read)
                with m.If(ram_i_buffer.i.valid & ram_i_buffer.i.ready):
                    with m.If(wr_epoch != rd_epoch): # reader increments rd_epoch when done
                        m.d.sync += wr_epoch.eq(wr_epoch + 1)
                        m.next = "Deselect"

            with m.State("Deselect"):
                m.d.comb += ram_i_buffer.i.p.oper.eq(Operation.Idle)
                m.d.comb += ram_i_buffer.i.valid.eq(1)
                with m.If(ram_i_buffer.i.valid & ram_i_buffer.i.ready):
                    m.d.sync += t_rec.eq(t_rec - 1)
                    with m.If(t_rec == 0):
                        m.d.comb += self.bus.commands.ready.eq(1)
                        m.next = "Command/Address[32:48]"

            with m.State("Error"):
                pass

        m.d.comb += [
            self.bus.r_data.p[0].data.eq(ram.o_stream.p.data[0]),
            self.bus.r_data.p[1].data.eq(ram.o_stream.p.data[1]),
        ]

        remain = Signal.like(fifo.o.payload)
        with m.If(fifo.o.valid & (rd_epoch == ram.o_stream.p.epoch)):
            m.d.comb += self.bus.r_data.valid.eq(ram.o_stream.valid)
            m.d.comb += ram.o_stream.ready.eq(self.bus.r_data.ready)
            with m.If(ram.o_stream.valid & ram.o_stream.ready):
                with m.If(remain + 1 == fifo.o.payload):
                    m.d.comb += fifo.o.ready.eq(1)
                    m.d.sync += remain.eq(0)
                    m.d.sync += rd_epoch.eq(rd_epoch + 1)
                with m.Else():
                    m.d.sync += remain.eq(remain + 1)
        with m.Else():
            m.d.comb += ram.o_stream.ready.eq(1)

        return m


class SimulationController(wiring.Component):
    """Behavioral simulation of a memory controller.

    Only supports ``GlobalReset``, ``WriteMemRow``, and ``ReadMemRow`` commands.
    """

    bus: In(Signature())
    latency: In(range(32))

    def __init__(self, size):
        assert size % 2 == 0

        self.memory  = bytearray(size)

        super().__init__()

    def elaborate(self, platform):
        return Module()

    async def testbench(self, ctx: SimulatorContext):
        init_latency = 5
        ctx.set(self.latency, init_latency)

        while True:
            command = await stream_get(ctx, self.bus.commands, context=self)
            match command.type:
                case Command.GlobalReset:
                    ctx.set(self.latency, init_latency)

                case Command.WriteMemRow:
                    await ctx.tick(context=self).repeat(2 + ctx.get(self.latency))

                    assert command.addr % 2 == 0, f"{command.addr:#x} % 2 != 0"
                    for offset in range(0, command.size << 1, 2):
                        pointer = command.addr + offset
                        word = await stream_get(ctx, self.bus.w_data, context=self)
                        if not word[0].mask:
                            self.memory[pointer + 0] = word[0].data
                        if not word[1].mask:
                            self.memory[pointer + 1] = word[1].data

                case Command.ReadMemRow:
                    # Act as-if fixed latency mode was always used.
                    await ctx.tick(context=self).repeat(2 + ctx.get(self.latency) * 2)

                    assert command.addr % 2 == 0, f"{command.addr:#x} % 2 != 0"
                    for offset in range(0, command.size << 1, 2):
                        pointer = command.addr + offset
                        await stream_put(ctx, self.bus.r_data, [
                            {"data": self.memory[pointer + 0]},
                            {"data": self.memory[pointer + 1]},
                        ], context=self)


class InterfaceQueue(wiring.Component):
    """Clock domain crossing queue for commands and data.

    The data queue is split into two parts: the CDC FIFO and the buffer FIFO. This is done in order
    to improve timing; wide Gray counters quickly become the critical path, limiting the design
    with as little depth as as 2^8.

    The CDC FIFOs (three: commands, write data, and read data) always have depth 4, while
    the buffer FIFO has configurable depth. The read and write buffer FIFOs are both placed in
    ``o_domain``; assuming ``o_domain`` has a faster clock, this minimizes the time a DRAM
    transaction has to hold CE# low.
    """

    i: In(Signature())
    o: Out(Signature())

    def __init__(self, *, i_domain: str, o_domain: str,
            w_buffer_depth: int | None = None, r_buffer_depth: int | None = None):
        self.i_domain       = i_domain
        self.o_domain       = o_domain
        self.w_buffer_depth = w_buffer_depth
        self.r_buffer_depth = r_buffer_depth

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.cmd_cdc = cmd_cdc = AsyncQueue.shaped_like(self.i.commands,
            depth=4, i_domain=self.i_domain, o_domain=self.o_domain)
        wiring.connect(m, wiring.flipped(self.i.commands), cmd_cdc.i)
        wiring.connect(m, cmd_cdc.o, wiring.flipped(self.o.commands))

        m.submodules.wr_cdc = wr_cdc = AsyncQueue.shaped_like(self.i.w_data,
            depth=4, i_domain=self.i_domain, o_domain=self.o_domain)
        wiring.connect(m, wiring.flipped(self.i.w_data), wr_cdc.i)
        if self.w_buffer_depth is not None:
            m.submodules.wr_fifo = wr_fifo = DomainRenamer(self.o_domain)(
                Queue.shaped_like(self.i.w_data, depth=self.w_buffer_depth))
            wiring.connect(m, wr_cdc.o, wr_fifo.i)
            wiring.connect(m, wr_fifo.o, wiring.flipped(self.o.w_data))
        else:
            wiring.connect(m, wr_cdc.o, wiring.flipped(self.o.w_data))

        m.submodules.rd_cdc = rd_cdc = AsyncQueue.shaped_like(self.i.r_data,
            depth=4, i_domain=self.o_domain, o_domain=self.i_domain)
        if self.r_buffer_depth is not None:
            m.submodules.rd_fifo = rd_fifo = DomainRenamer(self.o_domain)(
                Queue.shaped_like(self.i.r_data, depth=self.r_buffer_depth))
            wiring.connect(m, wiring.flipped(self.o.r_data), rd_fifo.i)
            wiring.connect(m, rd_fifo.o, rd_cdc.i)
        else:
            wiring.connect(m, wiring.flipped(self.o.r_data), rd_cdc.i)
        wiring.connect(m, rd_cdc.o, wiring.flipped(self.i.r_data))

        return m
