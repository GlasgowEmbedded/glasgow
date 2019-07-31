# Ref: IBM PS/2 Hardware Technical Reference ­- Keyboards (101- and 102-Key)
# Accession: G00037
# Ref: UTC UT84520 PS/2 SCROLLING MOUSE CONTROLLER
# Accession: G00036

# The PS/2 mouse is kind of weird because while the IBM PS/2 Technical Reference does specify that
# it *exists* (along with touchpads and trackballs), it does not specify its protocol at all,
# leaving it at just "auxiliary device commands". It is not completely clear where does the common
# PS/2 mouse command set originate from, but it is likely one of these early devices. As a result,
# the commands here are referenced from a datasheet from an arbitrarily chosen mouse controller.
#
# It should be noted that many of the PS/2 mouse commands (FF, FE, F6, F5, F4, F2) are essentially
# identical to the respective keyboard commands. The command F3 has different semantics
# (the interpretation of the data byte is changed), but is similar in spirit: F3 in mice changes
# sample rate, whereas F3 in keyboards changes typematic repeat rate and delay. The command EE
# has different semantics (the data is echoed until the command EC is received), but is similar in
# spirit: EE in mice returns the input bytes until EC is received, whereas EE in keyboards returns
# the input byte once.
#
# See also the note on the i8042 controller in the ps2-host applet.

from collections import namedtuple
import logging
import asyncio

from ... import *
from ...interface.ps2_host import PS2HostApplet


CMD_RESET               = 0xff
CMD_RESEND              = 0xfe
CMD_SET_DEFAULTS        = 0xf6
CMD_DISABLE_REPORTING   = 0xf5 # default
CMD_ENABLE_REPORTING    = 0xf4
CMD_SET_SAMPLE_RATE     = 0xf3
ARG_SAMPLE_RATES        = (10, 20, 40, 60, 80, 100, 200)
CMD_GET_DEVICE_ID       = 0xf2
CMD_SET_REMOTE_MODE     = 0xf0
CMD_SET_WRAP_MODE       = 0xee
CMD_RESET_WRAP_MODE     = 0xec
CMD_READ_DATA           = 0xeb
CMD_SET_STREAM_MODE     = 0xea # default
CMD_STATUS_REQUEST      = 0xe9
CMD_SET_RESOLUTION      = 0xe8 # default: 4
ARG_RESOLUTIONS         = (1, 2, 4, 8)
CMD_ENABLE_AUTOSPEED    = 0xe7
CMD_DISABLE_AUTOSPEED   = 0xe6 # default

ID_MOUSE_STANDARD       = 0x00
ID_MOUSE_WHEEL          = 0x03
SEQ_ENABLE_WHEEL        = (200, 100, 80) # for CMD_SET_RESOLUTION
ID_MOUSE_5_BUTTON       = 0x04
SEQ_ENABLE_5_BUTTON     = (200, 200, 80) # for CMD_SET_RESOLUTION

# 1st byte
REP_LEFT_BUTTON         =         0b001
REP_RIGHT_BUTTON        =         0b010
REP_MIDDLE_BUTTON       =         0b100
REP_X_SIGN              =    0b01_0_000
REP_Y_SIGN              =    0b10_0_000
REP_X_OVERFLOW          = 0b01_00_0_000
REP_Y_OVERFLOW          = 0b10_00_0_000
# 3rd byte
REP_4TH_BUTTON          = 0b01_0000
REP_5TH_BUTTON          = 0b10_0000


SensorMousePS2Report = namedtuple("SensorMousePS2Report",
    ("left", "right", "middle", "button_4", "button_5",
     "offset_x", "offset_y", "offset_z", "overflow_x", "overflow_y"))


class SensorMousePS2Error(GlasgowAppletError):
    pass


