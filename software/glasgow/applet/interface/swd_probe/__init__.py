# Ref: Arm Debug Interface Architecture Specification ADIv5.0 to ADIv5.2, Issue E
# Accession: G00097
# Document Number: IHI0031E

# The wire protocol of this applet is incorporated by reference into the protocol of the `probe-rs`
# applet. Be careful when making changes to it; any breaking changes must update `probe-rs` as
# instructed in the comment there.

from typing import Optional, AsyncIterator
import sys
import argparse
import logging
import struct

from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io, cdc
from amaranth.lib.wiring import In, Out

from glasgow.support.bits import bits
from glasgow.arch.arm.swj import *
from glasgow.arch.arm.dap import *
from glasgow.database.jedec import jedec_mfg_name_from_bank_num
from glasgow.gateware import swd
from glasgow.abstract import AbstractAssembly, GlasgowPin, ClockDivisor
from glasgow.applet import GlasgowAppletError, GlasgowAppletV2


__all__ = ["SWDProbeException", "SWDProbeComponent", "SWDProbeInterface"]


class SWDProbeException(GlasgowAppletError):
    class Kind(enum.Enum):
        Error   = "error"   # parity error or invalid acknowledgement
        Fault   = "fault"   # target returned a FAULT response
        Timeout = "timeout" # too many retries for a WAIT response
        Other   = "other"   # unspecified

    def __init__(self, message, *, kind: Kind = Kind.Other):
        self.kind = kind
        super().__init__(message)


class SWDCommand(data.Struct):
    arg: data.UnionLayout({
        "transfer": data.StructLayout({
            "ap_ndp":   1,
            "r_nw":     1,
            "addr23":   2,
        }),
        "sequence": data.StructLayout({
            "len":      5, # encoding 0 means 32 bits long
        }),
    })
    cmd: swd.Command
    _:   2


class SWDResponse(data.Struct):
    ack: swd.Ack
    _1:  1
    rsp: swd.Response
    _2:  2


class SWDProbeComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))

    divisor: In(16)
    timeout: In(16, init=~0)

    def __init__(self, ports, *, offset=None):
        self._ports  = ports
        self._offset = offset

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.ctrl = ctrl = swd.Controller(self._ports,
            # Offset sampling by ~10 ns to compensate for 10..15 ns of roundtrip delay caused by
            # the level shifters (5 ns each) and FPGA clock-to-out (5 ns).
            offset=1 if self._offset is None else self._offset)
        m.d.comb += ctrl.divisor.eq(self.divisor)
        m.d.comb += ctrl.timeout.eq(self.timeout)

        with m.FSM(name="i_fsm"):
            with m.State("Command"):
                i_command = SWDCommand(self.i_stream.payload)
                m.d.sync += [
                    ctrl.i_stream.p.len.eq(i_command.arg.sequence.len),
                    ctrl.i_stream.p.hdr.ap_ndp.eq(i_command.arg.transfer.ap_ndp),
                    ctrl.i_stream.p.hdr.r_nw.eq(i_command.arg.transfer.r_nw),
                    ctrl.i_stream.p.hdr.addr[2:4].eq(i_command.arg.transfer.addr23),
                    ctrl.i_stream.p.cmd.eq(i_command.cmd),
                ]
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    with m.If(i_command.cmd == swd.Command.Sequence):
                        m.next = "Data"
                    with m.Elif((i_command.cmd == swd.Command.Transfer) &
                            (i_command.arg.transfer.r_nw == 0)):
                        m.next = "Data"
                    with m.Else():
                        m.next = "Execute"

            with m.State("Data"):
                i_count = Signal(range(4))
                m.d.sync += ctrl.i_stream.p.data.word_select(i_count, 8).eq(self.i_stream.payload)
                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    m.d.sync += i_count.eq(i_count + 1)
                    with m.If(i_count == 3):
                        m.next = "Execute"

            with m.State("Execute"):
                m.d.comb += ctrl.i_stream.valid.eq(1)
                with m.If(ctrl.i_stream.ready):
                    m.next = "Command"

        with m.FSM(name="o_fsm"):
            with m.State("Response"):
                o_response = Signal(SWDResponse)
                m.d.comb += [
                    o_response.ack.eq(ctrl.o_stream.p.ack),
                    o_response.rsp.eq(ctrl.o_stream.p.rsp),
                    self.o_stream.payload.eq(o_response),
                    self.o_stream.valid.eq(ctrl.o_stream.valid),
                ]
                with m.If(ctrl.o_stream.valid & self.o_stream.ready):
                    with m.If(o_response.rsp == swd.Response.Data):
                        m.next = "Data"
                    with m.Else():
                        m.d.comb += ctrl.o_stream.ready.eq(1)

            with m.State("Data"):
                o_count = Signal(range(4))
                m.d.comb += [
                    self.o_stream.payload.eq(ctrl.o_stream.p.data.word_select(o_count, 8)),
                    self.o_stream.valid.eq(1),
                ]
                with m.If(self.o_stream.ready):
                    m.d.sync += o_count.eq(o_count + 1)
                    with m.If(o_count == 3):
                        m.d.comb += ctrl.o_stream.ready.eq(1)
                        m.next = "Response"

        return m


class SWDProbeInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 swclk: GlasgowPin, swdio: GlasgowPin):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

        ports = assembly.add_port_group(swclk=swclk, swdio=swdio)
        component = assembly.add_submodule(SWDProbeComponent(ports))
        self._pipe = assembly.add_inout_pipe(component.o_stream, component.i_stream)
        self._clock = assembly.add_clock_divisor(component.divisor,
            ref_period=assembly.sys_clk_period, name="swclk")
        self._timeout = assembly.add_rw_register(component.timeout)

        self._select = None

    def _log(self, message, *args):
        self._logger.log(self._level, "SWD: " + message, *args)

    @property
    def clock(self) -> ClockDivisor:
        """SWCLK clock divisor."""
        return self._clock

    async def _send_command(self, **kwargs):
        await self._pipe.send([SWDCommand.const(kwargs).as_value().value])

    async def _send_sequence(self, sequence: bits):
        for start in range(0, len(sequence), 32):
            chunk = sequence[start:start + 32]
            await self._send_command(cmd=swd.Command.Sequence,
                arg={"sequence": {"len": len(chunk)}})
            await self._pipe.send(struct.pack("<L", chunk.to_int()))
        await self._pipe.flush()

    async def _send_transfer(self, **kwargs):
        await self._send_command(cmd=swd.Command.Transfer,
            arg={"transfer": kwargs})

    async def _recv_ack(self):
        await self._pipe.flush()
        response = data.Const(SWDResponse, (await self._pipe.recv(1))[0])
        if response.rsp == swd.Response.Error:
            raise SWDProbeException("communication error", kind=SWDProbeException.Kind.Error)
        if response.ack == swd.Ack.FAULT:
            raise SWDProbeException("transaction fault", kind=SWDProbeException.Kind.Fault)
        if response.ack == swd.Ack.WAIT:
            raise SWDProbeException("wait timeout", kind=SWDProbeException.Kind.Timeout)
        assert response.ack == swd.Ack.OK

    async def line_reset(self):
        """Perform a line reset sequence."""
        self._log("line-reset")
        await self._send_sequence(SWJ_line_reset_seq)
        self._select = None

    async def jtag_to_swd_v1(self):
        """Perform a DPv1 JTAG-to-SWD switch sequence."""
        self._log("jtag-to-swd v1")
        await self._send_sequence(SWJ_jtag_to_swd_switch_seq)

    async def jtag_to_swd_v2(self):
        """Perform a DPv2 JTAG-to-SWD switch sequence.

        This sequence consists of a JTAG-to-dormant, Selection Alert, and dormant-to-SWD
        sub-sequences.
        """
        self._log("jtag-to-swd v2")
        await self._send_sequence(SWJ_jtag_to_dormant_switch_seq)
        await self._send_sequence(SWJ_selection_alert_seq)
        await self._send_sequence(SWJ_dormant_to_swd_switch_seq)

    async def _raw_read(self, *, ap_ndp: bool, addr: int) -> int:
        assert addr in range(0, 0x10, 4)
        await self._send_transfer(ap_ndp=ap_ndp, r_nw=1, addr23=addr >> 2)
        try:
            await self._recv_ack()
            data, = struct.unpack("<L", await self._pipe.recv(4))
            self._log(f"rd {'ap' if ap_ndp else 'dp'} addr={addr:#x} data={data:#010x}")
        except SWDProbeException as exn:
            self._log(f"rd {'ap' if ap_ndp else 'dp'} addr={addr:#x} {exn.kind.value}")
            raise
        return data

    async def _raw_write(self, *, ap_ndp: bool, addr: int, data: int):
        assert addr in range(0, 0x10, 4)
        await self._send_transfer(ap_ndp=ap_ndp, r_nw=0, addr23=addr >> 2)
        await self._pipe.send(struct.pack("<L", data))
        try:
            await self._recv_ack()
            self._log(f"wr {'ap' if ap_ndp else 'dp'} addr={addr:#x} data={data:#010x}")
        except SWDProbeException as exn:
            self._log(f"wr {'ap' if ap_ndp else 'dp'} addr={addr:#x} {exn.kind.value}")
            raise

    async def _update_select(self, **kwargs):
        if self._select is None:
            select = DP_SELECT(**kwargs)
        else:
            select = self._select.copy()
            for field, value in kwargs.items():
                setattr(select, field, value)
        if select != self._select:
            self._log(f"select {select.bits_repr()}")
            await self._raw_write(ap_ndp=0, addr=DP_SELECT_addr, data=select.to_int())
            self._select = select

    async def _select_dp_addr(self, addr: int):
        if addr & 0xf == 0x4: # banked
            await self._update_select(DPBANKSEL=addr >> 4)

    async def dp_read(self, reg: int) -> int:
        """Read from DP register :py:`reg`, switching the DP bank if necessary.

        Raises
        ------
        SWDProbeException
            On communication error.
        """
        await self._select_dp_addr(reg)
        return await self._raw_read(ap_ndp=0, addr=reg & 0xf)

    async def dp_write(self, reg: int, data: int):
        """Write :py:`data` to DP register :py:`reg`, switching the DP bank if necessary.

        Raises
        ------
        SWDProbeException
            On communication error.
        """
        await self._select_dp_addr(reg)
        return await self._raw_write(ap_ndp=0, addr=reg & 0xf, data=data)

    async def _select_ap_addr(self, ap: int, reg: int):
        await self._update_select(APSEL=ap, APBANKSEL=reg >> 4)

    async def ap_read(self, ap: int, reg: int) -> int:
        """Read from AP :py:`ap` register :py:`reg`, switching the AP and AP bank if necessary.

        Raises
        ------
        SWDProbeException
            On communication error.
        """
        await self._select_ap_addr(ap, reg)
        await self._raw_read(ap_ndp=1, addr=reg & 0xf)
        return await self.dp_read(DP_RDBUFF_addr)

    async def ap_read_block(self, ap: int, reg: int, count: int) -> list[int]:
        """Read from AP :py:`ap` register :py:`reg` :py:`count` times, switching the AP and AP bank
        if necessary.

        The AP reads are pipelined, making this method significantly faster than calling
        :meth:`ap_read` :py:`count` times.

        Raises
        ------
        SWDProbeException
            On communication error.
        """
        assert count >= 1
        await self._select_ap_addr(ap, reg)
        await self._raw_read(ap_ndp=1, addr=reg & 0xf)
        results = []
        for _ in range(count - 1):
            results.append(await self._raw_read(ap_ndp=1, addr=reg & 0xf))
        results.append(await self.dp_read(DP_RDBUFF_addr))
        return results

    async def ap_write(self, ap: int, reg: int, data: int):
        """Write :py:`data` to AP :py:`ap` register :py:`reg`, switching the AP and AP bank if
        necessary.

        Raises
        ------
        SWDProbeException
            On communication error.
        """
        await self._select_ap_addr(ap, reg)
        return await self._raw_write(ap_ndp=1, addr=reg & 0xf, data=data)

    async def initialize(self) -> DP_DPIDR:
        """Initialize the SW-DP or SWJ-DP.

        The initialization process is:

        1. Perform a DPv2 JTAG-to-SWD switch sequence, as in :meth:`jtag_to_swd_v2`.
        2. Perform a DPv1 JTAG-to-SWD switch sequence, as in :meth:`jtag_to_swd_v1`.
        3. Perform a line reset and read ``DPIDR`` to start SWD communication.
        4. Write ``DP_ABORT`` to clear all errors.
        5. Write ``CTRL_STAT`` to request debug power-up.
        6. Read ``CTRL_STAT`` to ensure acknowledge of debug power-up.

        Raises
        ------
        SWDProbeException
            On communication error, or if debug power-up request isn't acknowledged.
        """
        await self.jtag_to_swd_v2()
        await self.jtag_to_swd_v1()
        await self.line_reset()
        dpidr = DP_DPIDR.from_int(await self.dp_read(reg=DP_DPIDR_addr))
        await self.dp_write(reg=DP_ABORT_addr,
            data=DP_ABORT(STKCMPCLR=1, STKERRCLR=1, WDERRCLR=1, ORUNERRCLR=1).to_int())
        await self.dp_write(reg=DP_CTRL_STAT_addr,
            data=DP_CTRL_STAT(CDBGPWRUPREQ=1).to_int())
        ctrl_stat = DP_CTRL_STAT.from_int(await self.dp_read(reg=DP_CTRL_STAT_addr))
        if not ctrl_stat.CDBGPWRUPACK:
            raise SWDProbeException("target failed to acknowledge debug power-up request")
        return dpidr

    async def iter_aps(self) -> AsyncIterator[tuple[int, AP_IDR]]:
        """Iterate available APs.

        Yields 2-tuples :py:`(ap, ap_idr)` where :py:`ap` is the AP index and :py:`ap_idr` is
        the value of the ``IDR`` register.

        Raises
        ------
        SWDProbeException
            On communication error.
        """
        for ap in range(0, 0x100):
            ap_idr = AP_IDR.from_int(await self.ap_read(ap, AP_IDR_addr))
            if ap_idr.to_int() == 0:
                break
            yield ap, ap_idr


class SWDProbeApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "access Arm microcontrollers via SWD"
    description = """
    At the moment, this applet does not include any high-level functionality. It only offers
    very low-level access to the target via the REPL or script interface.

    Use the `probe-rs` applet to debug and program Arm microcontrollers.
    """
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "swclk", required=True, default=True)
        access.add_pins_argument(parser, "swdio", required=True, default=True)

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            self.swd_iface = SWDProbeInterface(self.logger, self.assembly,
                swclk=args.swclk, swdio=args.swdio)

    @classmethod
    def add_setup_arguments(cls, parser):
        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=1000,
            help="set SWCLK frequency to FREQ kHz (default: %(default)s)")

    async def setup(self, args):
        await self.swd_iface.clock.set_frequency(args.frequency * 1000)

    @classmethod
    def add_run_arguments(cls, parser):
        def address(arg):
            value = int(arg, 0)
            if value & 0x3:
                raise argparse.ArgumentTypeError("address must be word-aligned")
            return value
        def length(arg):
            value = int(arg, 0)
            if value & 0x3:
                raise argparse.ArgumentTypeError("length must be word-aligned")
            return value

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_dump_memory = p_operation.add_parser(
            "dump-memory", help="read memory via a MEM-AP")
        p_dump_memory.add_argument(
            "address", metavar="ADDRESS", type=address,
            help="start at ADDRESS")
        p_dump_memory.add_argument(
            "length", metavar="LENGTH", type=length,
            help="dump LENGTH bytes")
        p_dump_memory.add_argument(
            "-f", "--file", metavar="FILENAME", type=argparse.FileType("wb"),
            help="dump contents to FILENAME")
        p_dump_memory.add_argument(
            "--ap", metavar="INDEX", default=0,
            help="access memory via MEM-AP #INDEX")

    @staticmethod
    def _show_progress(done, total):
        if sys.stdout.isatty():
            sys.stdout.write("\r\033[0K")
            if done < total:
                sys.stdout.write(f"{done}/{total} bytes done")
            sys.stdout.flush()

    async def run(self, args):
        dpidr = await self.swd_iface.initialize()
        self.logger.info("DP: %sDPv%d DPIDR=%#010x",
            "MIN" if dpidr.MIN else "", dpidr.VERSION, dpidr.to_int())
        mfg_name = jedec_mfg_name_from_bank_num(dpidr.DESIGNER >> 7, dpidr.DESIGNER & 0x7f)
        self.logger.info("  designer=%#05x (%s) partno=%#04x revision=%#03x",
            dpidr.DESIGNER, mfg_name or "unknown", dpidr.PARTNO, dpidr.REVISION)

        match args.operation:
            case None:
                async for ap, apidr in self.swd_iface.iter_aps():
                    ap_class = AP_IDR_CLASS(apidr.CLASS)
                    self.logger.info("  AP #%d: %s APIDR=%#010x", ap, ap_class, apidr.to_int())
                    mfg_name = jedec_mfg_name_from_bank_num(
                        apidr.DESIGNER >> 7, apidr.DESIGNER & 0x7f)
                    self.logger.info("    designer=%#05x (%s) revision=%#03x",
                        apidr.DESIGNER, mfg_name or "unknown", apidr.REVISION)
                    if ap_class == AP_IDR_CLASS.MEM_AP:
                        base = MEM_AP_BASE.from_int(
                            await self.swd_iface.ap_read(ap, MEM_AP_BASE_addr))
                        if base.P:
                            self.logger.info("    baseaddr=%#010x", base.BASEADDR << 16)

            case "dump-memory":
                ap_cfg = MEM_AP_CFG.from_int(await self.swd_iface.ap_read(args.ap, MEM_AP_CFG_addr))

                data = []
                addr = args.address
                last = args.address + args.length
                await self.swd_iface.ap_write(args.ap, MEM_AP_CSW_addr,
                    MEM_AP_CSW(AddrInc=1, Size=2).to_int())
                while addr < last:
                    await self.swd_iface.ap_write(args.ap, MEM_AP_TAR_addr, addr)
                    block = await self.swd_iface.ap_read_block(args.ap, MEM_AP_DRW_addr,
                        min(0x100, (last - addr) >> 2))
                    data += block
                    addr += len(block) << 2
                    self._show_progress(len(data) << 2, args.length)

                image = b"".join(word.to_bytes(4, "big" if ap_cfg.BE else "little")
                                 for word in data)
                if args.file:
                    args.file.write(image)
                else:
                    print(image.hex())

    @classmethod
    def tests(cls):
        from . import test
        return test.SWDProbeAppletTestCase
