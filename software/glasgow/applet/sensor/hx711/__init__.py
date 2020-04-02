# Ref: HX711 24-Bit Analog-to-Digital Converter (ADC) for Weigh Scales
# Accession: G00049

import logging
import asyncio
from nmigen import *
from nmigen.lib.cdc import FFSynchronizer

from ... import *
from ....gateware.clockgen import *
from ....support.data_logger import DataLogger


class HX711Error(GlasgowAppletError):
    pass


class HX711Bus(Elaboratable):
    def __init__(self, pads):
        self.pads = pads
        self.clk = Signal()
        self.din = Signal()
        self.osc = Signal()

    def elaborate(self, platform):
        m = Module()
        m.d.comb += [
            self.pads.clk_t.oe.eq(1),
            self.pads.clk_t.o.eq(self.clk),
        ]
        m.submodules += [
            FFSynchronizer(self.pads.din_t.i, self.din),
        ]
        if hasattr(self.pads, "osc_t"):
            m.d.comb += [
                self.pads.osc_t.oe.eq(1),
                self.pads.osc_t.o.eq(self.osc),
            ]
        return m


class SensorHX711Subtarget(Elaboratable):
    def __init__(self, pads, in_fifo, out_fifo, clk_cyc, osc_cyc):
        self.pads     = pads
        self.in_fifo  = in_fifo
        self.out_fifo = out_fifo
        self.clk_cyc  = clk_cyc
        self.osc_cyc  = osc_cyc

    def elaborate(self, platform):
        m = Module()
        m.submodules.bus = bus = HX711Bus(self.pads)

        if self.osc_cyc is not None:
            m.submodules.clkgen = clkgen = ClockGen(self.osc_cyc)
            m.d.comb += bus.osc.eq(clkgen.clk)

        with m.FSM():
            timer = Signal(range(self.clk_cyc))
            count = Signal(range(28))
            limit = Signal(range(28))
            shreg = Signal(8)

            with m.State("IDLE"):
                with m.If(self.out_fifo.r_rdy):
                    m.d.comb += self.out_fifo.r_en.eq(1)
                    m.d.sync += [
                        limit.eq(self.out_fifo.r_data),
                        count.eq(0),
                    ]
                    m.next = "WAIT"

            with m.State("WAIT"):
                with m.If(~bus.din):
                    m.next = "SHIFT"

            with m.State("SHIFT"):
                with m.If(timer != 0):
                    m.d.sync += timer.eq(timer - 1)
                with m.Else():
                    m.d.sync += [
                        timer.eq(self.clk_cyc),
                        bus.clk.eq(~bus.clk),
                    ]
                    with m.If(~bus.clk): # posedge
                        m.d.sync += count.eq(count + 1)
                        with m.If((count != 0) & (count % 8 == 0)):
                            m.d.comb += [
                                self.in_fifo.w_data.eq(shreg),
                                self.in_fifo.w_en.eq(1),
                            ]
                    with m.If(bus.clk): # negedge
                        m.d.sync += shreg.eq(Cat(bus.din, shreg))
                        with m.If(count == limit):
                            m.next = "IDLE"

        return m


class HX711Interface:
    def __init__(self, interface, logger):
        self._lower  = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self._channel = "A"
        self._gain    = 128

    def _log(self, message, *args):
        self._logger.log(self._level, "HX711: " + message, *args)

    async def set_channel_gain(self, channel, gain):
        if (channel, gain) not in (("A", 128), ("B", 32), ("A", 64)):
            raise HX711Error("HX711 does not support a combination of channel {} and gain {}"
                             .format(channel, gain))
        self._channel = channel
        self._gain    = gain
        self._log("set channel=%s gain=%d", channel, gain)
        await self.sample() # dummy sample to prime the settings

    async def sample(self):
        channel_gain = (self._channel, self._gain)
        if channel_gain == ("A", 128):
            await self._lower.write([25])
        elif channel_gain == ("B", 32):
            await self._lower.write([26])
        elif channel_gain == ("A", 64):
            await self._lower.write([27])
        else:
            assert False
        sample_as_unsigned = int.from_bytes(await self._lower.read(3), byteorder="big")
        return sample_as_unsigned - ((sample_as_unsigned & 0x800000) << 1)


class SensorHX711Applet(GlasgowApplet, name="sensor-hx711"):
    logger = logging.getLogger(__name__)
    help = "measure voltage with AVIA Semiconductor HX711"
    description = """
    Measure voltage with AVIA Semiconductor HX711 wheatstone bridge analog-to-digital converter.

    This applet can optionally provide a frequency source that can be connected to the XI pin.
    The provided frequency source is much more accurate than the internal oscillator of the HX711,
    and, depending on the state of the RATE pin, allows for a much wider sample rate range from
    approx. 1 Hz to approx. 144 Hz.
    """

    __pins = ("clk", "din", "osc")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=float,
            help="set oscillator frequency to FREQ MHz")

        access.add_pin_argument(parser, "clk", default=True)
        access.add_pin_argument(parser, "din", default=True)
        access.add_pin_argument(parser, "osc", required=False)

    def build(self, target, args):
        if args.frequency is None:
            osc_cyc = None
        else:
            osc_cyc = self.derive_clock(clock_name="osc",
                input_hz=target.sys_clk_freq, output_hz=args.frequency * 1e6)

        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        iface.add_subtarget(SensorHX711Subtarget(
            pads=iface.get_pads(args, pins=self.__pins),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(),
            # The highest conversion rate supported by this sensor is about 144 Hz, and at 1 MHz,
            # the lowest retrieval rate is 37 kHz, so it'll always be fast enough unless the FIFO
            # gets full.
            clk_cyc=int(1e-6 * target.sys_clk_freq),
            osc_cyc=osc_cyc,
        ))

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        return HX711Interface(iface, self.logger)

    @classmethod
    def add_interact_arguments(cls, parser):
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

    async def interact(self, device, args, hx711):
        await hx711.set_channel_gain(args.channel, args.gain)

        if args.operation == "measure":
            sample = await hx711.sample()
            print("count : {:+d} LSB".format(sample))

        if args.operation == "log":
            data_logger = await DataLogger(self.logger, args, field_names={"n": "count(LSB)"})
            while True:
                sample = await hx711.sample()
                await data_logger.report_data(fields={"n": sample})

# -------------------------------------------------------------------------------------------------

class SensorHX711AppletTestCase(GlasgowAppletTestCase, applet=SensorHX711Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