class SensorMousePS2Interface:
    def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, "PS/2 Mouse: " + message, *args)

    async def reset(self):
        bat_result, = await self.lower.send_command(CMD_RESET, ret=1)
        self._log("reset bat-result=%02x", bat_result)
        if bat_result == 0xaa:
            pass # passed
        elif bat_result == 0xfc:
            raise SensorMousePS2Error("Basic Assurance Test failed")
        else:
            raise SensorMousePS2Error("invalid Basic Assurance Test response {:#04x}"
                                      .format(bat_result))

    async def identify(self):
        ident, = await self.lower.send_command(CMD_GET_DEVICE_ID, ret=1)
        self._log("ident=%02x", ident)
        return ident

    async def probe(self):
        ident = await self.identify()
        if ident == ID_MOUSE_STANDARD:
            for rate in SEQ_ENABLE_WHEEL:
                await self.set_sample_rate(rate)
            ident = await self.identify()
        if ident == ID_MOUSE_WHEEL:
            for rate in SEQ_ENABLE_5_BUTTON:
                await self.set_sample_rate(rate)
            ident = await self.identify()
        return ident

    async def set_reporting(self, enabled=True):
        self._log("reporting=%s", "on" if enabled else "off")
        if enabled:
            await self.lower.send_command(CMD_ENABLE_REPORTING)
        else:
            await self.lower.send_command(CMD_DISABLE_REPORTING)

    async def set_sample_rate(self, rate):
        assert rate in ARG_SAMPLE_RATES
        self._log("sample-rate=%d [report/s]", rate)
        await self.lower.send_command(CMD_SET_SAMPLE_RATE)
        await self.lower.send_command(rate)

    async def set_remote_mode(self):
        self._log("mode=remote")
        await self.lower.send_command(CMD_SET_REMOTE_MODE)

    async def set_stream_mode(self):
        self._log("mode=stream")
        await self.lower.send_command(CMD_SET_STREAM_MODE)

    async def set_resolution(self, resolution):
        assert resolution in ARG_RESOLUTIONS
        self._log("resolution=%d [count/mm]", resolution)
        await self.lower.send_command(CMD_SET_RESOLUTION)
        await self.lower.send_command(ARG_RESOLUTIONS.index(resolution))

    async def set_autospeed(self, enabled):
        self._log("autospeed=%s", "on" if enabled else "off")
        if enabled:
            await self.lower.send_command(CMD_ENABLE_AUTOSPEED)
        else:
            await self.lower.send_command(CMD_DISABLE_AUTOSPEED)

    def _size_report(self, ident):
        if ident == ID_MOUSE_STANDARD:
            return 3
        elif ident == ID_MOUSE_WHEEL:
            return 4
        elif ident == ID_MOUSE_5_BUTTON:
            return 4
        else:
            assert False

    def _decode_report(self, ident, packet):
        button_4 = button_5 = False
        if ident == ID_MOUSE_STANDARD:
            control, data_x, data_y = packet
            offset_z = 0
        elif ident == ID_MOUSE_WHEEL:
            control, data_x, data_y, data_z = packet
            offset_z = data_z | (-((data_z & 0x80) != 0) << 7)
        elif ident == ID_MOUSE_5_BUTTON:
            control, data_x, data_y, data_z = packet
            offset_z = data_z | (-((data_z & 0x08) != 0) << 3)
            button_4 = (data_z & REP_4TH_BUTTON) != 0
            button_5 = (data_z & REP_5TH_BUTTON) != 0
        else:
            assert False
        offset_x = data_x | (-((control & REP_X_SIGN) != 0) << 8)
        offset_y = data_y | (-((control & REP_Y_SIGN) != 0) << 8)
        report = SensorMousePS2Report(
            left=bool(control & REP_LEFT_BUTTON),
            right=bool(control & REP_RIGHT_BUTTON),
            middle=bool(control & REP_MIDDLE_BUTTON),
            button_4=button_4,
            button_5=button_5,
            offset_x=offset_x,
            offset_y=offset_y,
            offset_z=offset_z,
            overflow_x=bool(control & REP_X_OVERFLOW),
            overflow_y=bool(control & REP_Y_OVERFLOW),
        )
        self._log("report l=%d m=%d r=%d 4=%d 5=%d x=%+d y=%+d z=%+d ox=%d oy=%d",
                  report.left, report.middle, report.right, report.button_4, report.button_5,
                  report.offset_x, report.offset_y, report.offset_z,
                  report.overflow_x, report.overflow_y)
        return report

    async def request_report(self, ident=None):
        if ident is None:
            ident = await self.identify()
        packet = await self.lower.send_command(CMD_READ_DATA, ret=self._size_report(ident))
        return self._decode_report(ident, packet)

    async def request_report(self, ident=None):
        if ident is None:
            ident = await self.identify()
        size = self._size_report(ident)
        packet = await self.lower.send_command(CMD_READ_DATA, ret=size)
        return self._decode_report(ident, packet)

    async def stream_reports(self, ident=None):
        if ident is None:
            ident = await self.identify()
        await self.set_stream_mode()
        await self.set_reporting(True)
        size = self._size_report(ident)
        more = True
        while more or more is None:
            packet = await self.lower.recv_packet(size)
            more = (yield self._decode_report(ident, packet))


