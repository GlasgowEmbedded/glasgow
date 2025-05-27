# The protocol implementation in this applet must be synchronized with the protocol implementation
# in `probe-rs <https://probe.rs/>`. Breaking changes may be made but must increment the version
# number in the identifier.
#
# This applet incorporates by reference the protocol used by the `swd-probe` applet. Breaking
# changes to the protocol of that applet are also breaking changes to the protocol of this applet.

import logging
import asyncio
import argparse

from amaranth import *
from amaranth.lib import enum, data, wiring, stream, io
from amaranth.lib.wiring import In, Out

from glasgow.gateware import cobs
from glasgow.gateware.stream import StreamBuffer
from glasgow.hardware.device import VID_QIHW, PID_GLASGOW
from glasgow.support.endpoint import endpoint, ServerEndpoint
from glasgow.applet.interface.swd_probe import SWDProbeComponent
from glasgow.applet import GlasgowAppletV2


__all__ = []


class ProbeRsTarget(enum.Enum, shape=8):
    Root = 0
    SWD  = 1
    # JTAG = 2 (future expansion)


class ProbeRsCommand(enum.Enum, shape=8):
    Identify    = 0x00
    GetDivisor  = 0x10
    SetDivisor  = 0x20
    AssertReset = 0x30
    ClearReset  = 0x31


class ProbeRsRootTarget(wiring.Component):
    IDENTIFIER = b"probe-rs,v00"

    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))
    o_flush:  Out(1)

    divisor:  Out(16)
    dut_rst:  Out(1)

    def elaborate(self, platform):
        m = Module()

        with m.FSM():
            with m.State("Command"):
                with m.If(self.i_stream.valid):
                    m.d.comb += self.i_stream.ready.eq(1)
                    with m.Switch(self.i_stream.payload):
                        with m.Case(ProbeRsCommand.Identify):
                            m.next = "Identify"
                        with m.Case(ProbeRsCommand.GetDivisor):
                            m.next = "Get Divisor"
                        with m.Case(ProbeRsCommand.SetDivisor):
                            m.next = "Set Divisor"
                        with m.Case(ProbeRsCommand.AssertReset):
                            m.d.sync += self.dut_rst.eq(1)
                        with m.Case(ProbeRsCommand.ClearReset):
                            m.d.sync += self.dut_rst.eq(0)
                        with m.Case():
                            m.d.comb += self.i_stream.ready.eq(0)
                with m.Else():
                    m.d.comb += self.o_flush.eq(1)

            with m.State("Identify"):
                ident  = C(int.from_bytes(self.IDENTIFIER, "little"), 12 * 8)
                offset = Signal(range(len(ident) + 1))

                m.d.comb += self.o_stream.payload.eq(ident.word_select(offset, 8))
                m.d.comb += self.o_stream.valid.eq(1)
                with m.If(self.o_stream.ready):
                    with m.If(offset == len(self.IDENTIFIER) - 1):
                        m.d.sync += offset.eq(0)
                        m.next = "Command"
                    with m.Else():
                        m.d.sync += offset.eq(offset + 1)

            with m.State("Get Divisor"):
                offset = Signal(range(2))

                m.d.comb += self.o_stream.payload.eq(self.divisor.word_select(offset, 8))
                m.d.comb += self.o_stream.valid.eq(1)
                with m.If(self.o_stream.ready):
                    m.d.sync += offset.eq(offset + 1)
                    with m.If(offset == 1):
                        m.next = "Command"

            with m.State("Set Divisor"):
                offset = Signal(range(2))

                m.d.comb += self.i_stream.ready.eq(1)
                with m.If(self.i_stream.valid):
                    m.d.sync += self.divisor.word_select(offset, 8).eq(self.i_stream.payload)
                    m.d.sync += offset.eq(offset + 1)
                    with m.If(offset == 1):
                        m.next = "Command"

        return m


