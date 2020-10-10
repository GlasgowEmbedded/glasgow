# Ref: Pervasive Displays EM027AS012 2.7” TFT EPD Panel Product Specifications
# Document Number: 1P033-00
# Accession: G00011
# Ref: Pervasive Displays E-paper Display COG Driver Interface Timing (G1)
# Document Number: 4P008-00
# Accession: G00012
# Ref: Pervasive Displays E-paper Display COG Driver Interface Timing (G2)
# Document Number: 4P015-00
# Accession: G00013

# G1 COG Startup
# --------------
#
# For G1 COG, the datasheet is not clear on the function of PWM pin. Without correct PWM signal
# being provided at start, the charge pump in the COG will not run correctly, resulting in
# a nonfunctional display and significant heat dissipation in COG. However, this does not seem
# to damage the COG over the time scale of minutes.
#
# G1 EPD Performance
# ------------------
#
# From some experiments with EPD, it appears that, unlike e.g. TFT LCD, EPDs require a huge amount
# of trial-and-error to eliminate artifacts. The algorithms in the datasheet are clearly the result
# of such trial-and-error, and should be followed precisely for best results. However, ignoring
# advice of the datasheet results in interesting discoveries. Here are some of my experiments:
#
#  * The EPD is sensitive to incorrect power-down sequence. If a nothing frame is not displayed,
#    e.g. after displaying a white frame, and the EPD is turned off, the display becomes uniformly
#    light gray.
#
#  * The EPD, apart from the active (pixel matrix) area, has lots of inactive areas, which is to
#    say, the entire rest of display save for a few regions. Such inactive areas will often change
#    color during operation in fascinating ways.
#
#    The BORDER pin (which is not implemented in this applet) is apparently added to control these
#    inactive areas. The datasheet is not entirely clear on its precise purpose. It does affect
#    aesthetics of the display, but it also has a cryptic note: "The reason for using BORDER is to
#    keep a sharp border and not have a charge on particles of FPL. Voltage too long on these will
#    produce a gray effect which is the optimal for long term operation".
#
#    So, is the "gray effect" good for long term operation (do they mean reliability)? No idea.
#    Given that it is recommended to use BORDER, I would say yes, but the note above implies no...
#
#  * The order of updating lines in the EPD is important. It should be strictly top to bottom, each
#    line in sequence. Updating the lines in upside down order leads to ghosting. Updating
#    the odd lines and then even lines leads to ghosting. It appears that the display has some
#    logic dependent on scan order, in spite of the scan bytes seemingly implying that the drivers
#    can be scanned in any desired order.
#
#  * The staging differs from that described in the datasheet in two aspects. First, there is no
#    Compensate stage, since the applet can't know what the old image was. Second, the datasheet
#    suggests White→Inverse→Normal staging. My experimentation shows that a different staging,
#    Black→White→Normal→Normal (with two Normal frames, not one Normal frame that's twice as
#    long!), produces significantly higher contrast, and an even longer staging, Black→White→
#    Black→White→Normal→Normal has higher contrast and reduced ghosting. I'm guessing these
#    would be more unpleasant on something like a ebook reader.

import math
import re
import itertools
import logging
import argparse
import asyncio
from bitarray import bitarray
from nmigen.compat import *

from ...interface.spi_controller import SPIControllerSubtarget, SPIControllerInterface
from ... import *


REG_CHAN_SEL    = 0x01
REG_OUTPUT_EN   = 0x02
REG_DRV_LATCH   = 0x03
REG_VGS_LEVEL   = 0x04
REG_CHARGE_PUMP = 0x05
REG_DC_DC_FREQ  = 0x06
REG_OSC_MODE    = 0x07
REG_ADC_MODE    = 0x08
REG_VCOM_LEVEL  = 0x09
REG_DATA        = 0x0A


class PDIDisplayError(GlasgowAppletError):
    pass


