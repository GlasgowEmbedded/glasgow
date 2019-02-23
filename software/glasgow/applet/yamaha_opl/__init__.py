# Ref: CATALOG No. LSI-2130143 (YM3014B)
# Ref: CATALOG No. LSI-2138123 (YM3812)
# Ref: CATALOG No. LSI-2438124 (YM3812 Application Manual)

# The documentation (which often serves more to confuse than to document), has plenty of typos
# and omits critical parts. A brief list of datasheet issues, most of which are common for
# the entire OPL series:
#  * Pin 1 is VCC, not VSS as on the diagram.
#  * ~RD and ~WR are active low, unlike what the truth table implies.
#  * The timing diagrams are incomplete. They imply reads and writes are asynchronous. This is
#    only partially true. There is a latency in terms of master clock cycles after each write,
#    which differs from series to series and from address to data.
#     - OPLL/OPL(?)/OPL2(?): address 12 cycles, data 84 cycles. (only documented for OPLL)
#     - OPL3: address 32 cycles, data 32 cycles. (documented)
#
# The Yamaha DAC bitstream fromat is somewhat underdocumented and confusing. The DAC bitstream
# has 16 bit dynamic range and uses 13 bit samples in a bespoke floating point format. These 13 bit
# samples are padded to 16 bits and transmitted over a serial protocol similar to I²S.
#
# The sample format is as follows, transmitted on wire LSB first:
#  (LSB)                                                                       (MSB)
#  +----+----+----+----+----+----+----+----+----+----+----+----+----+----+----+----+
#  | 0  | 0  | 0  | M0 | M1 | M2 | M3 | M4 | M5 | M6 | M7 | M8 | S  | E0 | E1 | E2 |
#  +----+----+----+----+----+----+----+----+----+----+----+----+----+----+----+----+
#
# Each sample defines a 9-bit M(antissa), 1-bit S(ign) and 3-bit E(exponent). The legal values
# for the exponent are 1..7. The sample format does not appear to follow any intrinsic structure
# and seems to have been chosen for the simplicity of DAC implementation alone. Therefore, no
# attempt is made here to describe the sample format in abstract terms.
#
# The DAC transfer function, which converts DAC bitstream to unsigned 16-bit voltage levels,
# is as follows, in a Verilog-like syntax:
#     assign V = {S, {{7{~S}}, M, 7'b0000000}[E+:15]};

import logging
import argparse
import struct
import array
import asyncio
from migen import *
from migen.genlib.cdc import MultiReg

from .. import *
from ...gateware.pads import *
from ...protocol.vgm import *


