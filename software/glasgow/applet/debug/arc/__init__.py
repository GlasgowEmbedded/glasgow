# Ref: ARC® 700 External Interfaces Reference
# Document Number: 5117-014
# Accession: G00004
# Ref: Microchip MEC1618/MEC1618i Low Power 32-bit Microcontroller with Embedded Flash
# Document Number: DS00002339A
# Accession: G00005
# Ref: Microchip MEC1609 Mixed Signal Mobile Embedded Flash ARC EC BC-Link/VLPC Base Component
# Document Number: DS00002485A
# Accession: G00006

# The ARC JTAG TAP core has an important quirk: all transactions are initiated by a TCK pulse
# in Run-Test/Idle state:
#
#   The Run-Test/Idle state always precedes the Test-Logic-Reset, Update-DR and Update-IR states
#   on the rising edge of TCK when TMS is low. This state is employed to initiate a read/write
#   access or place the JTAG module in the idle state. The read/write access defined by the
#   address, data and command registers only occurs once on entry to Run-Test/Idle.

import logging
import argparse

from ....arch.jtag import *
from ....arch.arc import *
from ....database.arc import *
from ...interface.jtag_probe import JTAGProbeApplet
from ... import *


class ARCDebugError(GlasgowAppletError):
    pass


class ARCDebugInterface:
    def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, "ARC: " + message, *args)

    async def identify(self):
        await self.lower.test_reset()
        idcode_bits = await self.lower.read_dr(32)
        idcode = DR_IDCODE.from_bits(idcode_bits)
        self._log("read IDCODE mfg_id=%03x arc_type=%02x arc_number=%03x",
                  idcode.mfg_id, idcode.part_id & 0b111111, idcode.part_id >> 6)
        device = devices[idcode.mfg_id, idcode.part_id & 0b111111]
        return idcode, device

    async def _wait_txn(self):
        await self.lower.write_ir(IR_STATUS)
        status = DR_STATUS()
        while not status.RD:
            status_bits = await self.lower.read_dr(4)
            status = DR_STATUS.from_bits(status_bits)
            self._log("status %s", status.bits_repr())
            if status.FL:
                raise ARCDebugError("transaction failed: %s" % status.bits_repr())

    async def read(self, address, space):
        if space == "memory":
            dr_txn_command = DR_TXN_COMMAND_READ_MEMORY
        elif space == "core":
            dr_txn_command = DR_TXN_COMMAND_READ_CORE
        elif space == "aux":
            dr_txn_command = DR_TXN_COMMAND_READ_AUX
        else:
            assert False

        self._log("read %s address=%08x", space, address)
        dr_address = DR_ADDRESS(Address=address)
        await self.lower.write_ir(IR_ADDRESS)
        await self.lower.write_dr(dr_address.to_bits())
        await self.lower.write_ir(IR_TXN_COMMAND)
        await self.lower.write_dr(dr_txn_command)
        await self.lower.run_test_idle(1)
        await self._wait_txn()
        await self.lower.write_ir(IR_DATA)
        dr_data_bits = await self.lower.read_dr(32)
        dr_data = DR_DATA.from_bits(dr_data_bits)
        self._log("read data=%08x", dr_data.Data)
        return dr_data.Data

    async def write(self, address, data, space):
        if space == "memory":
            dr_txn_command = DR_TXN_COMMAND_WRITE_MEMORY
        elif space == "core":
            dr_txn_command = DR_TXN_COMMAND_WRITE_CORE
        elif space == "aux":
            dr_txn_command = DR_TXN_COMMAND_WRITE_AUX
        else:
            assert False

        self._log("write %s address=%08x data=%08x", space, address, data)
        dr_address = DR_ADDRESS(Address=address)
        await self.lower.write_ir(IR_ADDRESS)
        await self.lower.write_dr(dr_address.to_bits())
        await self.lower.write_ir(IR_DATA)
        dr_data = DR_DATA(Data=data)
        await self.lower.write_dr(dr_data.to_bits())
        await self.lower.write_ir(IR_TXN_COMMAND)
        await self.lower.write_dr(dr_txn_command)
        await self.lower.run_test_idle(1)
        await self._wait_txn()

    async def set_halted(self, halted):
        await self.write(AUX_STATUS32_addr, AUX_STATUS32(halted=halted).to_int(), space="aux")


class DebugARCApplet(JTAGProbeApplet, name="debug-arc"):
    logger = logging.getLogger(__name__)
    help = "debug ARC processors via JTAG"
    description = """
    Debug ARC processors via the JTAG interface.

    The list of supported devices is:
{devices}

    There is currently no debug server implemented. This applet only allows manipulating Memory,
    Core and Aux spaces via a Python REPL.
    """.format(
        devices="\n".join(map(lambda x: "        * {.name}".format(x), devices.values()))
    )

    @classmethod
    def add_run_arguments(cls, parser, access):
        super().add_run_arguments(parser, access)
        super().add_run_tap_arguments(parser)

    async def run(self, device, args):
        tap_iface = await self.run_tap(DebugARCApplet, device, args)
        return ARCDebugInterface(tap_iface, self.logger)

    @classmethod
    def add_interact_arguments(cls, parser):
        pass

    async def interact(self, device, args, arc_iface):
        idcode, device = await arc_iface.identify()
        if device is None:
            raise GlasgowAppletError("cannot operate on unknown device with IDCODE=%08x"
                                     % idcode.to_int())
        self.logger.info("IDCODE=%08x device=%s rev=%d",
                         idcode.to_int(), device.name, idcode.version)
