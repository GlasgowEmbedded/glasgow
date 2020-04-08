# Reference: https://semtech.my.salesforce.com/sfc/p/#E0000000JelG/a/440000001NCE/v_VBhk1IolDgxwwnOpcS_vTFxPfSEPQbuneK3mWsXlU
# Accession: G00051

import math
import asyncio
import logging
import argparse
from time import sleep
from nmigen.compat import *

from ....support.logging import *
from ....support.bits import *
from ....support.endpoint import *
from ....arch.sx1272 import regs_common
from ....arch.sx1272 import regs_xxk
from ....arch.sx1272 import regs_lora
from ....arch.sx1272.apis import *
from ....protocol.lora import *
from ...interface.spi_master import SPIMasterSubtarget, SPIMasterInterface
from ... import *


class RadioSX1272Interface:
    def __init__(self, interface, logger):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE

    def _log(self, message, *args):
        self._logger.log(self._level, message, *args)

    async def read_register_wide(self, address, length):
        assert address in range(0x70 + 1)
        await self.lower.write([regs_common.OP_R_REGISTER|address], hold_ss=True)
        value = await self.lower.read(length)
        self._log("read register [%02x]=<%s>", address, dump_hex(value))
        return value

    async def write_register_wide(self, address, value):
        assert address in range(0x70 + 1)
        self._log("write register [%02x]=<%s>", address, dump_hex(value))
        await self.lower.write([regs_common.OP_W_REGISTER|address, *value])

    async def read_register(self, address):
        value, = await self.read_register_wide(address, 1)
        return value

    async def write_register(self, address, value):
        await self.write_register_wide(address, [value])


class RadioSX1272Applet(GlasgowApplet, name="radio-sx1272"):
    logger = logging.getLogger(__name__)
    help = "transmit and receive using SX1272 RF PHY"
    description = """
    Transmit and receive packets using the SX1272 RF PHY.

    This applet allows setting only LoRa modulation parameters, FSK/OOK
    modem is not implemented in high level APIs. Transmit and receive
    operations are implemented. The monitor command will listen and dump all
    messages received while running.

    For LoRaWAN operation, see radio-lorawan applet
    """

    __pins = ("ss", "sck", "mosi", "miso")

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_build_arguments(parser)

        access.add_pin_argument(parser, "ss",  default=True)
        access.add_pin_argument(parser, "mosi", default=True)
        access.add_pin_argument(parser, "miso", default=True)
        access.add_pin_argument(parser, "sck",  default=True)

        parser.add_argument(
            "--spi-freq", metavar="FREQ", type=int, default=500,
            help="set SPI frequency to FREQ kHz (default: %(default)s)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        pads = iface.get_pads(args, pins=self.__pins)
        iface.add_subtarget(SPIMasterSubtarget(
            pads=pads,
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(),
            period_cyc=math.ceil(target.sys_clk_freq / (args.spi_freq * 1000)),
            delay_cyc=math.ceil(target.sys_clk_freq / 1e6),
            sck_idle=0,
            sck_edge="rising",
            ss_active=0,
        ))

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        spi_iface = SPIMasterInterface(iface, self.logger)
        sx1272_iface = RadioSX1272Interface(spi_iface, self.logger)

        return sx1272_iface

    @classmethod
    def add_interact_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OP", required=True)
        p_receive = p_operation.add_parser("receive", help="receive packets")
        p_monitor = p_operation.add_parser("monitor", help="monitor packets")
        p_transmit = p_operation.add_parser("transmit", help="transmit packets")
        p_socket = p_operation.add_parser("socket", help="connect tx to a socket")
        ServerEndpoint.add_argument(p_socket, "endpoint", default='tcp:localhost:9999')

        def payload(value):
            pl = int(value, 16)
            pl = pl.to_bytes(math.ceil(pl.bit_length()/8), 'little')
            return pl

        def freq(value):
            f = float(value)
            return f

        parser.add_argument(
            "-f", "--freq", metavar="FREQ", type=freq, required=True,
            help="set the transmission frequency in MHz"
        )
        parser.add_argument(
            "--bw", metavar="BW", type=int, default=125,
            choices=(125, 250, 500),
            help="set the bandwidth in kHz"
        )
        parser.add_argument(
            "--crate", metavar="CODR", type=int, default=5,
            choices=(5, 6, 7, 8),
            help="set the coding rate (in 4/x)"
        )
        parser.add_argument(
            "--sf", metavar="SF", type=int, default=12,
            choices=(6, 7, 8, 9, 10, 11, 12),
            help="set the spreading factor"
        )

        p_transmit.add_argument(
            "--pwr", metavar="PWR", type=int, default=13,
            choices=range(1, 14),
            help="set the transmit power in dBm"
        )
        p_transmit.add_argument(
            "--payload", metavar="PAYLOAD", type=payload, required=True,
            help="set the payload to be sent"
        )

    async def _interact_socket(self, dev, endpoint):
        endpoint = await ServerEndpoint("socket", self.logger, endpoint)
        while True:
            try:
                data = await asyncio.shield(endpoint.recv())
                await dev.transmit(data)
            except asyncio.CancelledError:
                pass

    async def interact(self, device, args, sx1272_iface):
        dev = SX1272_LoRa_Device_API(sx1272_iface, self.logger)

        if args.operation != "transmit":
            args.pwr = 13

        await dev.configure(args.freq*1e6, args.bw*1e3, args.sf, args.pwr, args.crate)

        if args.operation == "transmit":
            await dev.transmit(args.payload)
            self.logger.info("Packet sent")
        if args.operation == "receive":
            data, _, snr, rssi, codr = await dev.receive()
            if data != None:
                self.logger.info("Received packet: {} with SNR = {}, RSSI = {}, coding rate = {}".format(data, snr, rssi, codr))
            else:
                self.logger.error("No packet received")
        if args.operation == "monitor":
            async def onpayload(data, crcerr, snr, rssi, codr):
                self.logger.info("Received packet: {} with SNR = {}, RSSI = {}, coding rate = {}".format(data, snr, rssi, codr))
            await dev.listen(onpayload)
        if args.operation == "socket":
            await self._interact_socket(dev, args.endpoint)

# -------------------------------------------------------------------------------------------------

class RadioSX1272AppletTestCase(GlasgowAppletTestCase, applet=RadioSX1272Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