class YamahaOPLBus(Module):
    def __init__(self, pads, master_cyc):
        self.stb_m  = Signal()
        self.stb_sy = Signal()
        self.stb_sh = Signal()

        self.a  = Signal(1)

        self.oe = Signal(reset=1)
        self.di = Signal(8)
        self.do = Signal(8)

        self.cs = Signal()
        self.rd = Signal()
        self.wr = Signal()

        self.sh = Signal()
        self.mo = Signal()

        ###

        half_master_cyc = int(master_cyc // 2)

        cyc_m   = Signal(max=half_master_cyc)
        self.sync += [
            If(cyc_m == 0,
                cyc_m.eq(half_master_cyc - 1),
            ).Else(
                cyc_m.eq(cyc_m - 1)
            ),
        ]

        clk_m_s = Signal()
        clk_m_r = Signal()
        self.sync += [
            If(cyc_m == 0,
                clk_m_s.eq(~clk_m_s)
            ),
            clk_m_r.eq(clk_m_s),
            self.stb_m.eq(~clk_m_r & clk_m_s)
        ]

        clk_sy_s = Signal()
        clk_sy_r = Signal()
        self.sync += [
            clk_sy_r.eq(clk_sy_s),
            self.stb_sy.eq(~clk_sy_r & clk_sy_s)
        ]

        sh_r = Signal()
        self.sync += [
            sh_r.eq(self.sh),
            self.stb_sh.eq(sh_r & ~self.sh)
        ]

        self.comb += [
            pads.clk_m_t.oe.eq(1),
            pads.clk_m_t.o.eq(clk_m_s),
            pads.d_t.oe.eq(self.oe),
            pads.d_t.o.eq(Cat((self.do))),
            self.di.eq(Cat((pads.d_t.i))),
            pads.a_t.oe.eq(1),
            pads.a_t.o.eq(self.a),
            pads.cs_t.oe.eq(1),
            pads.cs_t.o.eq(~self.cs),
            # handle (self.rd & (self.wr | self.oe)) == 1 safely
            pads.rd_t.oe.eq(1),
            pads.rd_t.o.eq(~(self.rd & ~self.wr & ~self.oe)),
            pads.wr_t.oe.eq(1),
            pads.wr_t.o.eq(~(self.wr & ~self.rd)),
        ]

        self.specials += [
            MultiReg(pads.clk_sy_t.i, clk_sy_s),
            MultiReg(pads.sh_t.i, self.sh),
            MultiReg(pads.mo_t.i, self.mo)
        ]


OP_ENABLE = 0x00
OP_WRITE  = 0x10
OP_READ   = 0x20
OP_WAIT   = 0x30
OP_MASK   = 0xf0


class YamahaOPLSubtarget(Module):
    def __init__(self, pads, in_fifo, out_fifo,
                 read_pulse_cyc, write_pulse_cyc, address_latency_cyc, data_latency_cyc,
                 master_cyc):
        self.submodules.bus = bus = YamahaOPLBus(pads, master_cyc)

        # Control


        pulse_timer   = Signal(max=max(read_pulse_cyc, write_pulse_cyc))
        latency_timer = Signal(max=max(address_latency_cyc, data_latency_cyc))
        sample_timer  = Signal(16)

        enabled  = Signal()

        # The code below assumes that the FSM clock is under ~50 MHz, which frees us from the need
        # to explicitly satisfy setup/hold timings.
        self.submodules.control_fsm = FSM()
        self.control_fsm.act("IDLE",
            NextValue(bus.oe, 1),
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                Case(out_fifo.dout & OP_MASK, {
                    OP_ENABLE: [
                        NextValue(enabled, out_fifo.dout & ~OP_MASK),
                    ],
                    OP_WRITE:  [
                        NextValue(bus.a, out_fifo.dout & ~OP_MASK),
                        NextState("WRITE-DATA")
                    ],
                    # OP_READ: NextState("READ"),
                    OP_WAIT: [
                        NextState("WAIT-H-BYTE")
                    ]
                })
            )
        )
        self.control_fsm.act("WRITE-DATA",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(bus.do, out_fifo.dout),
                NextValue(bus.cs, 1),
                NextValue(bus.wr, 1),
                NextValue(pulse_timer, write_pulse_cyc - 1),
                NextState("WRITE-PULSE")
            )
        )
        self.control_fsm.act("WRITE-PULSE",
            If(pulse_timer == 0,
                NextValue(bus.cs, 0),
                NextValue(bus.wr, 0),
                If(bus.a == 0b0,
                    NextValue(latency_timer, address_latency_cyc - 1)
                ).Else(
                    NextValue(latency_timer, data_latency_cyc - 1)
                ),
                NextState("WRITE-LATENCY")
            ).Else(
                NextValue(pulse_timer, pulse_timer - 1)
            )
        )
        self.control_fsm.act("WRITE-LATENCY",
            If(bus.stb_m,
                If(latency_timer == 0,
                    NextState("IDLE")
                ).Else(
                    NextValue(latency_timer, latency_timer - 1)
                )
            )
        )
        self.control_fsm.act("WAIT-H-BYTE",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(sample_timer[8:16], out_fifo.dout),
                NextState("WAIT-L-BYTE")
            )
        )
        self.control_fsm.act("WAIT-L-BYTE",
            If(out_fifo.readable,
                out_fifo.re.eq(1),
                NextValue(sample_timer[0:8], out_fifo.dout),
                NextState("WAIT-LOOP")
            )
        )
        self.control_fsm.act("WAIT-LOOP",
            If(sample_timer == 0,
                NextState("IDLE")
            ).Else(
                If(bus.stb_sh,
                    NextValue(sample_timer, sample_timer - 1)
                )
            )
        )

        # Audio

        xfer_i = Record([
            ("z", 3),
            ("m", 9),
            ("s", 1),
            ("e", 3)
        ])
        xfer_o = Signal(16)
        self.comb += [
            # FIXME: this is uglier than necessary because of Migen bugs. Rewrite nicer in nMigen.
            xfer_o.eq(Cat((Cat(xfer_i.m, Replicate(~xfer_i.s, 7)) << xfer_i.e)[1:16], xfer_i.s))
        ]

        data_r = Signal(16)
        data_l = Signal(16)
        self.sync += If(bus.stb_sy, data_r.eq(Cat(data_r[1:], bus.mo)))
        self.comb += xfer_i.raw_bits().eq(data_l)

        self.submodules.data_fsm = FSM()
        self.data_fsm.act("WAIT-SH",
            If(bus.stb_sh & enabled,
                NextState("SAMPLE")
            )
        )
        self.data_fsm.act("SAMPLE",
            NextValue(data_l, data_r),
            NextState("SEND-L-BYTE")
        )
        self.data_fsm.act("SEND-L-BYTE",
            in_fifo.din.eq(xfer_o[0:8]),
            in_fifo.we.eq(1),
            If(in_fifo.writable,
                NextState("SEND-H-BYTE")
            )
        )
        self.data_fsm.act("SEND-H-BYTE",
            in_fifo.din.eq(xfer_o[8:16]),
            in_fifo.we.eq(1),
            If(in_fifo.writable,
                NextState("WAIT-SH")
            )
        )


class YamahaOPLInterface:
    def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, "OPL*: " + message, *args)

    async def enable(self):
        self._log("enable")
        await self.lower.write([OP_ENABLE|1])

    async def disable(self):
        self._log("disable")
        await self.lower.write([OP_ENABLE|0])

    async def write_register(self, address, data):
        self._log("write [%#04x]=%#04x", address, data)
        await self.lower.write([OP_WRITE|0, address, OP_WRITE|1, data])

    async def wait_samples(self, count):
        self._log("wait %d samples", count)
        await self.lower.write([OP_WAIT, *struct.pack(">H", count)])

    async def read_samples(self, count):
        return await self.lower.read(count * 2)


