import math
import asyncio
import logging
import argparse
from time import sleep
from nmigen.compat import *

from ....support.logging import *
from ....support.endpoint import *
from ....support.bits import *
from ....arch.sx1272 import regs_common
from ....arch.sx1272 import regs_xxk
from ....arch.sx1272 import regs_lora
from ....arch.sx1272.apis import *
from ....protocol.lora import *
from ...interface.spi_master import SPIMasterSubtarget, SPIMasterInterface
from ... import *
from ..sx1272 import RadioSX1272Interface


class LoRaWANApplet(GlasgowApplet, name="radio-lorawan"):
    logger = logging.getLogger(__name__)
    help = "operate as a LoRaWAN node or gateway"
    description = """
    Set up a LoRaWAN node or gateway using SX1272 PHY
    
    The gateway uses the Semtech UDP forwarder protocol. Uplink and downlink
    operations are multiplexed using the same PHY. The node should join the
    network before transmitting any data

    RF parameters are set by specifying the region and channel.
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
            "-f", "--frequency", metavar="FREQ", type=int, default=500,
            help="set SPI frequency to FREQ kHz (default: %(default)s)")

    def build(self, target, args):
        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        pads = iface.get_pads(args, pins=self.__pins)
        iface.add_subtarget(SPIMasterSubtarget(
            pads=pads,
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(),
            period_cyc=math.ceil(target.sys_clk_freq / (args.frequency * 1000)),
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
        p_role = parser.add_subparsers(dest="role", metavar="ROLE", required=True)
        p_node = p_role.add_parser("node", help="LoRaWAN Node")
        p_gateway = p_role.add_parser("gateway", help="LoRaWAN Gateway (Semtech UDP forwarder)")
        ServerEndpoint.add_argument(p_node, "endpoint", default='tcp:localhost:9999')

        def eui(value):
            eui = int(value, 16)
            return eui

        def port(value):
            value = int(value, 10)
            if value not in range(1, 224):
                raise argparse.ArgumentTypeError(
                    "invalid port: {} (choose from 1..223)".format(value))
            return value

        def add_common_args(p):
            p.add_argument(
                "--region", metavar="REGION", type=str, default="EU863870",
                help="set the LoRaWAN region"
            )
            p.add_argument(
                "--chn", metavar="CHN", type=int, default=0,
                help="set the region channel to use"
            )
            p.add_argument(
                "--data-rate", metavar="DATR", type=int, default=0,
                choices=(range(0, 6)),
                help="set the datarate"
            )

        add_common_args(p_node)
        add_common_args(p_gateway)

        p_node.add_argument(
            "--dev-eui", metavar="DEVEUI", type=eui, required=True,
            help="set the device EUI"
        )
        p_node.add_argument(
            "--app-eui", metavar="APPEUI", type=eui, required=True,
            help="set the application EUI"
        )
        p_node.add_argument(
            "-K", "--app-key", metavar="APPKEY", type=eui, required=True,
            help="set the application key"
        )
        p_node.add_argument(
            "-P", "--tx-port", metavar="TXPORT", type=port, default=1,
            help="Set the transmission port"
        )
        p_node.add_argument(
            "-C", "--tx-confirmed", default=False, action="store_true",
            help="Set to true if transmissions are confirmed"
        )

        p_gateway.add_argument(
            "--gw-eui", metavar="GWEUI", type=eui, required=True,
            help="set the gateway EUI"
        )
        p_gateway.add_argument(
            "-S", "--gw-server", metavar="GWSRV", type=str, default="router.eu.thethings.network",
            help="set the gateway server"
        )
        p_gateway.add_argument(
            "-P", "--gw-port", metavar="GWPORT", type=int, default=1700,
            help="set the gateway server port"
        )

    async def _interact_socket(self, args, dev):
        endpoint = await ServerEndpoint("socket", self.logger, args.endpoint)
        while True:
            try:
                data = await asyncio.shield(endpoint.recv())
                self.logger.info("Sending payload {}".format(data))
                await dev.transmit(args.tx_port, data, args.tx_confirmed)
            except asyncio.CancelledError:
                pass

    def node_frame_cb(self, fport, fpl):
        self.logger.info("Received payload {} from port {}".format(fpl, fport))

    async def interact(self, device, args, sx1272_iface):
        region_params = {
            "EU863870": EU863870_PARAMETERS
        }[args.region]
        sx1272 = SX1272_LoRa_Device_API(sx1272_iface, self.logger)

        if args.role == "node":
            dev = node = LoRaWAN_Node(sx1272, region_params, args.app_key, args.dev_eui, args.app_eui, self.logger, self.node_frame_cb)
        elif args.role == "gateway":
            dev = gw = LoRaWAN_Gateway(sx1272, region_params, args.gw_server, args.gw_port, args.gw_eui, self.logger)

        await dev.configure_by_channel(args.chn, args.data_rate)

        if args.role == "node":
            joined = await node.join_network()
            if not joined:
                self.logger.error("Error joinning network")
            else:
                self.logger.info("Joined network")
                await node.configure_by_channel(args.chn, args.data_rate)
                await self._interact_socket(args, node)
        elif args.role == "gateway":
            await gw.main()

# -------------------------------------------------------------------------------------------------

class LoRaWANAppletTestCase(GlasgowAppletTestCase, applet=LoRaWANApplet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
