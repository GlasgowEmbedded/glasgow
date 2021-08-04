# Ref: https://static.docs.arm.com/ihi0031/c/IHI0031C_debug_interface_as.pdf
# Document Number: IHI0031C
# Accession: G00027

import logging
import argparse

from ....support.aobject import *
from ....arch.jtag import *
from ....arch.arm.jtag import *
from ....arch.arm.dap.dp import *
from ...interface.jtag_probe import JTAGProbeApplet
from . import *


class ARMJTAGDPInterface(ARMDPInterface, aobject):
    # Mask with all data link independent fields in the CTRL/STAT DP register.
    _DP_CTRL_STAT_mask = DP_CTRL_STAT(
        TRNMODE=0b11, TRNCNT=0xFFF, MASKLANE=0b1111,
        CDBGRSTREQ=0b1, CDBGRSTACK=0b1,
        CDBGPWRUPREQ=0b1, CDBGPWRUPACK=0b1,
        CSYSPWRUPREQ=0b1, CSYSPWRUPACK=0b1).to_int()

    async def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._select = DP_SELECT()

        await self.reset()

    def _log(self, message, *args):
        self._logger.log(self._level, "JTAG-DP: " + message, *args)

    # Low-level xPACC operations

    async def _write_dpacc(self, addr, value):
        await self.lower.write_ir(IR_DPACC)

        dr_update = DR_xPACC_update(RnW=0, A=(addr & 0xf) >> 2, DATAIN=value)
        # TODO: use JTAG masked compare when implemented
        dr_capture = DR_xPACC_capture.from_bits(await self.lower.exchange_dr(dr_update.to_bits()))
        assert dr_capture.ACK == DR_xPACC_ACK.OK_FAULT

    async def _read_dpacc(self, addr):
        await self.lower.write_ir(IR_DPACC)

        dr_update = DR_xPACC_update(RnW=1, A=(addr & 0xf) >> 2)
        # TODO: use JTAG masked compare when implemented
        dr_capture = DR_xPACC_capture.from_bits(await self.lower.exchange_dr(dr_update.to_bits()))
        assert dr_capture.ACK == DR_xPACC_ACK.OK_FAULT

        # TODO: pick a better nop than repeated read?
        dr_capture = DR_xPACC_capture.from_bits(await self.lower.exchange_dr(dr_update.to_bits()))
        assert dr_capture.ACK == DR_xPACC_ACK.OK_FAULT

        return dr_capture.ReadResult

    async def _poll_apacc(self):
        await self.lower.write_ir(IR_DPACC)

        dp_update_bits = DR_xPACC_update(RnW=1, A=DP_CTRL_STAT_addr >> 2).to_bits()
        while True:
            ap_capture = DR_xPACC_capture.from_bits(await self.lower.exchange_dr(dp_update_bits))
            if ap_capture.ACK != DR_xPACC_ACK.WAIT:
                break
            self._log("ap wait")
        assert ap_capture.ACK == DR_xPACC_ACK.OK_FAULT

        dp_capture = DR_xPACC_capture.from_bits(await self.lower.exchange_dr(dp_update_bits))
        assert dp_capture.ACK == DR_xPACC_ACK.OK_FAULT

        dp_ctrl_stat = DP_CTRL_STAT.from_int(dp_capture.ReadResult)
        assert not dp_ctrl_stat.STICKYORUN, "AP transaction overrun"
        if dp_ctrl_stat.STICKYERR:
            dp_update_bits = DR_xPACC_update(
                RnW=0, A=DP_CTRL_STAT_addr >> 2, DATAIN=dp_ctrl_stat.to_int()).to_bits()
            dp_capture = DR_xPACC_capture.from_bits(await self.lower.exchange_dr(dp_update_bits))
            assert dp_capture.ACK == DR_xPACC_ACK.OK_FAULT

            raise ARMAPTransactionError("AP transaction error")
        else:
            return ap_capture.ReadResult

    async def _write_apacc(self, addr, value):
        await self.lower.write_ir(IR_APACC)

        dr_update = DR_xPACC_update(RnW=0, A=(addr & 0xf) >> 2, DATAIN=value)
        # TODO: use JTAG masked compare when implemented
        dr_capture = DR_xPACC_capture.from_bits(await self.lower.exchange_dr(dr_update.to_bits()))
        assert dr_capture.ACK == DR_xPACC_ACK.OK_FAULT

        await self._poll_apacc()

    async def _read_apacc(self, addr):
        await self.lower.write_ir(IR_APACC)

        dr_update = DR_xPACC_update(RnW=1, A=(addr & 0xf) >> 2)
        # TODO: use JTAG masked compare when implemented
        dr_capture = DR_xPACC_capture.from_bits(await self.lower.exchange_dr(dr_update.to_bits()))
        assert dr_capture.ACK == DR_xPACC_ACK.OK_FAULT

        return await self._poll_apacc()

    # High-level DP and AP register operations

    async def reset(self):
        self._log("reset")
        await self.lower.test_reset()
        # DP registers are not reset by Debug-Logic-Reset (or anything else except power-on reset);
        # make sure our cached state matches DP's actual state.
        await self._write_dpacc(DP_SELECT_addr, self._select.to_int())

    async def _prepare_dp_reg(self, addr):
        assert addr in range(0x00, 0x100, 4)
        if addr & 0xf != 0x4:
            pass # DP accessible from any bank
        elif self._select.DPBANKSEL == addr >> 4:
            self._log("dp select (elided)")
            pass # DP bank matches cached SELECT register
        else:
            self._log("dp select bank=%#3x", addr >> 4)
            self._select.DPBANKSEL = addr >> 4
            await self._write_dpacc(DP_SELECT_addr, self._select.to_int())

    async def _write_dp_reg(self, addr, value):
        await self._prepare_dp_reg(addr)
        self._log("dp write addr=%#04x data=%#010x", addr, value)
        await self._write_dpacc(addr, value)

    async def _read_dp_reg(self, addr):
        await self._prepare_dp_reg(addr)
        self._log("dp read addr=%#04x", addr)
        value = await self._read_dpacc(addr)
        self._log("dp read data=%#010x", value)
        return value

    async def write_dp_reg(self, addr, value):
        assert addr in (DP_CTRL_STAT_addr,)
        assert value & ~self._DP_CTRL_STAT_mask == 0, \
              "Data link defined DP register bits may not be set"
        await self._write_dp_reg(addr, value)

    async def read_dp_reg(self, addr):
        assert addr in (DP_CTRL_STAT_addr, DP_DPIDR_addr, DP_TARGETID_addr, DP_EVENTSTAT_addr)
        return await self._read_dp_reg(addr)

    async def _prepare_ap_reg(self, id, addr):
        assert id in range(256) and addr in range(0x00, 0x100, 4)
        if self._select.APSEL == id and self._select.APBANKSEL == addr >> 4:
            self._log("ap select (elided)")
            pass # AP ID/bank matches cached SELECT register
        else:
            self._log("ap select id=%d bank=%#3x", id, addr >> 4)
            self._select.APSEL = id
            self._select.APBANKSEL = addr >> 4
            await self._write_dpacc(DP_SELECT_addr, self._select.to_int())

    async def write_ap_reg(self, index, addr, value):
        await self._prepare_ap_reg(index, addr)
        self._log("ap write id=%d addr=%#04x data=%#010x", index, addr, value)
        await self._write_apacc(addr, value)

    async def read_ap_reg(self, index, addr):
        await self._prepare_ap_reg(index, addr)
        self._log("ap read id=%d addr=%#04x", index, addr)
        value = await self._read_apacc(addr)
        self._log("ap read data=%#010x", value)
        return value


class DebugARMJTAGApplet(DebugARMAppletMixin, JTAGProbeApplet, name="debug-arm-jtag"):
    preview = True
    logger = logging.getLogger(__name__)
    help = "debug ARM processors via JTAG"
    description = """
    Debug ARM processors with CoreSight support via the JTAG interface.
    """

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)
        super().add_run_tap_arguments(parser)

    async def run(self, device, args):
        tap_iface = await self.run_tap(DebugARMJTAGApplet, device, args)
        return await ARMJTAGDPInterface(tap_iface, self.logger)