class PDIDisplayInterface:
    def __init__(self, interface, device, logger,
                 addr_cog_power, addr_cog_disch, addr_cog_reset):
        self.lower   = interface
        self.device  = device
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._addr_cog_power = addr_cog_power
        self._addr_cog_disch = addr_cog_disch
        self._addr_cog_reset = addr_cog_reset

    def _log(self, message, *args):
        self._logger.log(self._level, "PDI G%d: " + message, self._generation, *args)

    async def _set_power(self, value):
        self._log("cog-power=%d", value)
        await self.device.write_register(self._addr_cog_power, value)

    async def _set_disch(self, value):
        self._log("cog-disch=%d", value)
        await self.device.write_register(self._addr_cog_disch, value)

    async def _set_reset(self, value):
        self._log("cog-reset=%d", value)
        await self.device.write_register(self._addr_cog_reset, value)

    async def _identify(self):
        result = await self.lower.transfer([0x71, 0x00])
        cog_id = result[1]
        self._log("cog-id=%#04x", cog_id)
        return cog_id

    async def _write(self, index, value, delay_ms=0):
        if isinstance(value, int):
            value = bytes([value])
        else:
            value = bytes(value)
        if delay_ms > 0:
            self._log("[%02x] <= %s + %d ms", index, value.hex(), delay_ms)
        else:
            self._log("[%02x] <= %s", index, value.hex())
        await self.lower.delay_us(10)
        await self.lower.write([0x70, index])
        await self.lower.delay_us(10)
        await self.lower.write([0x72, *value])
        await self.lower.delay_ms(delay_ms)

    async def _read(self, index, length=1):
        await self.lower.delay_us(10)
        await self.lower.write([0x70, index])
        await self.lower.delay_us(10)
        result = await self.lower.transfer([0x73] + [0x00] * length)
        value  = result[1:]
        self._log("[%02x] => %s", index, value.hex())
        if length == 1:
            value = value[0]
        return value

    async def _flush(self):
        self._log("flush")
        await self.lower.synchronize()