class YamahaVGMStreamPlayer(VGMStreamPlayer):
    def __init__(self, reader, opl_iface):
        self._reader     = reader
        self._opl_iface  = opl_iface

        self.sample_time = 72 / reader.ym3812_clk # 72 фM per фSY

    async def play(self):
        try:
            await self._opl_iface.enable()
            await self._reader.parse_data(self)
        finally:
            await self._opl_iface.disable()

    async def record(self):
        count = int(self._reader.total_seconds / self.sample_time)
        return await self._opl_iface.read_samples(count)

    async def ym3812_write(self, address, data):
        await self._opl_iface.write_register(address, data)

    async def wait_seconds(self, delay):
        await self._opl_iface.wait_samples(int(delay / self.sample_time))


class YamahaOPLApplet(GlasgowApplet, name="yamaha-opl"):
    logger = logging.getLogger(__name__)
    help = "drive and record Yamaha OPL* FM synthesizers"
    description = """
    Send commands and record digital output from Yamaha OPL* series FM synthesizers. Currently,
    only OPL2 is supported, but this applet is easy to extend to other similar chips.

    The digital output is losslessly converted to 16-bit unsigned PCM samples. (The Yamaha DACs
    only have 16 bit of dynamic range, and there is a direct mapping between the on-wire floating
    point sample format and ordinary 16-bit PCM.)

    The written samples can be played with the knowledge of the sample rate, which is derived from
    the OPL frequency specified in the input file. E.g. using SoX:

        $ play -r 49715 output.u16
    """

    __pin_sets = ("d", "a")
    __pins = ("clk_m", "cs", "rd", "wr",
              "clk_sy", "sh", "mo")

    @classmethod
    def add_build_arguments(cls, parser, access):
        super().add_build_arguments(parser, access)

        access.add_pin_set_argument(parser, "d", width=8, default=True)
        access.add_pin_argument(parser, "clk_m", default=True)
        access.add_pin_set_argument(parser, "a", width=1, default=True)
        access.add_pin_argument(parser, "cs", default=True)
        access.add_pin_argument(parser, "rd", default=True)
        access.add_pin_argument(parser, "wr", default=True)
        access.add_pin_argument(parser, "clk_sy", default=True)
        access.add_pin_argument(parser, "sh", default=True)
        access.add_pin_argument(parser, "mo", default=True)

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        subtarget = iface.add_subtarget(YamahaOPLSubtarget(
            pads=iface.get_pads(args, pins=self.__pins, pin_sets=self.__pin_sets),
            # These FIFO depths are somewhat dependent on the (current, bad) arbiter in Glasgow,
            # but they work for now. With a better arbiter they should barely matter.
            out_fifo=iface.get_out_fifo(depth=512),
            in_fifo=iface.get_in_fifo(depth=8192, auto_flush=False),
            master_cyc=target.sys_clk_freq / 3.58e6,
            read_pulse_cyc=int(target.sys_clk_freq * 200e-9),
            write_pulse_cyc=int(target.sys_clk_freq * 100e-9),
            address_latency_cyc=12,
            data_latency_cyc=84,
        ))
        return subtarget

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        opl_iface = YamahaOPLInterface(iface, self.logger)
        return opl_iface

    @classmethod
    def add_interact_arguments(cls, parser):
        parser.add_argument(
            "vgm_file", metavar="VGM-FILE", type=argparse.FileType("rb"),
            help="read commands from VGM-FILE (one of: .vgm .vgm.gz .vgz)")
        parser.add_argument(
            "pcm_file", metavar="PCM-FILE", type=argparse.FileType("wb"),
            help="write samples to PCM-FILE")

    async def interact(self, device, args, opl_iface):
        vgm_reader = VGMStreamReader.from_file(args.vgm_file)
        self.logger.info("VGM file contains commands for %s", ", ".join(vgm_reader.chips()))
        if vgm_reader.ym3812_clk == 0:
            raise GlasgowAppletError("VGM file does not contain commands for YM3812")
        if len(vgm_reader.chips()) > 1:
            self.logger.warning("VGM file contains commands for %s, which will be ignored"
                                .format(", ".join(vgm_reader.chips())))

        vgm_player = YamahaVGMStreamPlayer(vgm_reader, opl_iface)
        self.logger.info("recording at sample rate %d Hz", 1 / vgm_player.sample_time)

        play_fut   = asyncio.ensure_future(vgm_player.play())
        record_fut = asyncio.ensure_future(vgm_player.record())
        done, pending = await asyncio.wait([play_fut, record_fut],
                                           return_when=asyncio.FIRST_EXCEPTION)

        if play_fut.done():
            await play_fut
        if record_fut.done():
            args.pcm_file.write(record_fut.result())

# -------------------------------------------------------------------------------------------------

class YamahaOPLAppletTestCase(GlasgowAppletTestCase, applet=YamahaOPLApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
