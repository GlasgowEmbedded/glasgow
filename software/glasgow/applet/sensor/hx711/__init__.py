# Ref: HX711 24-Bit Analog-to-Digital Converter (ADC) for Weigh Scales
# Accession: G00049

import logging
from typing import Literal

from amaranth import *
from amaranth.lib import enum, wiring, io, cdc, stream
from amaranth.lib.wiring import In, Out

from glasgow.abstract import AbstractAssembly, ClockDivisor, GlasgowPin
from glasgow.applet import GlasgowAppletV2, GlasgowAppletError
from glasgow.applet.control.clock import ClockDriveInterface
from glasgow.support.data_logger import DataLogger


__all__ = ["SensorHX711Interface", "SensorHX711Controller", "SensorHX711Component",
           "HX711Setting", "HX711Error"]


class HX711Error(GlasgowAppletError):
    pass


class HX711Setting(enum.IntEnum):
    """HX711Setting is an Enum that represents the three valid combinations of channel and gain."""

    A_128 = 25
    "A, 128 is the default (reset) value of channel and gain."
    B_32  = 26
    A_64  = 27

    @classmethod
    def from_channel_gain(
        cls, channel: Literal["A", "B"], gain: Literal[32, 64, 128]
    ) -> "HX711Setting":
        match (channel, gain):
            case ("B", 32):
                return cls.B_32
            case ("A", 64):
                return cls.A_64
            case ("A", 128):
                return cls.A_128
            case _:
                raise ValueError(
                    f"HX711 does not support a combination of channel {channel} and gain {gain}."
                )


class SensorHX711Controller(wiring.Component):
    sck_divisor: In(16)
    """Serial Clock (sck) clock divisor.

    sck frequency is freq(sync) / (2*(sck_divisor+1)).
    """

    settings: In(stream.Signature(HX711Setting))
    """A settings transfer instructs :py:`SensorHX711Controller` to perform a bus transaction.

    A bus transaction reads the current sample, and additionally, configures the channel and gain
    for the following sample. :py:`ready` will not be reasserted until both the bus transaction is
    complete and the acquired sample is transferred out from :py:`samples`.
    """

    samples: Out(stream.Signature(Shape(24, signed=True)))
    """Samples read from the HX711.

    Each transfer into the :py:`settings` stream causes one transfer out of
    the :py:`samples` stream.
    """

    def __init__(self, sck: io.PortLike, din: io.PortLike):
        self._sck = sck
        self._din = din
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        sck = Signal()
        din = Signal()
        m.submodules.sck_buffer = sck_buffer = io.Buffer("o", self._sck)
        m.submodules.din_buffer = din_buffer = io.Buffer("i", self._din)
        m.d.comb += sck_buffer.o.eq(sck)
        m.submodules += cdc.FFSynchronizer(din_buffer.i, din)

        sck_timer = Signal.like(self.sck_divisor)
        limit = Signal(HX711Setting)
        count = Signal(HX711Setting)
        sample_shreg = Signal.like(self.samples.payload)

        m.d.comb += self.samples.payload.eq(sample_shreg)
        with m.If(self.samples.ready):
            m.d.sync += self.samples.valid.eq(0)

        with m.FSM():
            with m.State("IDLE"):
                with m.If(self.settings.valid):
                    m.d.comb += self.settings.ready.eq(1)
                    m.d.sync += [
                        limit.eq(self.settings.payload),
                        count.eq(0),
                    ]
                    m.next = "WAIT"

            with m.State("WAIT"):
                with m.If(~din):
                    m.d.sync += sck_timer.eq(self.sck_divisor)
                    m.next = "SHIFT"

            with m.State("SHIFT"):
                with m.If(sck_timer != 0):
                    m.d.sync += sck_timer.eq(sck_timer-1)
                with m.Else():
                    m.d.sync += [
                        sck_timer.eq(self.sck_divisor),
                        sck.eq(~sck),
                    ]
                    with m.If(~sck):
                        # posedge
                        m.d.sync += count.eq(count+1)

                    with m.If(sck):
                        # negedge
                        with m.If(count <= 24):
                            m.d.sync += sample_shreg.eq(Cat(din, sample_shreg))

                        with m.If(count == 24):
                            m.d.sync += self.samples.valid.eq(1)

                        with m.Elif(count >= limit):
                            m.next = "FINISH-XFER"

            with m.State("FINISH-XFER"):
                with m.If(~self.samples.valid):
                    m.next = "IDLE"

        return m


