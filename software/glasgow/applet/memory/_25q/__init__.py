import dataclasses
import argparse
import logging
import re

from amaranth import *

from glasgow.support.logging import dump_hex
from glasgow.arch.qspi import nor
from glasgow.database.jedec import jedec_mfg_name_from_bytes
from glasgow.support.progress import Progress
from glasgow.protocol.sfdp import \
    SFDPCollection, SFDPJEDECFlashParametersTable, SFDPJEDECQuadEnableRequirements
from glasgow.abstract import GlasgowPin
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2
from glasgow.applet.interface.qspi_controller import QSPIControllerInterface, QSPIControllerApplet


__all__ = ["Memory25QError", "Memory25QVerifyError", "Memory25QInterface"]


class Memory25QError(GlasgowAppletError):
    pass


class Memory25QVerifyError(Memory25QError):
    pass


class Memory25QInterface:
    """Make sure to call :meth:`initialize` first."""

    qspi: QSPIControllerInterface
    """Underlying QSPI interface."""

    cmds: nor.CommandSet
    """Active NOR command set.

    The command set may be modified or extended after the interface is created to better represent
    actual capabilities of the memory device.
    """

    sfdp: SFDPCollection | None
    """SFDP table collection.

    Populated only if the tables were parsed successfully.
    """

    sfdp_used: bool
    """Whether SFDP tables are usable.

    Will be :py:`True` if SFDP information was used to successfully configure data transfer
    parameters, :py:`False` otherwise.
    """

    def __init__(self, logger: logging.Logger, assembly, *,
            cs: GlasgowPin, sck: GlasgowPin, io: GlasgowPin):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        self.qspi = QSPIControllerInterface(logger, assembly, cs=cs, sck=sck, io=io)
        self.cmds = nor.CommandSet()
        self.sfdp = None
        self.sfdp_used = False

    def _log(self, message, *args):
        self._logger.log(self._level, "25Q: " + message, *args)

    def _mode(self, command: nor.Command) -> nor.CommandMode:
        return self.cmds[command].mode

    @property
    def jedec_params(self) -> SFDPJEDECFlashParametersTable | None:
        # Not documented because the SFDP API is undocumented and also kind of terrible.
        if self.sfdp is not None:
            return self.sfdp.jedec_flash_table
        return None

    @property
    def memory_size(self) -> int | None:
        """Memory size.

        Size of the data region in bytes, or :py:`None` if SFDP data is not populated.
        """
        if (params := self.jedec_params) is not None:
            return params.density_bytes
        return None

    async def power_up(self):
        """Power up the device.

        Implemented using
        :data:`Opcode.ReleasePowerDown <glasgow.arch.qspi.nor.Opcode.ReleasePowerDown>`.

        .. important::

            A memory may not accept any commands besides this one if it is in a deep power-down
            state.
        """
        self._log("power up")
        await self.qspi.execute_cmd(self.cmds[nor.Command.PowerUp])

    async def power_down(self):
        """Power down the device.

        Implemented using :data:`Opcode.PowerDown <glasgow.arch.qspi.nor.Opcode.PowerDown>`.

        See :meth:`power_up`.
        """
        self._log("power down")
        await self.qspi.execute_cmd(self.cmds[nor.Command.PowerDown])

    async def jedec_id(self) -> tuple[int, int]:
        """Read JEDEC IDs.

        Implemented using :data:`Opcode.ReadJEDEC <glasgow.arch.qspi.nor.Opcode.ReadJEDEC>`.

        Returns :py:`(jedec_mfg_id, device_id)`.
        """
        data = await self.qspi.execute_read(self.cmds[nor.Command.ReadJEDEC])
        jedec_mfg_id, device_id = data[0], data[1] << 8 | data[2]
        self._log("read jedec mfg=%02x device=%04x", jedec_mfg_id, device_id)
        return jedec_mfg_id, device_id

    async def read_sfdp(self, address: int, length: int) -> memoryview:
        """Read SFDP information.

        Implemented using :data:`Opcode.ReadSFDP <glasgow.arch.qspi.nor.Opcode.ReadSFDP>`.

        Returns :py:`length` SFDP bytes starting at :py:`address`, wrapping when reading past
        the end of the SFDP region.
        """
        data = await self.qspi.execute_read(self.cmds[nor.Command.ReadSFDP],
            address=address, length=length)
        self._log("read sfdp addr=%06x len=%06x data=<%s>", address, length, dump_hex(data))
        return data

    async def initialize(self, *, enable_dual: bool = False, enable_quad: bool = False):
        """Prepare device for data transfer.

        Powers up the device and populates :data:`sfdp` (if possible).
        """
        await self.power_up()
        # TODO: reset device here (to clear e.g. volatile registers for 4-byte addressing)
        try:
            self.sfdp = await SFDPCollection.parse(self.read_sfdp)
        except ValueError as err:
            self.sfdp = None
            self._logger.warning(f"device does not have valid SFDP tables: {err}")
        else:
            try:
                # If SFDP data exists, we would like to take it to be axiomatically correct...
                # ... but, unfortunately, vendors. So we have to apply quirks first.
                if quirks := self.cmds.apply_quirks(self.sfdp):
                    self._logger.warning(f"applied quirks: {', '.join(quirks)}")
                self.cmds.use_jesd216(self.sfdp, enable_dual=enable_dual, enable_quad=enable_quad)
                self.sfdp_used = True
            except ValueError as err:
                # Missing tables, unsupported addressing mode, etc.
                self._logger.error(f"device has valid but unsupported SFDP tables: {err}")

    async def _execute_data_operation_prologue(self, address: int):
        for oper in self.cmds.data_operation_prologue(address):
            match oper:
                case nor.Instruction() as instr:
                    await self.qspi.execute_cmd(instr)
                case (nor.Instruction() as instr, data):
                    await self.qspi.execute_write(instr, data=data)
                case _:
                    assert False

    async def read_data(self, address: int, length: int) -> bytes:
        """Read data.

        Implemented using the :data:`Command.ReadData <glasgow.arch.qspi.nor.Command.ReadData>`,
        which is typically but not necessarily mapped to one of:

        * :data:`Opcode.Read <glasgow.arch.qspi.nor.Opcode.Read>`
        * :data:`Opcode.FastRead <glasgow.arch.qspi.nor.Opcode.FastRead>`
        * :data:`Opcode.FastReadDualOutput <glasgow.arch.qspi.nor.Opcode.FastReadDualOutput>`
        * :data:`Opcode.FastReadQuadOutput <glasgow.arch.qspi.nor.Opcode.FastReadQuadOutput>`
        * :data:`Opcode.FastReadDualInOut <glasgow.arch.qspi.nor.Opcode.FastReadDualInOut>`
        * :data:`Opcode.FastReadQuadInOut <glasgow.arch.qspi.nor.Opcode.FastReadQuadInOut>`

        Returns :py:`length` data bytes starting at :py:`address`, wrapping when reading past
        the end of the data region.

        Raises
        ------
        Memory25QError
            If no read commands are configured.
        """
        if nor.Command.ReadData not in self.cmds:
            raise Memory25QError("no read commands configured")
        # Use a fixed 64K chunk size for progress indication. Most other operations have a "natural"
        # chunk size that is also useful for UI feedback, but reads don't.
        result = bytearray()
        for chunk in Progress.chunks(range(address, address + length), 0x10000,
                action="reading", item="B", scale=1024):
            await self._execute_data_operation_prologue(address)
            data = await self.qspi.execute_read(self.cmds[nor.Command.ReadData],
                address=chunk.start, length=len(chunk))
            self._log("read data %s addr=%08x len=%08x data=<%s>",
                self._mode(nor.Command.ReadData), address, length, dump_hex(data))
            result += data
        return result

    async def read_status_reg_1(self) -> nor.StatusReg1:
        """Read Status Register 1.

        Implemented using
        :data:`Opcode.ReadStatusReg1 <glasgow.arch.qspi.nor.Opcode.ReadStatusReg1>`.
        """
        value, = await self.qspi.execute_read(self.cmds[nor.Command.ReadStatusReg1])
        return nor.StatusReg1(value)

    async def write_status_reg_1(self, value: nor.StatusReg1):
        """Write Status Register 1.

        Implemented using
        :data:`Opcode.WriteStatusReg1 <glasgow.arch.qspi.nor.Opcode.WriteStatusReg1>`.
        """
        await self.qspi.execute_cmd(self.cmds[nor.Command.WriteEnable])
        await self.qspi.execute_write(self.cmds[nor.Command.WriteStatusRegs], data=bytes([value]))
        await self.poll_busy()

    async def write_enable(self):
        """Prefix for write operations.

        All methods of this interface that perform write operations internally enable writes; only
        call this method explicitly when implementing new operations.

        Raises
        ------
        Memory25QError
            If the :data:`BUSY <glasgow.arch.qspi.nor.StatusReg1.BUSY>` bit is set
            in Status Register 1.
        Memory25QError
            If the operation fails to set the :data:`WREN <glasgow.arch.qspi.nor.StatusReg1.WREN>`
            bit in Status Register 1.
        """
        sr1 = await self.read_status_reg_1()
        if sr1 & nor.StatusReg1.BUSY != 0:
            raise Memory25QError("refusing to issue WriteEnable command: BUSY bit set")
        await self.qspi.execute_cmd(self.cmds[nor.Command.WriteEnable])
        sr1 = await self.read_status_reg_1()
        if sr1 & nor.StatusReg1.WREN == 0:
            raise Memory25QError("WriteEnable command failed: WREN bit not set")

    async def poll_busy(self):
        """Wait until operation is done.

        Polls Status Register 1 until the :data:`BUSY <glasgow.arch.qspi.nor.StatusReg1.BUSY>` bit
        is clear.

        All methods of this interfaces that perform write operations internally wait for completion;
        only call this method explicitly when implementing new operations.

        Raises
        ------
        Memory25QError
            If the :data:`WREN <glasgow.arch.qspi.nor.StatusReg1.WREN>` bit in Status Register 1
            is still set after the :data:`BUSY <glasgow.arch.qspi.nor.StatusReg1.BUSY>` bit clears.
            This usually means that the preceding operation failed.
        """
        while True:
            # Strictly speaking, per JESD216, polling SR1 for BUSY flag is considered
            # "Legacy Polling" and the standard leaves room for not implementing it. This seems
            # so unlikely to happen in reality though that we ignore it. (14th DWORD has a feature
            # bitmask with an alternate method.)
            sr1 = await self.read_status_reg_1()
            if sr1 & nor.StatusReg1.BUSY == 0:
                break
            # TODO: This is a pretty low delay. Adding native support for SR polling in the QSPI
            # controller would remove a lot of load from the CPU during erasing/programming.
            await self.qspi.delay_ms(10)
        if sr1 & nor.StatusReg1.WREN != 0:
            # Some devices (e.g. Macronix MX25L3205D) have a race condition between clearing BUSY
            # and clearing WREN that falsely indicates a failed operation. Make sure we're not
            # hitting it.
            sr1 = await self.read_status_reg_1()
            if sr1 & nor.StatusReg1.WREN != 0:
                raise Memory25QError("operation failed")

    async def set_quad_enabled(self, enabled: bool = True):
        """Enable or disable quad-SPI instructions.

        Most devices power on and/or arrive from the factory configured with IO2/IO3 pins having
        the WP#/HOLD# function. Using quad-SPI instructions requires switching them to data I/O
        first. Since this can cause bus contention and disables hardware write protection (if any),
        this action must be taken explicitly.

        Raises
        ------
        Memory25QError
            If SFDP tables are not available.
        NotImplementedError
            If the device-specific enablement algorithm has not been implemented.
        """
        if (jedec_params := self.jedec_params) is None:
            raise Memory25QError("SFDP tables not available")
        def update(sr, bit): return sr | (1 << bit) if enabled else sr & ~(1 << bit)
        self._log("quad %s (%s)", "enable" if enabled else "disable",
            jedec_params.quad_enable_requirements.name)
        match jedec_params.quad_enable_requirements:
            case SFDPJEDECQuadEnableRequirements.Absent:
                pass # no enablement necessary; quad instructions (if any) always work
            case SFDPJEDECQuadEnableRequirements.Reg1Bit6:
                sr1 = await self.read_status_reg_1()
                sr1 = update(sr1, 6)
                await self.write_status_reg_1(sr1)
            case unsupported:
                raise NotImplementedError(f"quad enablement {unsupported} not implemented yet")

    async def erase_data_all(self):
        """Erase all data.

        Implemented using :data:`Opcode.EraseChip <glasgow.arch.qspi.nor.Opcode.EraseChip>`.

        .. warning::

            This command can take a very long time (on the order of minutes) and does not read back
            data to verify success.

        .. tip::

            If the memory size is known (see :data:`memory_size`), prefer using :meth:`erase_data`
            with a range that covers the entire data region, which will report progress and verify
            that the data was successfully erased.
        """
        self._log("erase data all")
        await self.write_enable()
        await self.qspi.execute_cmd(self.cmds[nor.Command.EraseDataAll])
        await self.poll_busy()

    async def erase_data(self, address: int, length: int):
        """Erase data and verify success.

        Implemented using one of:

        * :data:`Command.EraseData4K <glasgow.arch.qspi.nor.Command.EraseData4K>`
        * :data:`Command.EraseData32K <glasgow.arch.qspi.nor.Command.EraseData32K>`
        * :data:`Command.EraseData64K <glasgow.arch.qspi.nor.Command.EraseData64K>`

        Erases memory range specified by :py:`address` and :py:`length`.

        Raises
        ------
        ValueError
            If either :py:`address` or :py:`length` is not divisible by the erase size of one of
            the available erase commands.
        Memory25QError
            If no erase commands are configured.
        Memory25QVerifyError
            If readback of erased data fails verification.
        """
        min_erase_size = self.cmds.min_erase_size
        if min_erase_size is None:
            raise Memory25QError("no erase commands configured")
        if address & (min_erase_size - 1) != 0:
            raise ValueError(
                f"address {address:#x} is not aligned to erase size {min_erase_size}")
        if length & (min_erase_size - 1) != 0:
            raise ValueError(
                f"length {length:#x} is not aligned to erase size {min_erase_size}")
        with Progress(total=length, action="erasing", item="B", scale=1024) as progress:
            while length > 0:
                # Pick the biggest erase size that can be used to erase the beginning of
                # the remaining un-erased area. Bigger erase sizes generally result in faster
                # erasing, though the relationship is seemingly not linear or universal.
                erase_size = max(
                    erase_size for erase_size in nor.Command.all_erase_sizes()
                    if (address & (erase_size - 1) == 0 and erase_size <= length and
                        nor.Command.erase_for_size(erase_size) in self.cmds)
                )
                self._log("erase data addr=%08x size=%dK", address, erase_size // 1024)
                await self._execute_data_operation_prologue(address)
                await self.qspi.execute_cmd( # don't use write_enable() to reduce USB roundtrips
                    self.cmds[nor.Command.WriteEnable])
                await self.qspi.execute_cmd(
                    self.cmds[nor.Command.erase_for_size(erase_size)], address=address)
                await self.poll_busy()
                # Verify that the data was erased. Some devices will report success during polling
                # but not actually change the contents of protected regions.
                self._log("verify data %s addr=%08x size=%dK",
                    self._mode(nor.Command.ReadData), address, erase_size // 1024)
                await self._execute_data_operation_prologue(address)
                erased_data = await self.qspi.execute_read(self.cmds[nor.Command.ReadData],
                    address=address, length=erase_size)
                if not re.match(rb"^\xff*$", erased_data):
                    raise Memory25QVerifyError(
                        f"failed to erase {erase_size // 1024}KiB at {address:#x}")
                # Advance to the next area.
                address += erase_size
                length  -= erase_size
                progress.advance(erase_size)

    async def program_data(self, address: int, data: bytes | bytearray | memoryview):
        """Program data and verify success.

        Implemented using :data:`Command.ProgramData <glasgow.arch.qspi.nor.Command.ProgramData>`.

        Programs :py:`data` to memory range starting at :py:`address`. The memory range must have
        been erased (using :meth:`erase_data` or otherwise), otherwise the resulting contents will
        become a logical AND of existing data and written data, and will fail verification.

        Raises
        ------
        Memory25QError
            If no program commands are available, or page size is not configured.
        Memory25QVerifyError
            If readback of programmed data fails verification.
        """
        if nor.Command.ProgramData not in self.cmds:
            raise Memory25QError("no program commands configured")
        page_size = self.cmds[nor.Command.ProgramData].data_octets
        if page_size is None:
            raise Memory25QError("page size not configured")
        with Progress(total=len(data), action="programming", item="B", scale=1024) as progress:
            offset = 0
            while offset < len(data):
                # Program data, taking care not to cross page boundaries.
                chunk_size = page_size - (address & (page_size - 1))
                program_data = data[offset:offset + chunk_size]
                if re.match(rb"^\xff*$", program_data):
                    self._log("program data addr=%08x data=%s (skipped)",
                        address, dump_hex(program_data))
                    # Since the precondition is that the area must've been erased, we do not need
                    # to program runs of all-ones. This can save quite a bit of waiting. Result is
                    # still verified later.
                else:
                    self._log("program data %s addr=%08x data=%s",
                        self._mode(nor.Command.ProgramData), address, dump_hex(program_data))
                    await self._execute_data_operation_prologue(address)
                    await self.qspi.execute_cmd( # don't use write_enable() to reduce USB roundtrips
                        self.cmds[nor.Command.WriteEnable])
                    await self.qspi.execute_write(self.cmds[nor.Command.ProgramData],
                        address=address, data=program_data)
                    await self.poll_busy()
                # Verify programmed data.
                self._log("verify data %s addr=%08x data=%s",
                    self._mode(nor.Command.ReadData), address, dump_hex(program_data))
                await self._execute_data_operation_prologue(address)
                verify_data = await self.qspi.execute_read(self.cmds[nor.Command.ReadData],
                    address=address, length=len(program_data))
                if verify_data != program_data:
                    raise Memory25QVerifyError(f"failed to program {chunk_size} B at {address:#x}")
                # Advance.
                address += chunk_size
                offset  += chunk_size
                progress.advance(chunk_size)

    async def write_data(self, address: int, data: bytes | bytearray | memoryview):
        """Write data and verify success.

        Implemented using :meth:`erase_data` and :meth:`program_data`.

        Writes :py:`data` at :py:`address` without any alignment constraints. If the written region
        is not already appropriately aligned, performs a read-modify-write cycle; in any case, data
        is first erased and then programmed.

        Raises
        ------
        Memory25QError
            If no erase or program commands are configured, or page size is not configured.
        Memory25QVerifyError
            If readback of erased or programmed data fails verification.
        """
        min_erase_size = self.cmds.min_erase_size
        if min_erase_size is None:
            raise Memory25QError("no erase commands configured")
        if nor.Command.ProgramData not in self.cmds: # check this _before_ erasing
            raise Memory25QError("no program command configured")
        if self.cmds[nor.Command.ProgramData].data_octets is None:
            raise Memory25QError("page size not configured")
        self._log("write data addr=%08x data=%s", address, dump_hex(data))
        aligned_address = address & ~(min_erase_size - 1)
        leader = b""
        if (leader_size := address & (min_erase_size - 1)):
            await self._execute_data_operation_prologue(aligned_address)
            leader = bytes(await self.qspi.execute_read(self.cmds[nor.Command.ReadData],
                address=aligned_address, length=leader_size))
        trailer = b""
        if (trailer_size := min_erase_size - (address + len(data) & (min_erase_size - 1))):
            if trailer_size != min_erase_size:
                await self._execute_data_operation_prologue(address + len(data))
                trailer = bytes(await self.qspi.execute_read(self.cmds[nor.Command.ReadData],
                    address=address + len(data), length=trailer_size))
        aligned_data = leader + data + trailer
        assert len(aligned_data) & (min_erase_size - 1) == 0
        await self.erase_data(aligned_address, len(aligned_data))
        await self.program_data(aligned_address, aligned_data)


class Memory25QApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "read and write 25-series (Q)SPI NOR Flash memories"
    description = """
    Identify, read, erase, or program memories compatible with 25-series SPI/dual-SPI/quad-SPI
    NOR Flash memory, such as Microchip 25C320, Winbond W25Q32JV, Micron MT25QU256ABA,
    Macronix MX25L6445E, ISSI IS25LP128, or hundreds of other memories that typically have ``25x``
    (where "x" is a letter, usually ``C``, ``F``, or ``Q``) in their part number. Note that ``25N``
    typically designates (Q)SPI NAND Flash memory, which is completely incompatible.

    The pinout of a typical 25-series IC is as follows:

    ::

                16-pin                     8-pin
        IO3/HOLD# @ * SCK               CS# @ * VCC
              VCC * * IO0/COPI     IO1/CIPO * * IO3/HOLD#
              N/C * * N/C           IO2/WP# * * SCK
              N/C * * N/C               GND * * IO0/COPI
              N/C * * N/C
              N/C * * N/C
              CS# * * GND
         IO1/CIPO * * IO2/WP#

    This applet supports ordinary SPI mode, as well as dual-SPI and quad-SPI. When quad-SPI mode
    is not in use, the ``WP#`` and ``HOLD#`` pins are pulled high; these must not be left floating
    as the memories do not typically include internal pull-ups. These faster modes are not enabled
    by default because of the potential for bus contention and higher severity of crosstalk; use
    the options ``--dual-spi`` and ``--quad-spi`` to enable their use (when described in SFDP).

    It is also possible to flash 25-series flash chips using the `spi-flashrom` applet, which
    requires a third-party tool `flashrom`. The advantage of using the `flashrom` applet is that
    flashrom offers compatibility with a wider variety of devices, some of which may not be
    supported by the `memory-25q` applet.
    """
    required_revision = QSPIControllerApplet.required_revision
    m25q_iface: Memory25QInterface

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "cs",  required=True, default=True)
        access.add_pins_argument(parser, "sck", required=True, default=True)
        access.add_pins_argument(parser, "io",  required=True, default=True, width=4,
            help="bind the applet I/O lines 'copi', 'cipo', 'wp', 'hold' to PINS")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.m25q_iface = Memory25QInterface(self.logger, self.assembly,
                cs=args.cs, sck=args.sck, io=args.io)

    @classmethod
    def add_setup_arguments(cls, parser):
        # Most SPI flashes should work at 12 MHz. Higher values work but crosstalk in jumper
        # cables puts an unknown maximum limit on the SCK frequency, so be conservative here.
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=12000,
            help="set SCK frequency to FREQ kHz (default: %(default)s)")

    async def setup(self, args):
        await self.m25q_iface.qspi.clock.set_frequency(args.frequency * 1000)

    @classmethod
    def __add_initialize_arguments(cls, parser):
        def page_size(arg):
            size = int(arg, 0)
            if size <= 0 or (size & (size - 1)):
                raise argparse.ArgumentTypeError(f"{size} is not a power of 2")
            else:
                return size
        def opcode(arg):
            if m := re.match(r"^(?:0x)?([0-9A-Fa-f]{2})h?$", arg):
                return int(m[1], 16)
            else:
                raise argparse.ArgumentTypeError(f"invalid opcode {arg!r}")

        # Dual-SPI mostly just works (it uses the same COPI/CIPO pins that single-SPI uses), but
        # having two pins toggling simultaneously *dramatically* increases the effect of crosstalk
        # in a background of poor signal integrity (e.g. a SOIC clip plus the official harness).
        # Quad-SPI requires two additional pins (and a complicated enable/disable dance), which
        # means it can't be used without an explicit opt-in regardless of SI considerations.
        # Note that reducing the frequency will do nothing because the characteristic property
        # of the aggressor signal is high dV/dt. Increasing the output impedance would work, but
        # this isn't standardized until JESD216C.
        parser.add_argument(
            "--dual-spi", dest="enable_dual", default=False, action="store_true",
            help="use dual-SPI modes if present in SFDP")
        parser.add_argument(
            "--quad-spi", dest="enable_quad", default=False, action="store_true",
            help="use quad-SPI modes if present in SFDP")

        # Most flashes use 3 address bytes or use some kind of multiplexing scheme that resets
        # to effectively a 3 address byte mode. The 4-byte-only ones, hopefully, all have SFDP...
        # It would be pretty annoying to specify this parameter whenever reading an old flash.
        parser.add_argument(
            "-A", "--address-bytes", metavar="WIDTH", type=int, choices=(3, 4), default=None,
            help="use WIDTH address bytes for data region (choices: 3, 4, default: 3)")
        parser.add_argument(
            "-P", "--page-size", metavar="SIZE", type=page_size,
            help="do not cross multiple-of-SIZE boundaries when programming")
        parser.add_argument(
            "--opcode-erase-4k", metavar="OPCODE", type=opcode,
            help="opcode for erasing a 4 KiB region")
        parser.add_argument(
            "--opcode-erase-32k", metavar="OPCODE", type=opcode,
            help="opcode for erasing a 32 KiB region")
        parser.add_argument(
            "--opcode-erase-64k", metavar="OPCODE", type=opcode,
            help="opcode for erasing a 64 KiB region")

    async def __initialize(self, args):
        # This function initializes the full command set, either based on SFDP information or
        # on explicitly provided
        await self.m25q_iface.initialize(
            enable_dual=args.enable_dual, enable_quad=args.enable_quad)
        if self.m25q_iface.sfdp_used:
            assert (params := self.m25q_iface.jedec_params) is not None
            # If SFDP data exists, it is assumed correct and the explicitly passed CLI args are
            # checked for compatibility. (In the very rare case that it is not actually correct,
            # please use the REPL and `m25q_iface.cmds.use_explicit` instead of command line args.)
            if args.address_bytes is not None and {args.address_bytes} != params.address_byte_count:
                self.logger.warning(f"ignoring argument --address-bytes {args.address_bytes} "
                                    f"that does not match SFDP value")
            if args.page_size is not None and args.page_size != params.page_size:
                if ((params.exact_page_size and args.page_size != params.page_size) or
                        (not params.exact_page_size and args.page_size < params.page_size)):
                    self.logger.warning(f"ignoring argument --page-size {args.page_size} "
                                        f"that does not match SFDP value")
                else:
                    # Allow refining the SFDP page size; this can greatly speed up programming.
                    self.m25q_iface.cmds[nor.Command.ProgramData] = \
                        dataclasses.replace(self.m25q_iface.cmds[nor.Command.ProgramData],
                            data_octets=args.page_size)
            if (args.opcode_erase_4k is not None and
                    args.opcode_erase_4k != params.erase_sizes.get(4096)):
                self.logger.warning(
                    f"ignoring argument --opcode-erase-4k {args.opcode_erase_4k:02X}h "
                    f"that does not match SFDP value")
            if (args.opcode_erase_32k is not None and
                    args.opcode_erase_32k != params.erase_sizes.get(32768)):
                self.logger.warning(
                    f"ignoring argument --opcode-erase-32k {args.opcode_erase_32k:02X}h "
                    f"that does not match SFDP value")
            if (args.opcode_erase_64k is not None and
                    args.opcode_erase_64k != params.erase_sizes.get(65536)):
                self.logger.warning(
                    f"ignoring argument --opcode-erase-64k {args.opcode_erase_64k:02X}h "
                    f"that does not match SFDP value")
        else:
            # If there is no SFDP data or it is invalid, use the CLI args explicitly.
            # All parameters but `address_bytes` can be `None` and will fail later if needed.
            if (address_bytes := args.address_bytes) is None:
                address_bytes = 3
                self.logger.warning("assuming --address-bytes 3 by default")
            self.m25q_iface.cmds.use_explicit(
                address_bytes=address_bytes,
                page_size=args.page_size,
                opcode_erase_4k=args.opcode_erase_4k,
                opcode_erase_32k=args.opcode_erase_32k,
                opcode_erase_64k=args.opcode_erase_64k,
            )
        read_mode = self.m25q_iface.cmds[nor.Command.ReadData].mode
        if args.enable_quad:
            if read_mode.uses_quad:
                await self.m25q_iface.set_quad_enabled()
            else:
                self.logger.warning(
                    f"argument --quad-spi specified, but fastest read mode is {read_mode}")
        if args.enable_dual and not (read_mode.uses_dual or read_mode.uses_quad):
            self.logger.warning(
                f"argument --dual-spi specified, but fastest read mode is {read_mode}")

    @classmethod
    def add_run_arguments(cls, parser):
        def address(arg):
            return int(arg, 0)
        def length(arg):
            return int(arg, 0)
        def hex_bytes(arg):
            return bytes.fromhex(arg)
        def bp_bits(arg):
            if re.match(r"^[01]{1,4}$", arg):
                return int(arg, 2)
            else:
                raise argparse.ArgumentTypeError(f"invalid BP bits {arg!r}")

        cls.__add_initialize_arguments(parser)

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_identify = p_operation.add_parser(
            "identify", help="identify memory using JEDEC ID and SFDP data", description="""
        Identify memory by its JEDEC ID and (if available) Serial Flash Discoverable Parameters.
        """)
        p_identify.add_argument(
            "--annotate-raw-sfdp", default=False, action="store_true",
            help="annotate known raw SFDP DWORDs with fields")

        def add_addr_argument(parser):
            parser.add_argument(
                "address", metavar="ADDRESS", type=address,
                help="start with byte at ADDRESS")

        def add_len_argument(parser):
            parser.add_argument(
                "length", metavar="LENGTH", type=length,
                help="continue for LENGTH bytes")

        def add_dst_argument(parser):
            parser.add_argument(
                "-f", "--file", metavar="FILENAME", type=argparse.FileType("wb"),
                help="write memory contents to FILENAME")

        def add_src_argument(parser):
            group = parser.add_mutually_exclusive_group(required=True)
            group.add_argument(
                "-d", "--data", metavar="DATA", type=hex_bytes,
                help="use hex bytes DATA as memory contents")
            group.add_argument(
                "-f", "--file", metavar="FILENAME", type=argparse.FileType("rb"),
                help="use data from FILENAME as memory contents")

        p_read = p_operation.add_parser(
            "read", help="read memory range", description="""
        Read memory range using the fastest available read command.
        """)
        add_addr_argument(p_read)
        add_len_argument(p_read)
        add_dst_argument(p_read)

        p_verify = p_operation.add_parser(
            "verify", help="compare memory range", description="""
        Read memory range using the fastest available read command, and compare with given data.
        """)
        add_addr_argument(p_verify)
        add_src_argument(p_verify)

        p_erase = p_operation.add_parser(
            "erase", help="erase memory range", description="""
        Erase memory range. Start and end of specified range must be aligned on erase size
        boundaries.
        """)
        add_addr_argument(p_erase)
        add_len_argument(p_erase)

        p_erase_all = p_operation.add_parser(
            "erase-all", help="erase all memory", description="""
        Erase memory range covering the entire chip.
        """)

        p_write = p_operation.add_parser(
            "write", help="write memory range", description="""
        Write memory range using a read-modify-write sequence. Start and end of specified
        range do not need to be aligned on erase size boundaries.
        """)
        add_addr_argument(p_write)
        add_src_argument(p_write)

        p_protect = p_operation.add_parser(
            "protect", help="read or write block protection bits", description="""
        Read or write Block Protection (BP) bits. The exact size and location of the protected area
        for a specific bit combination can only be determined from the device datasheet.

        Setting all BP bits to zero may be necessary to execute the `erase-all` command or to
        resolve erase/program failures.
        """)
        p_protect.add_argument(
            "bp_bits", metavar="BITMASK", type=bp_bits, nargs="?",
            help="write BITMASK to BP bits (e.g. 0000 to allow all, 1111 to protect all)"
        )

    async def run(self, args):
        await self.__initialize(args)

        jedec_mfg_id, device_id = await self.m25q_iface.jedec_id()
        if jedec_mfg_id in (0x00, 0xff):
            raise Memory25QError(f"invalid JEDEC ID {jedec_mfg_id:#04x}; check connectivity")

        if args.operation in (None, "identify"):
            jedec_mfg_name = jedec_mfg_name_from_bytes([jedec_mfg_id]) or "unknown"
            self.logger.info("JEDEC identification:       %s (%#04x) device %#06x",
                jedec_mfg_name, jedec_mfg_id, device_id)
            if self.m25q_iface.sfdp is not None:
                self.logger.info(f"{self.m25q_iface.sfdp} descriptor:")
                for line in self.m25q_iface.sfdp.description():
                    self.logger.info(f"  {line}")
            else:
                # Second byte of device_id typically appears to be a power-of-2 exponent for
                # the number of bytes. None of the datasheets I've seen explicitly guarantee
                # this algebraic relation, but it seems useful enough to display for devices
                # without more accurately known capacity.
                memory_size_guess = 1 << (device_id & 0xff)
                if memory_size_guess > 1048576:
                    self.logger.info(f"inexact memory size guess:  {memory_size_guess/1048576} MiB")
                else:
                    self.logger.info(f"inexact memory size guess:  {memory_size_guess/1024} KiB")

        if args.operation in (None, "identify", "erase", "erase-all", "write", "protect"):
            sr1 = await self.m25q_iface.read_status_reg_1()
            if (bp_bits := sr1 & nor.StatusReg1.BPALL) != 0:
                self.logger.warning(
                    f"current block protect bits: {bp_bits >> 2:04b} "
                    f"(some blocks protected)")
            elif args.operation in (None, "identify", "protect"):
                self.logger.info(
                    f"current block protect bits: {bp_bits >> 2:04b} "
                    f"(all blocks writable)")

        if args.operation is None:
            pass # done above

        elif args.operation == "identify":
            if args.annotate_raw_sfdp and self.m25q_iface.jedec_params:
                self.logger.info("decoded SFDP DWORDs:")
                for index, (dword, fields) in enumerate(self.m25q_iface.jedec_params.raw_dwords()):
                    self.logger.info(f"  [{index}] = {dword:08X}")
                    for field in fields:
                        self.logger.info(f"    {field}")
            elif args.annotate_raw_sfdp:
                self.logger.error("decoded SFDP DWORDs unavailable")

        elif args.operation == "read":
            data = await self.m25q_iface.read_data(args.address, args.length)
            if args.file is not None:
                args.file.write(data)
            else:
                print(data.hex())

        elif args.operation == "verify":
            if args.file is not None:
                data_golden = args.file.read()
            else:
                data_golden = args.data
            data_actual = await self.m25q_iface.read_data(args.address, len(data_golden))
            if data_golden == data_actual:
                self.logger.info("verify PASS")
            else:
                self.logger.error("verify FAIL")
                exit(1)

        elif args.operation == "erase":
            try:
                await self.m25q_iface.erase_data(args.address, args.length)
            except ValueError as err: # unaligned address or length
                raise Memory25QError(str(err))

        elif args.operation == "erase-all":
            if (memory_size := self.m25q_iface.memory_size) is not None:
                # If available from SFDP, erase block-by-block so that progress is reported
                # incrementally. We use the biggest possible erase size for each address, which
                # generally seems to be as fast as erasing the entire chip.
                await self.m25q_iface.erase_data(0, memory_size)
            else:
                # If not, erase the entire chip, but this could take more than 60s with no
                # progress reporting.
                self.logger.warning("this command may take a long time")
                await self.m25q_iface.erase_data_all()

        elif args.operation == "write":
            if args.file is not None:
                data = args.file.read()
            else:
                data = args.data
            await self.m25q_iface.write_data(args.address, data)

        elif args.operation == "protect":
            if args.bp_bits is None:
                pass # done above

            else:
                sr1 = await self.m25q_iface.read_status_reg_1()
                sr1 &= ~nor.StatusReg1.BPALL
                sr1 |= (args.bp_bits << 2)
                await self.m25q_iface.write_status_reg_1(sr1)

                sr1 = await self.m25q_iface.read_status_reg_1()
                if (bp_bits := sr1 & nor.StatusReg1.BPALL) != 0:
                    self.logger.info(
                        f"updated block protect bits: {bp_bits >> 2:04b} "
                        f"(some blocks protected)")
                else:
                    self.logger.info(
                        f"updated block protect bits: {bp_bits >> 2:04b} "
                        f"(all blocks writable)")

        else:
            assert False

    @classmethod
    def add_repl_arguments(cls, parser):
        cls.__add_initialize_arguments(parser)

    async def repl(self, args):
        # Prepopulate command set to make using the REPL more convenient.
        await self.__initialize(args)

        await super().repl(args)

    @classmethod
    def tests(cls):
        from . import test
        return test.Memory25QAppletTestCase