class PDIG1DisplayInterface(PDIDisplayInterface):
    _generation = 1

    def __init__(self, interface, device, logger,
                 addr_cog_power, addr_cog_disch, addr_cog_reset, addr_cog_pwmen,
                 epd_size):
        super().__init__(interface, device, logger, addr_cog_power, addr_cog_disch, addr_cog_reset)

        self._addr_cog_pwmen = addr_cog_pwmen

        assert epd_size in ("1.44", "2", "2.7")
        self.epd_size = epd_size
        if self.epd_size == "1.44":
            self.width, self.height = 128, 96
        if self.epd_size == "2":
            self.width, self.height = 200, 96
        if self.epd_size == "2.7":
            self.width, self.height = 264, 176

    async def _set_pwmen(self, value):
        await self._flush()
        self._log("cog-pwmen=%d", value)
        await self.device.write_register(self._addr_cog_pwmen, value)

    async def power_on(self):
        self._log("power on cog")
        # Power on and reset COG
        await self._set_pwmen(1)
        await self._set_reset(1)
        await asyncio.sleep(0.005)
        await self._set_power(1)
        await asyncio.sleep(0.005)
        await self._set_reset(0)
        await asyncio.sleep(0.005)

        # Verify that COG has the right generation
        cog_id = await self._identify()
        if cog_id != 0x11:
            raise PDIDisplayError("COG is not PDI EPD G1 (id={:#04x})".format(cog_id))

        self._log("power on cog driver")
        # Channel Select
        if self.epd_size == "1.44":
            await self._write(REG_CHAN_SEL, bytes.fromhex("0000 0000 000F FF00"))
        if self.epd_size == "2":
            await self._write(REG_CHAN_SEL, bytes.fromhex("0000 0000 01FF E000"))
        if self.epd_size == "2.7":
            await self._write(REG_CHAN_SEL, bytes.fromhex("0000 007F FFFE 0000"))
        # DC/DC Frequency Setting
        await self._write(REG_DC_DC_FREQ, 0xFF)
        # High Power Mode Osc Setting
        await self._write(REG_OSC_MODE, 0x9D)
        # Disable ADC
        await self._write(REG_ADC_MODE, 0x00)
        # Set Vcom level
        await self._write(REG_VCOM_LEVEL, bytes.fromhex("D000"))
        # Gate and Source Voltage Level
        if self.epd_size in ("1.44", "2"):
            await self._write(REG_VGS_LEVEL, 0x03)
        if self.epd_size == "2.7":
            await self._write(REG_VGS_LEVEL, 0x00)
        # Driver latch on (cancel register noise)
        await self._write(REG_DRV_LATCH, 0x01)
        # Driver latch off
        await self._write(REG_DRV_LATCH, 0x00)
        # Start Positive Chargepump; VGH & VDH on
        await self._write(REG_CHARGE_PUMP, 0x01, delay_ms=30)
        # Start Negative Chargepump; VGL & VDL on
        await self._set_pwmen(0)
        await self._write(REG_CHARGE_PUMP, 0x03, delay_ms=30)
        # Start Vcom Chargepump; Vcom on
        await self._write(REG_CHARGE_PUMP, 0x0F, delay_ms=30)
        # Output enable to disable
        await self._write(REG_OUTPUT_EN, 0x24)
        # Flush command queue
        await self._flush()

    async def _display_line(self, data, scan, delay_ms=0, padding=0x00):
        # Set Chargepump voltage level reduce voltage shift
        if self.epd_size in ("1.44", "2"):
            await self._write(REG_VGS_LEVEL, 0x03)
        if self.epd_size == "2.7":
            await self._write(REG_VGS_LEVEL, 0x00)
        # Sending Data
        if self.epd_size == "1.44":
            prefix, suffix = [padding], []
        if self.epd_size in ("2", "2.7"):
            prefix, suffix = [], [padding]
        await self._write(REG_DATA,
            prefix + data[:len(data)//2] + scan + data[len(data)//2:] + suffix)
        # Turn on Output Enable
        await self._write(REG_OUTPUT_EN, 0x2F, delay_ms=delay_ms)

    async def display_frame(self, mode, time_ms=0, image=None):
        assert mode in ("black", "white", "nothing0", "nothing1")
        if mode == "black":
            fill = 0b11_11_11_11
        if mode == "white":
            fill = 0b10_10_10_10
        if mode == "nothing0":
            fill = 0b00_00_00_00
        if mode == "nothing1":
            fill = 0b01_01_01_01

        for y in range(self.height):
            data_even = [fill for _ in range(self.width // 8)]
            data_odd  = [fill for _ in range(self.width // 8)]
            if image is not None:
                offset = y * self.width
                even = image[offset + 1:offset + self.width:2]
                odd  = image[offset    :offset + self.width:2]
                for x, bit in enumerate(reversed(even)):
                    if bit: data_even[x // 4] ^= 0b01_00_00_00 >> ((x % 4) * 2)
                for x, bit in enumerate(odd):
                    if bit: data_odd [x // 4] ^= 0b01_00_00_00 >> ((x % 4) * 2)

            scan = [0x00 for _ in range(self.height // 4)]
            scan[y // 4] |= 0xc0 >> ((y % 4) * 2)

            await self._display_line(data_even + data_odd, scan,
                delay_ms=time_ms if y == self.height - 1 else 0)

    async def power_off(self):
        self._log("display nothing frame")
        await self.display_frame(mode="nothing1")

        self._log("display dummy line")
        data = [0x55 for _ in range(self.width  // 4)]
        scan = [0x00 for _ in range(self.height // 4)]
        if self.epd_size == "1.44":
            await self._display_line(data, scan, padding=0xAA, delay_ms=250)
        else:
            await self._display_line(data, scan, delay_ms=250)

        self._log("power off cog driver")
        # Latch reset turn on
        await self._write(REG_DRV_LATCH, 0x01)
        # Output enable off
        await self._write(REG_OUTPUT_EN, 0x05)
        # Power off chargepump Vcom
        await self._write(REG_CHARGE_PUMP, 0x0E)
        # Power off Negative Chargepump
        await self._write(REG_CHARGE_PUMP, 0x02)
        # Discharge
        await self._write(REG_VGS_LEVEL, 0x0C)
        # Turn off all chargepumps
        await self._write(REG_CHARGE_PUMP, 0x00)
        # Turn off osc
        await self._write(REG_OSC_MODE, 0x0D)
        # Discharge internal
        await self._write(REG_VGS_LEVEL, 0x50, delay_ms=40)
        # Discharge internal
        await self._write(REG_VGS_LEVEL, 0xA0, delay_ms=40)
        # Discharge internal
        await self._write(REG_VGS_LEVEL, 0x00, delay_ms=120)
        # Flush command queue
        await self._flush()

        self._log("power off cog")
        # Power off COG
        await self._set_power(0)
        await self._set_reset(1)
        await self._set_disch(1)
        await asyncio.sleep(0.150)
        await self._set_disch(0)


class DisplayPDIApplet(GlasgowApplet, name="display-pdi"):
    logger = logging.getLogger(__name__)
    help = "display images on Pervasive Display Inc EPD panels"
    description = """
    Display images on Pervasive Display Inc (PDI) electrophoretic (e-paper) displays.

    Supported and tested panels:
        * EM027AS012: G1 COG, 2.7" FPL, 264x176.

    Other G1 panels are supported but not tested. G2 panels are not supported, but would be easy
    to add support for.

    This applet requires additional logic for the display as described in PDI EPD Reference
    Circuit. In particular, the G1 COG will not start up without PWM.
    """

    __pins    = ("power", "disch", "reset", "cs", "sck", "cipo", "copi")
    __pins_g1 = ("pwm",)

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        for pin in cls.__pins + cls.__pins_g1:
            access.add_pin_argument(parser, pin, default=True)

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(SPIControllerSubtarget(
            pads=iface.get_pads(args, pins=self.__pins + self.__pins_g1),
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(auto_flush=False),
            period_cyc=math.ceil(target.sys_clk_freq / 5e6),
            delay_cyc=math.ceil(target.sys_clk_freq / 1e6),
            sck_idle=0,
            sck_edge="rising",
            cs_active=0,
        ))

        cog_power, self.__addr_cog_power = target.registers.add_rw(1)
        cog_disch, self.__addr_cog_disch = target.registers.add_rw(1)
        cog_reset, self.__addr_cog_reset = target.registers.add_rw(1, reset=1)
        target.comb += [
            # Make sure power and disch are never asserted together, as a safety interlock.
            iface.pads.power_t.oe.eq(1),
            iface.pads.power_t.o.eq(cog_power & ~cog_disch),
            iface.pads.disch_t.oe.eq(1),
            iface.pads.disch_t.o.eq(cog_disch & ~cog_power),
            iface.pads.reset_t.oe.eq(1),
            iface.pads.reset_t.o.eq(~cog_reset),
        ]

        if hasattr(iface.pads, "pwm_t"):
            pwm_half  = math.ceil(target.sys_clk_freq / 50e3)
            pwm_timer = Signal(max=pwm_half)
            pwm_phase = Signal()
            target.sync += [
                If(pwm_timer == 0,
                    pwm_phase.eq(~pwm_phase),
                    pwm_timer.eq(pwm_half),
                ).Else(
                    pwm_timer.eq(pwm_timer - 1)
                )
            ]

            cog_pwmen, self.__addr_cog_pwmen = target.registers.add_rw(1)
            target.comb += [
                iface.pads.pwm_t.oe.eq(1),
                iface.pads.pwm_t.o.eq(cog_pwmen & pwm_phase),
            ]

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)

        parser.add_argument(
            "-s", "--size", metavar="SIZE", choices=["1.44", "2", "2.7"],
            help="EPD size (diagonal inches; one of %(choices)s)")

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        spi_iface = SPIControllerInterface(iface, self.logger)
        pdi_iface = PDIG1DisplayInterface(spi_iface, device, self.logger,
            self.__addr_cog_power, self.__addr_cog_disch, self.__addr_cog_reset,
            self.__addr_cog_pwmen,
            epd_size=args.size)
        return pdi_iface

    @classmethod
    def add_interact_arguments(cls, parser):
        g_pattern = parser.add_mutually_exclusive_group(required=True)
        g_pattern.add_argument(
            "--checkerboard", default=False, action="store_true",
            help="display a checkerboard pattern")
        g_pattern.add_argument(
            "image_file", metavar="IMAGE-FILE", type=argparse.FileType("rb"), nargs="?",
            help="image file to display (format: pbm)")

    async def interact(self, device, args, pdi_iface):
        if args.checkerboard:
            image = bitarray(([0,0,1,1] * (pdi_iface.width // 2) +
                              [1,1,0,0] * (pdi_iface.width // 2))
                             * (pdi_iface.height // 4))

        if args.image_file:
            image_header = args.image_file.readline()
            if image_header != b"P4\n":
                raise GlasgowAppletError("image file is not a raw PBM file")
            image_comment = args.image_file.readline()
            image_size = re.match(rb"^(\d+) (\d+)$", args.image_file.readline())
            if not image_size:
                raise GlasgowAppletError("image file is corrupt")
            image_width, image_height = int(image_size[1]), int(image_size[2])
            if image_width != pdi_iface.width or image_height != pdi_iface.height:
                raise GlasgowAppletError("image size does not match display size")
            image = bitarray()
            image.frombytes(args.image_file.read())

        stage_ms = 300

        await pdi_iface.power_on()
        for _ in range(2):
            await pdi_iface.display_frame(mode="black", time_ms=stage_ms)
            await pdi_iface.display_frame(mode="white", time_ms=stage_ms)
        await pdi_iface.display_frame(mode="white", time_ms=stage_ms, image=image)
        await pdi_iface.display_frame(mode="white", time_ms=stage_ms, image=image)
        await pdi_iface.power_off()

# -------------------------------------------------------------------------------------------------

class DisplayPDIAppletTestCase(GlasgowAppletTestCase, applet=DisplayPDIApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