class SensorHX711Component(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))

    sck_divisor: In(16)

    def __init__(self, ports):
        self._ports = ports
        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.hx711_controller = hx711_controller = SensorHX711Controller(
            sck=self._ports.sck, din=self._ports.din)

        m.d.comb += hx711_controller.sck_divisor.eq(self.sck_divisor)
        m.d.comb += [
            hx711_controller.settings.payload.eq(self.i_stream.payload),
            hx711_controller.settings.valid.eq(self.i_stream.valid),
            self.i_stream.ready.eq(hx711_controller.settings.ready)
        ]

        with m.FSM():
            word_count = Signal(range(3))
            sample = Signal.like(hx711_controller.samples.payload)

            with m.State("IDLE"):
                with m.If(hx711_controller.samples.valid):
                    m.d.comb += hx711_controller.samples.ready.eq(1)
                    m.d.sync += [
                        sample.eq(hx711_controller.samples.payload),
                        word_count.eq(2),
                    ]
                    m.next = "SEND"

            with m.State("SEND"):
                m.d.comb += [
                    self.o_stream.valid.eq(1),
                    self.o_stream.payload.eq(sample.word_select(word_count, 8))
                ]
                with m.If(self.o_stream.ready):
                    with m.If(word_count != 0):
                        m.d.sync += word_count.eq(word_count - 1)
                    with m.Else():
                        m.next = "IDLE"

        return m


class SensorHX711Interface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 sck: GlasgowPin, din: GlasgowPin):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        component = assembly.add_submodule(
            SensorHX711Component(assembly.add_port_group(sck=sck, din=din)))

        self._pipe = assembly.add_inout_pipe(component.o_stream, component.i_stream)

        self._sck_clock = assembly.add_clock_divisor(
            component.sck_divisor, ref_period=assembly.sys_clk_period*2, name="sck")

    def _log(self, message, *args):
        self._logger.log(self._level, "HX711: " + message, *args)

    @property
    def sck_clock(self) -> ClockDivisor:
        """Serial Clock (sck) clock divisor.

        The recommended frequency is 1MHz, otherwise the valid range is 20kHz to 5MHz.
        """
        return self._sck_clock

    async def sample(self, next_setting: HX711Setting) -> int:
        """Read the current sample, and initiate the conversion of the next sample.

        :py:`next_setting` determines the channel and gain of the next sample.

        Returns the sample as a signed 24 bit integer, which can be converted into the measured
        differential voltage with the formula: :math:`v = (sample/2^{23}) * (0.5AVDD/GAIN)`
        """
        await self._pipe.send(next_setting.to_bytes())
        await self._pipe.flush()
        sample_as_unsigned = int.from_bytes(await self._pipe.recv(3), byteorder="big")
        return sample_as_unsigned - ((sample_as_unsigned & 0x800000) << 1)


class SensorHX711Applet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "measure voltage with AVIA Semiconductor HX711"
    description = """
    Measure voltage with AVIA Semiconductor HX711 wheatstone bridge analog-to-digital converter.

    This applet can optionally provide a frequency source that can be connected to the XI pin.
    The provided frequency source is much more accurate than the internal oscillator of the HX711,
    and, depending on the state of the RATE pin, allows for a much wider sample rate range from
    approx. 1 Hz to approx. 144 Hz.
    """

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)

        access.add_pins_argument(parser, "sck", default=True, required=True)
        access.add_pins_argument(parser, "din", default=True, required=True)
        access.add_pins_argument(parser, "osc", required=False)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.hx711_iface = SensorHX711Interface(self.logger, self.assembly,
                                                    sck=args.sck, din=args.din)
            if args.osc is not None:
                self.osc_iface = ClockDriveInterface(self.logger, self.assembly,
                                                     clk=args.osc, name="osc")

    @classmethod
    def add_setup_arguments(cls, parser):
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=float,
            help="set reference oscillator frequency to FREQ MHz")

    async def setup(self, args):
        # The highest conversion rate supported by this sensor is about 144 Hz, and at 1 MHz,
        # the lowest retrieval rate is 37 kHz, so it'll always be fast enough unless the FIFO
        # gets full.
        await self.hx711_iface.sck_clock.set_frequency(1e6)

        if args.frequency is not None and args.osc is not None:
            await self.osc_iface.enable(args.frequency * 1e6)
        elif args.frequency is not None:
            raise HX711Error("osc pin not assigned, but --frequency argument is present.")
        elif args.osc is not None:
            raise HX711Error("osc pin assigned, but --frequency argument is missing.")

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument(
            "-c", "--channel", metavar="CHAN", type=str, choices=("A", "B"), default="A",
            help="measure channel CHAN")
        parser.add_argument(
            "-g", "--gain", metavar="GAIN", type=int, choices=(32, 64, 128), default=128,
            help="amplify GAIN times (64 or 128 for channel A, 32 for channel B)")

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_measure = p_operation.add_parser(
            "measure", help="read measured values")

        p_log = p_operation.add_parser(
            "log", help="log measured values")
        DataLogger.add_subparsers(p_log)

    async def run(self, args):
        setting = HX711Setting.from_channel_gain(args.channel, args.gain)
        # dummy sample to prime the settings
        await self.hx711_iface.sample(setting)

        if args.operation == "measure":
            sample = await self.hx711_iface.sample(setting)
            print(f"count : {sample:+d} LSB")

        if args.operation == "log":
            data_logger = await DataLogger(self.logger, args, field_names={"n": "count(LSB)"})
            while True:
                sample = await self.hx711_iface.sample(setting)
                await data_logger.report_data(fields={"n": sample})

    @classmethod
    def tests(cls):
        from . import test
        return test.SensorHX711AppletTestCase
