# Ref: https://static.docs.arm.com/ihi0031/c/IHI0031C_debug_interface_as.pdf
# Document Number: IHI0031C
# Accession: G00027

from abc import ABCMeta, abstractmethod

from ....database.jedec import *
from ....arch.arm.dap import *


__all__ = ["ARMDPInterface", "DebugARMAppletMixin"]


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

    async def iter_aps(self):
        for ap_index in range(256):
            ap_idr = AP_IDR.from_int(await self.read_ap_reg(ap_index, AP_IDR_addr))
            if ap_idr.to_int() == 0:
                break
            # For backwards compatibility, debuggers must treat an AP return a JEP106 field
            # of zero as an AP designed by Arm. This encoding was used in early implementations
            # of the DAP. In such an implementation, the REVISION and CLASS fields are also RAZ.
            if ap_idr.DESIGNER == 0:
                ap_idr.DESIGNER = 0x43B # Arm
            yield ap_index, ap_idr


class DebugARMAppletMixin:
    @classmethod
    def add_interact_arguments(cls, parser):
        pass

    async def interact(self, device, args, dp_iface):
        async for ap_index, ap_idr in dp_iface.iter_aps():
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
