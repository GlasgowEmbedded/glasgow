import struct
import logging
import argparse
from bitarray import bitarray

from .. import *
from ..jtag import JTAGApplet
from ...arch.jtag import *
from ...protocol.jtag_svf import *


class SVFOperation:
    def __init__(self, tdi, smask, tdo, mask):
        self.tdi   = tdi
        self.smask = smask
        self.tdo   = tdo
        self.mask  = mask

    def __add__(self, other):
        assert isinstance(other, SVFOperation)

        if self.tdo is None and other.tdo is None:
            # Propagate "TDO don't care".
            tdo = None
        else:
            # Replace "TDO don't care" with all-don't-care mask bits (which are guaranteed
            # to be in that state by SVFParser).
            tdo = (self.tdo or self.mask) + (other.tdo or other.mask)

        return SVFOperation(self.tdi   + other.tdi,
                            self.smask + other.smask,
                                 tdo,
                            self.mask  + other.mask)


class JTAGSVFInterface(SVFEventHandler):
    def __init__(self, interface, logger, frequency):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._frequency = frequency

        self._endir  = "IDLE"
        self._enddr  = "IDLE"

        self._hir    = SVFOperation(bitarray(), bitarray(), None, bitarray())
        self._tir    = SVFOperation(bitarray(), bitarray(), None, bitarray())
        self._hdr    = SVFOperation(bitarray(), bitarray(), None, bitarray())
        self._tdr    = SVFOperation(bitarray(), bitarray(), None, bitarray())

    def _log(self, message, *args):
        self._logger.log(self._level, "SVF: " + message, *args)

    async def _enter_state(self, state, path=[]):
        if path:
            raise GlasgowAppletError("explicitly providing TAP state path is not supported")

        if state == "RESET":
            await self.lower.enter_test_logic_reset(force=False)
        elif state == "IDLE":
            await self.lower.enter_run_test_idle()
        elif state == "IRPAUSE":
            await self.lower.enter_pause_ir()
        elif state == "DRPAUSE":
            await self.lower.enter_pause_dr()
        else:
            assert False

    async def svf_frequency(self, frequency):
        if frequency is not None and frequency < self._frequency:
            raise GlasgowAppletError("FREQUENCY command requires a lower frequency (%.3f kHz) "
                                     "than the applet is configured for (%.3f kHz)"
                                     % (frequency / 1e3, args.frequency / 1e3))

    async def svf_trst(self, mode):
        if mode == "ABSENT":
            pass # ignore; the standard doesn't seem to specify what to do?
        elif mode == "Z":
            await self.lower.set_trst(state=None)
        elif mode == "ON":
            await self.lower.set_trst(state=True)
        elif mode == "OFF":
            await self.lower.set_trst(state=False)
        else:
            assert False

    async def svf_state(self, state, path):
        await self._enter_state(state, path)

    async def svf_endir(self, state):
        self._endir = state

    async def svf_enddr(self, state):
        self._enddr = state

    async def svf_hir(self, tdi, smask, tdo, mask):
        self._hir = SVFOperation(tdi, smask, tdo, mask)

    async def svf_tir(self, tdi, smask, tdo, mask):
        self._tir = SVFOperation(tdi, smask, tdo, mask)

    async def svf_hdr(self, tdi, smask, tdo, mask):
        self._hdr = SVFOperation(tdi, smask, tdo, mask)

    async def svf_tdr(self, tdi, smask, tdo, mask):
        self._tdr = SVFOperation(tdi, smask, tdo, mask)

    async def svf_sir(self, tdi, smask, tdo, mask):
        op = self._hir + SVFOperation(tdi, smask, tdo, mask) + self._tir
        await self.lower.enter_shift_ir()
        if op.tdo is None:
            await self.lower.shift_tdi(op.tdi)
        else:
            tdo = await self.lower.shift_tdio(op.tdi)
            if tdo & op.mask != op.tdo & op.mask:
                raise GlasgowAppletError("SIR command failed: TDO <%s> & <%s> != <%s>"
                                         % (tdo.to01(), op.mask.to01(), op.tdo.to01()))
        await self._enter_state(self._endir)

    async def svf_sdr(self, tdi, smask, tdo, mask):
        op = self._hdr + SVFOperation(tdi, smask, tdo, mask) + self._tdr
        await self.lower.enter_shift_dr()
        if op.tdo is None:
            await self.lower.shift_tdi(op.tdi)
        else:
            tdo = await self.lower.shift_tdio(op.tdi)
            if tdo & op.mask != op.tdo & op.mask:
                raise GlasgowAppletError("SDR command failed: TDO <%s> & <%s> != <%s>"
                                         % (tdo.to01(), op.mask.to01(), op.tdo.to01()))
        await self._enter_state(self._enddr)

    async def svf_runtest(self, run_state, run_count, run_clock, min_time, max_time, end_state):
        if run_clock != "TCK":
            raise GlasgowAppletError("RUNTEST clock %s is not supported" % run_count)
        if run_count is None or min_time is not None and run_count / self._frequency < min_time:
            run_count = int(self._frequency * min_time)
        if max_time is not None and run_count / self._frequency > max_time:
            self._logger.warning("RUNTEST exceeds maximum time: %d cycles (%.3f s) > %.3f s"
                                 % (run_count, run_count / self._frequency, max_time))

        await self._enter_state(run_state)
        await self.lower.pulse_tck(run_count)
        await self._enter_state(end_state)

    async def svf_piomap(self, mapping):
        raise GlasgowAppletError("the PIOMAP command is not supported")

    async def svf_pio(self, vector):
        raise GlasgowAppletError("the PIO command is not supported")


class JTAGSVFApplet(JTAGApplet, name="jtag-svf"):
    logger = logging.getLogger(__name__)
    help = "play SVF test vectors via JTAG"
    description = """
    Play SVF test vectors via the JTAG interface.

    This applet currently does not implement some SVF features:
        * PIOMAP and PIO are not supported;
        * Explict state path may not be specified for STATE;
        * The SCK clock in RUNTEST is not supported.

    If any commands requiring these features are encountered, the applet terminates itself.
    """

    async def run(self, device, args):
        jtag_iface = await super().run(device, args)
        await jtag_iface.pulse_trst()

        return JTAGSVFInterface(jtag_iface, self.logger, args.frequency * 1000)

    @classmethod
    def add_interact_arguments(cls, parser):
        parser.add_argument(
            "svf_file", metavar="SVF-FILE", type=argparse.FileType("r"),
            help="test vector to play")

    async def interact(self, device, args, svf_iface):
        svf_parser = SVFParser(args.svf_file.read(), svf_iface)
        while True:
            coro = svf_parser.parse_command()
            if not coro: break

            for line in svf_parser.last_command().split("\n"):
                line = line.strip()
                if line: svf_iface._log(line)

            await coro
