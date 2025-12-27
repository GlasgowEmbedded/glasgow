# Ref: HX711 24-Bit Analog-to-Digital Converter (ADC) for Weigh Scales
# Accession: G00049

import logging
from typing import Literal

from amaranth import *
from amaranth.lib import wiring, io, cdc, stream
from amaranth.lib.wiring import In, Out

from glasgow.abstract import AbstractAssembly, ClockDivisor, GlasgowPin
from glasgow.applet import GlasgowAppletV2, GlasgowAppletError
from glasgow.support.data_logger import DataLogger


__all__ = ["SensorHX711Component", "SensorHX711Interface"]


class HX711Error(GlasgowAppletError):
    pass


class HX711Bus(Elaboratable):
    def __init__(self, ports):
        self.ports = ports
        self.sck = Signal()
        self.din = Signal()
        self.osc = Signal()

    def elaborate(self, platform):
        m = Module()
        m.submodules.sck_buffer = sck_buffer = io.Buffer("o", self.ports.sck)
        m.d.comb += sck_buffer.o.eq(self.sck)
        m.submodules.din_buffer = din_buffer = io.Buffer("i", self.ports.din)
        m.submodules += cdc.FFSynchronizer(din_buffer.i, self.din)
        if self.ports.osc is not None:
            m.submodules.osc_buffer = osc_buffer = io.Buffer("o", self.ports.osc)
            m.d.comb += osc_buffer.o.eq(self.osc)
        return m


class SensorHX711Component(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))

    sck_divisor: In(16)
    osc_divisor: In(16)

    def __init__(self, ports):
        self._ports = ports
        super().__init__()

    def elaborate(self, platform):
        m = Module()
        m.submodules.bus = bus = HX711Bus(self._ports)

        if self._ports.osc is not None:
            osc_timer = Signal.like(self.osc_divisor)
            with m.If(osc_timer == 0):
                m.d.sync += [
                    osc_timer.eq(self.osc_divisor),
                    bus.osc.eq(~bus.osc)
                ]
            with m.Else():
                m.d.sync += osc_timer.eq(osc_timer-1)

        with m.FSM():
            sck_timer = Signal.like(self.sck_divisor)
            count = Signal(range(28))
            limit = Signal(range(28))
            shreg = Signal(8)

            with m.State("IDLE"):
                with m.If(self.i_stream.valid):
                    m.d.comb += self.i_stream.ready.eq(1)
                    m.d.sync += [
                        limit.eq(self.i_stream.payload),
                        count.eq(0),
                    ]
                    m.next = "WAIT"

            with m.State("WAIT"):
                with m.If(~bus.din):
                    m.next = "SHIFT"

            with m.State("SHIFT"):
                with m.If(sck_timer != 0):
                    m.d.sync += sck_timer.eq(sck_timer - 1)
                with m.Else():
                    m.d.sync += [
                        sck_timer.eq(self.sck_divisor),
                        bus.sck.eq(~bus.sck),
                    ]
                    with m.If(~bus.sck): # posedge
                        m.d.sync += count.eq(count + 1)
                        with m.If((count != 0) & (count % 8 == 0)):
                            m.d.comb += [
                                self.o_stream.payload.eq(shreg),
                                self.o_stream.valid.eq(1),
                            ]
                    with m.If(bus.sck): # negedge
                        m.d.sync += shreg.eq(Cat(bus.din, shreg))
                        with m.If(count == limit):
                            m.next = "IDLE"

        return m


class SensorHX711Interface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 sck: GlasgowPin, din: GlasgowPin, osc: GlasgowPin | None = None):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        # HX711 comes out of reset with this channel/gain
        self._channel = "A"
        self._gain    = 128

        component = assembly.add_submodule(
            SensorHX711Component(assembly.add_port_group(sck=sck, din=din, osc=osc)))

        self._pipe = assembly.add_inout_pipe(component.o_stream, component.i_stream)

        self._sck_clock = assembly.add_clock_divisor(
            component.sck_divisor, ref_period=assembly.sys_clk_period*2, name="sck")

        if osc is not None:
            self._osc_clock = assembly.add_clock_divisor(
                component.osc_divisor, ref_period=assembly.sys_clk_period*2, name="osc")
        else:
            self._osc_clock = None

    def _log(self, message, *args):
        self._logger.log(self._level, "HX711: " + message, *args)

    @property
    def sck_clock(self) -> ClockDivisor:
        """Serial Clock (sck) clock divisor.

        The recommended frequency is 1MHz, otherwise the valid range is 20kHz to 5MHz.
        """
        return self._sck_clock

    @property
    def osc_clock(self) -> ClockDivisor:
        """Reference frequency clock divisor.

        The sample rate is either freq/1,105,920 or freq/138,240, depending on the HX711 rate pin.

        Raises
        ------
        HX711Error
            If the optional reference clock is not used and :py:`osc_clock` is accessed.
        """
        if self._osc_clock is not None:
            return self._osc_clock
        else:
            raise HX711Error(f"There is no pin assigned for osc.")

    async def set_channel_gain(self, channel: Literal["A", "B"], gain: Literal[32, 64, 128]):
        """Select the :py:`channel` to be sampled, and the :py:`gain` for it.

        The valid combinations of :py:`channel` and :py:`gain` are:

            "A", 128; "B", 32; "A", 64

        :meth:`set_channel_gain` also performs a dummy sample to prime the
        settings for following calls to :meth:`sample`

        Raises
        ------
        HX711Error
            If an invalid combination of channel and gain is used.
        """
        if (channel, gain) not in (("A", 128), ("B", 32), ("A", 64)):
            raise HX711Error(
                f"HX711 does not support a combination of channel {channel} and gain {gain}")
        self._channel = channel
        self._gain    = gain
        self._log("set channel=%s gain=%d", channel, gain)
        await self.sample() # dummy sample to prime the settings

    async def sample(self) -> int:
        """Read the current sample, and initiate the conversion of the next sample.

        The full scale range is 2.56V / :py:`gain`.

        Returns the sample as a signed 24 bit integer.
        """
        match (self._channel, self._gain):
            case ("A", 128):
                msg = [25]
            case ("B", 32):
                msg = [26]
            case ("A", 64):
                msg = [27]
            case _:
                assert False
        await self._pipe.send(msg)
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

    The pinout of the HX711 is as follows:

    ::

           SOP-16
        VSUP @ * DVDD
        BASE * * RATE
        AVDD * * XI
         VFB * * XO
        AGND * * DOUT
         VBG * * PD_SCK
        INNA * * INPB
        INPA * * INNB
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
                                                    sck=args.sck, din=args.din, osc=args.osc)

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
        if args.frequency is not None:
            await self.hx711_iface.osc_clock.set_frequency(args.frequency * 1e6)
        elif args.osc is not None:
            raise HX711Error("osc pin assigned, but --frequency argument is missing.")

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        return SensorHX711Interface(iface, self.logger)

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
        await self.hx711_iface.set_channel_gain(args.channel, args.gain)

        if args.operation == "measure":
            sample = await self.hx711_iface.sample()
            print(f"count : {sample:+d} LSB")

        if args.operation == "log":
            data_logger = await DataLogger(self.logger, args, field_names={"n": "count(LSB)"})
            while True:
                sample = await self.hx711_iface.sample()
                await data_logger.report_data(fields={"n": sample})

    @classmethod
    def tests(cls):
        from . import test
        return test.SensorHX711AppletTestCase