class SensorMousePS2Applet(PS2HostApplet, name="sensor-mouse-ps2"):
    logger = logging.getLogger(__name__)
    help = "receive axis and button information from PS/2 mice"
    description = """
    Identify PS/2 mice, and receive axis position and button press/release updates. The updates
    may be logged or forwarded to the desktop on Linux.

    This applet has additional Python dependencies:
        * uinput (optional, required for Linux desktop forwarding)
    """

    async def run(self, device, args):
        ps2_iface = await self.run_lower(SensorMousePS2Applet, device, args)
        mouse_iface = SensorMousePS2Interface(ps2_iface, self.logger)
        return mouse_iface

    @classmethod
    def add_interact_arguments(cls, parser):
        parser.add_argument(
            "--no-reset", dest="reset", default=True, action="store_false",
            help="do not send the reset command before initialization (does not affect reset pin)")
        parser.add_argument(
            "--no-probe", dest="probe", default=True, action="store_false",
            help="do not probe magic sequences to detect improved protocols")

        parser.add_argument(
            "-r", "--resolution", metavar="RES", type=int, choices=ARG_RESOLUTIONS,
            help="set resolution to RES counts/mm (one of: %(choices)s)")
        parser.add_argument(
            "-s", "--sample-rate", metavar="RATE", type=int, choices=ARG_SAMPLE_RATES,
            help="set sample rate to RATE reports/s (one of: %(choices)s)")
        parser.add_argument(
            "-a", "--acceleration", dest="acceleration", default=None, action="store_true",
            help="enable acceleration (also known as autospeed and scaling)")
        parser.add_argument(
            "-A", "--no-acceleration", dest="acceleration", default=None, action="store_false",
            help="disable acceleration")

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_stream_log = p_operation.add_parser("stream-log",
            help="stream events and log them")

        p_stream_uinput = p_operation.add_parser("stream-uinput",
            help="stream events and forward them to desktop via uinput (Linux only)")
        p_stream_uinput.add_argument(
            "-x", "--invert-x", default=1, action="store_const", const=-1,
            help="invert X axis offsets")
        p_stream_uinput.add_argument(
            "-y", "--invert-y", default=1, action="store_const", const=-1,
            help="invert Y axis offsets")

    async def interact(self, device, args, mouse_iface):
        async def initialize():
            if args.reset:
                await mouse_iface.reset()
            if args.probe:
                return await mouse_iface.probe()
            else:
                return await mouse_iface.identify()

        try:
            ident = await asyncio.wait_for(initialize(), timeout=1)
        except asyncio.TimeoutError:
            raise SensorMousePS2Error("initialization timeout; connection problem?")

        if ident == ID_MOUSE_STANDARD:
            self.logger.info("found standard mouse")
        elif ident == ID_MOUSE_WHEEL:
            self.logger.info("found scrolling mouse")
        elif ident == ID_MOUSE_5_BUTTON:
            self.logger.info("found 5-button mouse")
        else:
            self.logger.warn("found unknown mouse with ID %#04x", ident)

        if args.resolution is not None:
            await mouse_iface.set_resolution(args.resolution)
        if args.sample_rate is not None:
            await mouse_iface.set_sample_rate(args.sample_rate)
        if args.acceleration is not None:
            await mouse_iface.set_autospeed(args.acceleration)

        if args.operation == "stream-log":
            async for report in mouse_iface.stream_reports(ident):
                overflow = report.overflow_x or report.overflow_y
                self.logger.log(logging.WARN if overflow else logging.INFO,
                    "btn=%s%s%s%s%s x=%+4d%s y=%+4d%s z=%+2d",
                    "L" if report.left     else "-",
                    "M" if report.middle   else "-",
                    "R" if report.right    else "-",
                    "4" if report.button_4 else "-",
                    "5" if report.button_5 else "-",
                    report.offset_x, "!" if report.overflow_x else "",
                    report.offset_y, "!" if report.overflow_y else "",
                    report.offset_z)

        if args.operation == "stream-uinput":
            try:
                import uinput
            except ImportError:
                raise SensorMousePS2Error("uinput not installed")
            device = uinput.Device([
                uinput.BTN_LEFT,
                uinput.BTN_MIDDLE,
                uinput.BTN_RIGHT,
                uinput.BTN_4,
                uinput.BTN_5,
                uinput.REL_X,
                uinput.REL_Y,
                uinput.REL_WHEEL,
            ])

            async for report in mouse_iface.stream_reports(ident):
                device.emit(uinput.BTN_LEFT,   report.left,     syn=False)
                device.emit(uinput.BTN_MIDDLE, report.middle,   syn=False)
                device.emit(uinput.BTN_RIGHT,  report.right,    syn=False)
                device.emit(uinput.BTN_4,      report.button_4, syn=False)
                device.emit(uinput.BTN_5,      report.button_5, syn=False)
                device.emit(uinput.REL_X,      report.offset_x * args.invert_x, syn=False)
                device.emit(uinput.REL_Y,      report.offset_y * args.invert_y, syn=False)
                device.emit(uinput.REL_WHEEL, -report.offset_z, syn=False)
                device.syn()
