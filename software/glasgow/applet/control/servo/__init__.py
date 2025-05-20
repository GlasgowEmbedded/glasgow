import logging

from amaranth import *
from amaranth.lib import enum, io, wiring, stream
from amaranth.lib.wiring import In, Out

from glasgow.applet import GlasgowAppletV2


__all__ = ["ControlServoComponent", "ControlServoInterface"]


class ServoChannel(wiring.Component):
    en:  In(1)
    pos: In(range(2_000))
    out: Out(1)

    def __init__(self, period_us=20_000):
        self.period_us = period_us

        super().__init__()

    def elaborate(self, platform):
        # Cycles per microsecond. The position is specified in integer microseconds.
        resolution = int(platform.default_clk_frequency / 1_000_000)
        assert resolution * 1_000_000 == platform.default_clk_frequency, "Inexact µs duration"

        m = Module()

        # The modulation parameters are latched at the beginning of the cycle, avoiding glitches.
        en_r  = Signal.like(self.en)
        pos_r = Signal.like(self.pos)

        # This timer governs the overall modulation period. In a single period of operation (20 ms),
        # the first millisecond is always high (whenever the channel is enabled), the second is
        # an encoding of the position and the rest is always low.
        period_timer = Signal(range(self.period_us * resolution),
                              init=self.period_us * resolution - 1)
        with m.If(period_timer == period_timer.init):
            m.d.sync += period_timer.eq(0)
            m.d.sync += en_r.eq(self.en)
            m.d.sync += pos_r.eq(self.pos)
        with m.Else():
            m.d.sync += period_timer.eq(period_timer + 1)

        # This timer is controlled by the previous timer and governs pulse width within one
        # modulation period.
        pulse_en    = Signal()
        pulse_timer = Signal(range(resolution))
        pulse_count = Signal.like(self.pos)

        with m.If(period_timer == period_timer.init):
            m.d.sync += self.out.eq(en_r)
            m.d.sync += pulse_en.eq(1)

        with m.If(pulse_en):
            with m.If(pulse_timer == 0):
                m.d.sync += pulse_timer.eq(resolution - 1)
                m.d.sync += pulse_count.eq(pulse_count + 1)
                with m.If(pulse_count == pos_r):
                    m.d.sync += self.out.eq(0)
                    m.d.sync += pulse_en.eq(0)
            with m.Else():
                m.d.sync += pulse_timer.eq(pulse_timer - 1)
        with m.Else():
            m.d.sync += pulse_timer.eq(0)
            m.d.sync += pulse_count.eq(0)

        return m


class ControlServoComponent(wiring.Component):
    i_stream: In(stream.Signature(8))

    class Command(enum.Enum):
        Disable  = 0x00
        Enable   = 0x01
        SetValue = 0x02

    def __init__(self, ports):
        self.ports = ports

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.chan = chan = ServoChannel()
        m.submodules.out_buffer = out_buffer = io.Buffer("o", self.ports.out)
        m.d.comb += out_buffer.o.eq(chan.out)

        command   = Signal(self.Command)
        value_low = Signal.like(self.i_stream.payload)
        with m.FSM():
            with m.State("ReadCommand"):
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    m.d.sync += command.eq(self.i_stream.payload)
                    m.next = "HandleCommand"

            with m.State("HandleCommand"):
                with m.If(command == self.Command.Disable):
                    m.d.sync += chan.en.eq(0)
                    m.next = "ReadCommand"
                with m.If(command == self.Command.Enable):
                    m.d.sync += chan.en.eq(1)
                    m.next = "ReadCommand"
                with m.If(command == self.Command.SetValue):
                    m.d.comb += self.i_stream.ready.eq(1)
                    with m.If(self.i_stream.valid):
                        m.d.sync += value_low.eq(self.i_stream.payload)
                        m.next = "ReadPositionHigh"

            with m.State("ReadPositionHigh"):
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    m.d.sync += chan.pos.eq(Cat(value_low, self.i_stream.payload))
                    m.next = "ReadCommand"

        return m


class ControlServoInterface:
    def __init__(self, logger, assembly, *, out):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        ports = assembly.add_port_group(out=out)
        component = assembly.add_submodule(ControlServoComponent(ports))
        self._pipe = assembly.add_out_pipe(component.i_stream)

    def _log(self, message, *args):
        self._logger.log(self._level, "servo: " + message, *args)

    async def enable(self, is_enabled=True):
        """Enable or disable the servo.

        When disabled, no pulses are sent over the control line.
        """
        if is_enabled:
            self._log("enable")
            await self._pipe.send([ControlServoComponent.Command.Enable.value])
        else:
            self._log("disable")
            await self._pipe.send([ControlServoComponent.Command.Disable.value])
        await self._pipe.flush()

    async def disable(self):
        """Disable the servo.

        When disabled, no pulses are sent over the control line.
        """
        await self.enable(False)

    async def set_value(self, value: int):
        """Set servo control value.

        ``value`` is an integer number of microseconds in the range of 1000 to 2000 inclusive.
        Note that the interpretation of this value varies.
        - For a servo, 1500 corresponds to the neutral position.
        - For an unidirectional ESC, 1000 is 0 rpm and 2000 is maximum rpm.
        - For a bidirectional ESC, 1000 is maximum rpm backwards and 2000 is maximum rpm forwards.

        The servo is enabled after the value is set.
        """
        assert 1000 <= value <= 2000, "Position out of [1000, 2000] range"

        self._log(f"value={value}")
        await self._pipe.send([
            ControlServoComponent.Command.SetValue.value,
            *value.to_bytes(2, byteorder="little")
        ])
        await self._pipe.flush()

        await self.enable()


class ControlServoApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "control RC servomotors and ESCs"
    description = """
    Control RC/hobby servomotors using the common pulse width modulation protocol where a pulse
    of 1000 µs corresponds to a minimum position and a pulse of 2000 µs corresponds to a maximum
    position. The frequency of the updates is not strictly constrained by the protocol, and is
    fixed at 50 Hz in this applet.

    This protocol is also used in common brushless motor ESC (electronic speed control) modules.
    For unidirectional ESCs, a pulse of 1000 µs corresponds to 0 rpm and a pulse of 2000 µs to
    maximum rpm. For bidirectional ESCs, a pulse of 1000 us corresponds to maximum rpm backwards,
    and 2000 µs to maximum rpm forwards.
    """
    # The FPGA on revA/revB is too slow for a wide counter we are using.
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "out", required=True, default=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.servo_iface = ControlServoInterface(self.logger, self.assembly, out=args.out)

    @classmethod
    def tests(cls):
        from . import test
        return test.ControlServoAppletTestCase
