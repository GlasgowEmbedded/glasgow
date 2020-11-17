# Ref: https://static.docs.arm.com/ihi0031/c/IHI0031C_debug_interface_as.pdf
# Document Number: IHI0031C
# Accession: G00027

from abc import ABCMeta, abstractmethod

from ....database.jedec import *
from ....arch.arm.dap import *
from ... import *


__all__ = ["ARMDPInterface", "ARMAPTransactionError", "DebugARMAppletMixin"]


class ARMDPError(GlasgowAppletError):
    pass


class ARMAPTransactionError(GlasgowAppletError):
    pass


class ARMDPInterface(metaclass=ABCMeta):
    @abstractmethod
    def _log(self, message, *args):
        pass

    # Data link dependent interface

    @abstractmethod
    async def reset(self):
        """Reset the data link layer."""

    @abstractmethod
    async def write_dp_reg(self, addr, value):
        """Write ``value`` to the data link independent DP register at ``addr``.

        In ADIv5.2, this may be only ``CTRL/STAT``, and data link dependent bits must be zero."""

    @abstractmethod
    async def read_dp_reg(self, addr):
        """Read ``value`` from the data link independent DP register at ``addr``.

        In ADIv5.2, this may be ``CTRL/STAT``, ``DPIDR``, ``TARGETID``, and ``EVENTSTAT``."""

    @abstractmethod
    async def write_ap_reg(self, index, addr, value):
        """Select AP ``index`` and write ``value`` to the AP register at ``addr``."""

    @abstractmethod
    async def read_ap_reg(self, index, addr):
        """Select AP ``index`` and read ``value`` from the AP register at ``addr``."""

    # Data link independent interface

    async def set_debug_power(self, enabled):
        dp_ctrl_stat = DP_CTRL_STAT.from_int(await self.read_dp_reg(DP_CTRL_STAT_addr))
        dp_ctrl_stat.CDBGPWRUPREQ = enabled
        await self.write_dp_reg(DP_CTRL_STAT_addr, dp_ctrl_stat.to_int())

        for _ in range(4):
            dp_ctrl_stat = DP_CTRL_STAT.from_int(await self.read_dp_reg(DP_CTRL_STAT_addr))
            if dp_ctrl_stat.CDBGPWRUPACK == enabled:
                break
        else:
            raise ARMDPError("cannot %s debug power".format("enable" if enabled else "disable"))

    async def set_system_power(self, enabled):
        dp_ctrl_stat = DP_CTRL_STAT.from_int(await self.read_dp_reg(DP_CTRL_STAT_addr))
        dp_ctrl_stat.CSYSPWRUPREQ = enabled
        await self.write_dp_reg(DP_CTRL_STAT_addr, dp_ctrl_stat.to_int())

        for _ in range(4):
            dp_ctrl_stat = DP_CTRL_STAT.from_int(await self.read_dp_reg(DP_CTRL_STAT_addr))
            if dp_ctrl_stat.CSYSPWRUPACK == enabled:
                break
        else:
            raise ARMDPError("cannot %s system power".format("enable" if enabled else "disable"))


class DebugARMAppletMixin:
    @classmethod
    def add_interact_arguments(cls, parser):
        pass

    async def interact(self, device, args, dp_iface):
        await dp_iface.set_debug_power(True)

        for ap_index in range(256):
            try:
                ap_idr = AP_IDR.from_int(await dp_iface.read_ap_reg(ap_index, AP_IDR_addr))
            except ARMAPTransactionError:
                # There's an AP at this index but it doesn't work.
                self.logger.error("AP #%d: IDR read error", ap_index)
                continue

            if ap_idr.to_int() == 0:
                # No AP at this index.
                self.logger.debug("AP #%d: IDR=0", ap_index)
                continue

            # "For backwards compatibility, debuggers must treat an AP return a JEP106 field
            # of zero as an AP designed by Arm. This encoding was used in early implementations
            # of the DAP. In such an implementation, the REVISION and CLASS fields are also RAZ."
            if ap_idr.DESIGNER == 0:
                ap_idr.DESIGNER = 0x43B # Arm

            designer_name = jedec_mfg_name_from_bank_num(ap_idr.DESIGNER >> 7,
                                                         ap_idr.DESIGNER & 0x7f)
            if designer_name is None:
                designer_name = "unknown"

            self.logger.info("AP #%d: IDR=%#10x", ap_index, ap_idr.to_int())
            self.logger.info("designer=%#5x (%s) class=%#3x (%s) type=%#3x (%s) "
                             "variant=%#3x revision=%#3x",
                             ap_idr.DESIGNER, designer_name,
                             ap_idr.CLASS, AP_IDR_CLASS(ap_idr.CLASS),
                             ap_idr.TYPE, "unknown",
                             ap_idr.VARIANT,
                             ap_idr.REVISION)
