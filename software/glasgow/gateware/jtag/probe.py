# Ref: IEEE Std 1149.1-2001
# Accession: G00018

from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io, cdc
from amaranth.lib.wiring import In, Out, connect, flipped

from glasgow.gateware.ports import PortGroup
from glasgow.gateware.iostream import IOStreamer


__all__ = ["Mode", "Controller"]


class Mode(enum.Enum, shape=unsigned(2)):
    ShiftTMS  = 0
    ShiftTDI  = 1
    ShiftTDIO = 2


class ShiftIn(enum.Enum, shape=unsigned(1)):
    More = 0
    Last = 1


class Enframer(wiring.Component):
    def __init__(self, *, width):
        super().__init__({
            "words": In(stream.Signature(data.StructLayout({
                "mode": Mode,
                "size": range(width + 1),
                "data": width,
                "last": 1,
            }))),
            "frames": Out(IOStreamer.o_stream_signature({
                "tck": ("o", 1),
                "tms": ("o", 1),
                "tdi": ("o", 1),
            }, meta_layout=ShiftIn)),
            "divisor": In(8),
        })

    def elaborate(self, platform):
        m = Module()

        timer  = Signal.like(self.divisor)
        phase  = Signal()
        offset = Signal.like(self.words.p.size)
        last   = (offset + 1 == self.words.p.size)

        m.d.comb += self.frames.p.port.tck.oe.eq(1)
        m.d.comb += self.frames.p.port.tck.o.eq(phase[-1])

        m.d.comb += self.frames.p.port.tms.oe.eq(1)
        with m.If(self.words.p.mode == Mode.ShiftTMS):
            m.d.comb += self.frames.p.port.tms.o.eq(self.words.p.data.bit_select(offset, 1))
        with m.Else():
            m.d.comb += self.frames.p.port.tms.o.eq(self.words.p.last & last)

        m.d.comb += self.frames.p.port.tdi.oe.eq(1)
        with m.If((self.words.p.mode == Mode.ShiftTDI) | (self.words.p.mode == Mode.ShiftTDIO)):
            m.d.comb += self.frames.p.port.tdi.o.eq(self.words.p.data.bit_select(offset, 1))
        with m.Else():
            # According to IEEE 1149.1, TDI idles at 1 (there is a pullup). In most cases this
            # should not matter but some devices are non-compliant and might misbehave if TDI
            # is left floating during operations where it should not matter.
            m.d.comb += self.frames.p.port.tdi.o.eq(1)

        m.d.comb += self.frames.p.meta.eq(Mux(last, ShiftIn.Last, ShiftIn.More))
        with m.If(self.words.p.mode == Mode.ShiftTDIO):
            m.d.comb += self.frames.p.i_en.eq(phase & (timer == 0))

        m.d.comb += self.frames.valid.eq(self.words.valid)
        with m.If(self.frames.valid & self.frames.ready):
            m.d.sync += timer.eq(timer + 1)
            with m.If(timer == self.divisor):
                m.d.sync += timer.eq(0)
                m.d.sync += phase.eq(~phase)
                with m.If(phase):
                    m.d.sync += offset.eq(offset + 1)
                    with m.If(last):
                        m.d.sync += offset.eq(0)
                        m.d.comb += self.words.ready.eq(1)

        return m


class Deframer(wiring.Component):
    def __init__(self, *, width):
        super().__init__({
            "frames": In(IOStreamer.i_stream_signature({
                "tdo": ("i", 1),
            }, meta_layout=ShiftIn)),
            "words": Out(stream.Signature(data.StructLayout({
                "size": range(width + 1),
                "data": width,
            }))),
        })

    def elaborate(self, platform):
        m = Module()

        offset = self.words.p.size

        with m.FSM():
            with m.State("More"):
                m.d.sync += self.words.p.data.bit_select(offset, 1).eq(self.frames.p.port.tdo.i)
                m.d.comb += self.frames.ready.eq(1)
                with m.If(self.frames.valid):
                    m.d.sync += offset.eq(offset + 1)
                    with m.If(self.frames.p.meta == ShiftIn.Last):
                        m.next = "Last"

            with m.State("Last"):
                m.d.comb += self.words.valid.eq(1)
                with m.If(self.words.ready):
                    m.d.sync += offset.eq(0)
                    m.next = "More"

        return m


class Controller(wiring.Component):
    def __init__(self, ports, *, width):
        self._ports = PortGroup(
            tck=ports.tck,
            tms=ports.tms,
            tdi=ports.tdi,
            tdo=ports.tdo,
        )
        self._width = width

        super().__init__({
            "i_words": In(stream.Signature(data.StructLayout({
                "mode": Mode,
                "size": range(width + 1),
                "data": width,
                "last": 1,
            }))),
            "o_words": Out(stream.Signature(data.StructLayout({
                "size": range(width + 1),
                "data": width,
            }))),
            "divisor": In(8),
        })

    def elaborate(self, platform):
        ioshape = {
            "tck": ("o", 1),
            "tms": ("o", 1),
            "tdi": ("o", 1),
            "tdo": ("i", 1),
        }

        m = Module()

        m.submodules.enframer = enframer = Enframer(width=self._width)
        connect(m, controller=flipped(self.i_words), enframer=enframer.words)
        m.d.comb += enframer.divisor.eq(self.divisor)

        m.submodules.io_streamer = io_streamer = IOStreamer(ioshape, self._ports, meta_layout=ShiftIn)
        connect(m, enframer=enframer.frames, io_streamer=io_streamer.o_stream)

        m.submodules.deframer = deframer = Deframer(width=self._width)
        connect(m, io_streamer=io_streamer.i_stream, deframer=deframer.frames)

        connect(m, deframer=deframer.words, controller=flipped(self.o_words))

        return m