class ProbeRsComponent(wiring.Component):
    i_stream: In(stream.Signature(8))
    o_stream: Out(stream.Signature(8))
    o_flush:  Out(1)

    def __init__(self, ports):
        self._ports = ports

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.cobs_decoder  = cobs_decoder  = cobs.Decoder()
        wiring.connect(m, cobs_decoder.i, wiring.flipped(self.i_stream))

        m.submodules.cobs_encoder = cobs_encoder = cobs.Encoder(fifo_depth=512)
        wiring.connect(m, wiring.flipped(self.o_stream), cobs_encoder.o)

        m.submodules.root_target = root_target = ProbeRsRootTarget()
        m.submodules.swd_target  = swd_target  = SWDProbeComponent(self._ports)
        m.d.comb += swd_target.divisor.eq(root_target.divisor)

        if self._ports.srst:
            # The SRST# buffer is open drain (SRST# is pulled high), to avoid or minimize bus
            # contention in case something on the board drives it as well.
            m.submodules.srst_buffer = srst_buffer = io.Buffer("o", self._ports.srst)
            m.d.comb += srst_buffer.oe.eq(root_target.dut_rst)

        targets = Array([root_target, swd_target])

        i_target = Signal(ProbeRsTarget)
        with m.FSM(name="i_fsm"):
            with m.State("Header"):
                with m.If(cobs_decoder.o.valid & ~cobs_decoder.o.p.end):
                    m.d.comb += cobs_decoder.o.ready.eq(1)
                    m.d.sync += i_target.eq(cobs_decoder.o.payload)
                    m.next = "Connect"

            with m.State("Connect"):
                with m.If(cobs_decoder.o.valid & cobs_decoder.o.p.end):
                    m.d.comb += cobs_decoder.o.ready.eq(1)
                    m.next = "Header"
                with m.Else():
                    m.d.comb += targets[i_target].i_stream.payload.eq(cobs_decoder.o.p.data)
                    m.d.comb += targets[i_target].i_stream.valid.eq(cobs_decoder.o.valid)
                    m.d.comb += cobs_decoder.o.ready.eq(targets[i_target].i_stream.ready)

        o_target = Signal(ProbeRsTarget)
        with m.FSM(name="o_fsm"):
            with m.State("Select"):
                with m.If(0):
                    pass
                for index, target in enumerate(targets):
                    with m.Elif(target.o_stream.valid):
                        m.d.sync += o_target.eq(index)
                        m.next = "Header"
                with m.Else():
                    m.d.comb += self.o_flush.eq(1)

            with m.State("Header"):
                m.d.comb += cobs_encoder.i.p.data.eq(o_target)
                m.d.comb += cobs_encoder.i.valid.eq(1)
                with m.If(cobs_encoder.i.ready):
                    m.next = "Connect"

            with m.State("Connect"):
                with m.If(~targets[o_target].o_stream.valid & targets[o_target].o_flush):
                    m.next = "End" # `o_flush` could go down; make sure `encoder.i.valid` doesn't
                with m.Else():
                    m.d.comb += cobs_encoder.i.p.data.eq(targets[o_target].o_stream.payload)
                    m.d.comb += cobs_encoder.i.valid.eq(targets[o_target].o_stream.valid)
                    m.d.comb += targets[o_target].o_stream.ready.eq(cobs_encoder.i.ready)

            with m.State("End"):
                m.d.comb += cobs_encoder.i.p.end.eq(1)
                m.d.comb += cobs_encoder.i.valid.eq(1)
                with m.If(cobs_encoder.i.ready):
                    m.next = "Select"

        return m


class ProbeRsApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "debug and program Arm microcontrollers via probe-rs"
    description = """
    Expose SWD via a socket that can be used with `probe-rs <https://probe.rs>`_.

    This applet is experimental. Currently, it only supports SWD and requires building
    `a fork of probe-rs <https://github.com/whitequark/probe-rs>`_.
    """
    required_revision = "C0"

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_voltage_argument(parser)
        access.add_pins_argument(parser, "swclk", required=True, default=True)
        access.add_pins_argument(parser, "swdio", required=True, default=True)
        access.add_pins_argument(parser, "srst")

    def build(self, args):
        with self.assembly.add_applet(self):
            self.assembly.use_voltage(args.voltage)
            if args.srst:
                self.assembly.use_pulls({args.srst: "high"})
            ports = self.assembly.add_port_group(swclk=args.swclk, swdio=args.swdio, srst=args.srst)
            component = self.assembly.add_submodule(ProbeRsComponent(ports))
            self.__pipe = self.assembly.add_inout_pipe(component.o_stream, component.i_stream,
                in_flush=component.o_flush, in_fifo_depth=0)

    @classmethod
    def add_run_arguments(cls, parser):
        parser.add_argument(
            "endpoint", metavar="ENDPOINT", type=endpoint, nargs="?",
            help="listen at ENDPOINT, either unix:PATH or tcp:HOST:PORT (default: connect via USB)")

    async def run(self, args):
        def connect_to(options):
            probe = f"{VID_QIHW:04x}:{PID_GLASGOW:04x}:{options}"
            self.logger.info(f"run `probe-rs info --probe {probe}`")

        if args.endpoint is None:
            iface_in, iface_out = await self.__pipe.detach()
            connect_to(f"{self.assembly.device.serial}:{iface_in}:{iface_out}")
        else:
            connect_to(":".join(map(str, args.endpoint)))
            endpoint = await ServerEndpoint("socket", self.logger, args.endpoint)
            await endpoint.attach_to_pipe(self.__pipe)

    @classmethod
    def tests(cls):
        from . import test
        return test.ProbeRsAppletTestCase