class Command(enum.Enum, shape=3):
    Reset   = 0
    RunTest = 1

    # There are no commands that shift in dummy data into DR because:
    #  * This is almost always a mistake that will cost you a lot of time.
    #  * There are no efficiency gains in the sequencer from doing so.
    SetDR   = 2 # i_stream -> TDI -> DUT -> TDO -> (discard)
    GetDR   = 3 # i_stream -> TDI -> DUT -> TDO -> o_stream
    SetIR   = 4 # i_stream -> TDI -> DUT -> TDO -> (discard)
    GetIR   = 5 # i_stream -> TDI -> DUT -> TDO -> o_stream


class Sequencer(wiring.Component):
    """JTAG operation sequencer for debug interfaces.

    The sequencer assumes that the payload of any desired JTAG operation fits into a payload of
    predefined maximum size. This is well suited for e.g. MIPS EJTAG, ARM EICE/CoreSight, and
    similar interfaces.

    Note that the sequencer stops in Update-DR/IR after completing DR/IR commands. From there,
    it can move to Run-Test/Idle, or directly to Select-DR/IR-Scan without going through
    Run-Test/Idle. This is slightly unusual as Update-DR/IR is not a stable state, and unlike
    the approach of stopping in Pause-DR/IR, the new DR/IR value is loaded by the time the command
    is completed by the sequencer.
    """

    @classmethod
    def i_stream_payload(self, width):
        return data.StructLayout({
            "cmd":  Command,
            "size": range(width + 1),
            "data": width,
        })

    @classmethod
    def o_stream_payload(self, width):
        return data.StructLayout({
            "size": range(width + 1),
            "data": width,
        })

    def __init__(self, ports, *, width):
        self._ports = ports
        self._width = width

        super().__init__({
            "i_stream": In(stream.Signature(self.i_stream_payload(width))),
            "o_stream": Out(stream.Signature(self.o_stream_payload(width))),
            "divisor": In(8),
        })

    def elaborate(self, platform):
        m = Module()

        m.submodules.ctrl = ctrl = Controller(self._ports, width=self._width)
        m.d.comb += ctrl.divisor.eq(self.divisor)

        def shift_mode(tms, *, next, done=False):
            assert len(tms) <= self._width
            m.d.comb += [
                ctrl.i_words.p.mode.eq(Mode.ShiftTMS),
                ctrl.i_words.p.data.eq(sum(val << idx for idx, val in enumerate(tms))),
                ctrl.i_words.p.size.eq(len(tms)),
                ctrl.i_words.p.last.eq(1),
                ctrl.i_words.valid.eq(1)
            ]
            with m.If(ctrl.i_words.ready):
                m.d.comb += self.i_stream.ready.eq(done)
                m.next = next

        def shift_data(mode, *, next, done=False):
            m.d.comb += [
                ctrl.i_words.p.mode.eq(mode),
                ctrl.i_words.p.last.eq(1),
                ctrl.i_words.valid.eq(1)
            ]
            with m.If(ctrl.i_words.ready):
                m.d.comb += self.i_stream.ready.eq(done)
                m.next = next

        with m.FSM():
            with m.State("Next Command"):
                with m.If(self.i_stream.valid):
                    with m.Switch(self.i_stream.p.cmd):
                        with m.Case(Command.Reset):
                            m.next = "TAP Reset"
                        with m.Case(Command.RunTest):
                            m.next = "Run Test"
                        with m.Case(Command.SetDR, Command.GetDR):
                            m.next = "Enter Shift-DR"
                        with m.Case(Command.SetIR, Command.GetIR):
                            m.next = "Enter Shift-IR"

            with m.State("TAP Reset"):
                # (any) -> Run-Test/Idle
                shift_mode([1,1,1,1,1,0], next="Next Command", done=True)

            with m.State("Run Test"):
                # Run-Test/Idle -> Run-Test/Idle
                shift_mode([0], next="Next Command", done=True)

            with m.State("Enter Shift-DR"):
                # Run-Test/Idle | Update-DR/IR -> Shift-DR
                shift_mode([1,0,0], next="Shift DR/IR")

            with m.State("Enter Shift-IR"):
                # Run-Test/Idle | Update-DR/IR -> Shift-IR
                shift_mode([1,1,0,0], next="Shift DR/IR")

            with m.State("Shift DR/IR"):
                # Shift-DR/IR -> Exit1-DR/IR
                m.d.comb += [
                    ctrl.i_words.p.data.eq(self.i_stream.p.data),
                    ctrl.i_words.p.size.eq(self.i_stream.p.size),
                ]
                with m.Switch(self.i_stream.p.cmd):
                    with m.Case(Command.SetDR, Command.SetIR):
                        shift_data(Mode.ShiftTDI,  next="Leave Shift-DR/IR", done=True)
                    with m.Case(Command.GetDR, Command.GetIR):
                        shift_data(Mode.ShiftTDIO, next="Leave Shift-DR/IR", done=True)

            with m.State("Leave Shift-DR/IR"):
                # Exit1-DR/IR -> Update-DR/IR
                shift_mode([1], next="Next Command")

        wiring.connect(m, flipped(self.o_stream), ctrl.o_words)

        return m
