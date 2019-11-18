# Reference: https://infocenter.nordicsemi.com/pdf/nRF24L01P_PS_v1.0.pdf
# Accession: ???

import math
import asyncio
import logging
import argparse
from nmigen.compat import *

from ....support.logging import *
from ....arch.nrf24l.rf import *
from ...interface.spi_master import SPIMasterSubtarget, SPIMasterInterface
from ... import *


class RadioNRF24L01Error(GlasgowAppletError):
    pass


class RadioNRF24L01Interface:
    def __init__(self, interface, logger, device, addr_dut_ce):
        self.lower   = interface
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name == __name__ else logging.TRACE
        self._device = device
        self._addr_dut_ce = addr_dut_ce

    def _log(self, message, *args):
        self._logger.log(self._level, "nRF24L01: " + message, *args)

    async def enable(self):
        self._log("enable rf")
        await self._device.write_register(self._addr_dut_ce, 1)

    async def disable(self):
        self._log("disable rf")
        await self._device.write_register(self._addr_dut_ce, 0)

    async def pulse(self):
        await self.enable()
        await asyncio.sleep(0.1) # 10 µs
        await self.disable()

    async def read_register_wide(self, address, length):
        assert address in range(0x1f)
        await self.lower.write([OP_R_REGISTER|address], hold_ss=True)
        value = await self.lower.read(length)
        self._log("read register [%02x]=<%s>", address, dump_hex(value))
        return value

    async def write_register_wide(self, address, value):
        assert address in range(0x1f)
        self._log("write register [%02x]=<%s>", address, dump_hex(value))
        await self.lower.write([OP_W_REGISTER|address, *value])

    async def read_register(self, address):
        value, = await self.read_register_wide(address, 1)
        return value

    async def write_register(self, address, value):
        await self.write_register_wide(address, [value])

    async def read_rx_payload_length(self):
        await self.lower.write([OP_R_RX_PL_WID], hold_ss=True)
        length, = await self.lower.read(1)
        self._log("read rx payload length=%d", length)
        return length

    async def read_rx_payload(self, length):
        await self.lower.write([OP_R_RX_PAYLOAD], hold_ss=True)
        payload = await self.lower.read(length)
        self._log("read rx payload=<%s>", dump_hex(payload))
        return payload

    async def flush_rx(self):
        self._log("flush rx")
        await self.lower.write([OP_FLUSH_RX])

    async def write_tx_payload(self, payload, *, ack=True):
        self._log("write tx payload=<%s> ack=%s", dump_hex(payload), "yes" if ack else "no")
        if ack:
            await self.lower.write([OP_W_TX_PAYLOAD, *payload])
        else:
            await self.lower.write([OP_W_TX_PAYLOAD_NOACK, *payload])

    async def reuse_tx_payload(self):
        self._log("reuse tx payload")
        await self.lower.write([OP_REUSE_TX_PL])

    async def flush_tx(self):
        self._log("flush tx")
        await self.lower.write([OP_FLUSH_TX])


class RadioNRF24L01Applet(GlasgowApplet, name="radio-nrf24l"):
    preview = True
    logger = logging.getLogger(__name__)
    help = "transmit and receive using nRF24L01(+) RF PHY"
    description = """
    Transmit and receive packets using the nRF24L01/nRF24L01+ RF PHY.

    This applet allows configuring all channel and packet parameters, and provides basic transmit
    and receive workflow with one pipe and automatic transaction handling (Enhanced ShockBurst).
    It does not support multiple pipes, acknowledgement payloads, or disabling transaction
    handling (ShockBurst mode).

    The pinout of a common 8-pin nRF24L01+ module is as follows (live bug view):

    ::
          GND @ * VCC
           CE * * SS
          SCK * * MOSI
         MISO * * IRQ
    """

    __pins = ("ce", "ss", "sck", "mosi", "miso", "irq")

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_build_arguments(parser)

        # Order matches the pin order, in clockwise direction.
        access.add_pin_argument(parser, "ce",   default=True)
        access.add_pin_argument(parser, "ss",   default=True)
        access.add_pin_argument(parser, "sck",  default=True)
        access.add_pin_argument(parser, "mosi", default=True)
        access.add_pin_argument(parser, "miso", default=True)
        access.add_pin_argument(parser, "irq",  default=True)

        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=1000,
            help="set SPI frequency to FREQ kHz (default: %(default)s)")

    def build(self, target, args):
        dut_ce, self.__addr_dut_ce = target.registers.add_rw(1)

        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        pads = iface.get_pads(args, pins=self.__pins)

        subtarget = iface.add_subtarget(SPIMasterSubtarget(
            pads=pads,
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(),
            period_cyc=math.ceil(target.sys_clk_freq / (args.frequency * 1000)),
            delay_cyc=math.ceil(target.sys_clk_freq / 1e6),
            sck_idle=0,
            sck_edge="rising",
            ss_active=0,
        ))
        subtarget.comb += [
            pads.ce_t.o.eq(dut_ce),
            pads.ce_t.oe.eq(1),
        ]

        return subtarget

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        spi_iface = SPIMasterInterface(iface, self.logger)
        nrf24l01_iface = RadioNRF24L01Interface(spi_iface, self.logger, device,
                                                self.__addr_dut_ce)
        return nrf24l01_iface

    @classmethod
    def add_interact_arguments(cls, parser):
        def channel(value):
            value = int(value, 10)
            if value not in range(126):
                raise argparse.ArgumentTypeError(
                    "invalid channel: {} (choose from 0..125)".format(value))
            return value
        def address(value):
            return bytes.fromhex(value)
        def length(value):
            value = int(value, 10)
            if value not in range(33):
                raise argparse.ArgumentTypeError(
                    "invalid length: {} (choose from 0..32)".format(value))
            return value
        def payload(value):
            payload = bytes.fromhex(value)
            if len(payload) not in range(33):
                raise argparse.ArgumentTypeError(
                    "invalid payload length: {} (must be between 0..32)".format(len(value)))
            return payload

        parser.add_argument(
            "-c", "--channel", metavar="RF-CHANNEL", type=channel, required=True,
            help="set channel number to RF-CHANNEL (range: 0..125, corresponds to 2400..2525 MHz)")
        parser.add_argument(
            "-b", "--bandwidth", metavar="RF-BANDWIDTH", type=int, required=True,
            choices=(250, 1000, 2000),
            help="set air data rate to RF-BANDWIDTH kbps (one of: 250 1000 2000)")
        parser.add_argument(
            "-p", "--power", metavar="RF-POWER", type=int, default=0,
            choices=(0, -6, -12, -18),
            help="set output power to RF-POWER dBm (one of: 0 -6 -12 -18, default: %(default)s)")
        parser.add_argument(
            "-A", "--address-width", metavar="WIDTH", type=int, required=True,
            choices=(2, 3, 4, 5),
            help="set address width to WIDTH bytes (one of: 2 3 4 5)")
        parser.add_argument(
            "-C", "--crc-width", metavar="WIDTH", type=int, required=True,
            choices=(1, 2),
            help="set CRC width to WIDTH bytes (one of: 1 2)")
        parser.add_argument(
            "-d", "--dynamic-length", default=False, action="store_true",
            help="enable dynamic payload length (L01+ only)")

        # TODO(py3.7): add required=True
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION")

        p_transmit = p_operation.add_parser(
            "transmit", help="transmit a packet")
        p_transmit.add_argument(
            "address", metavar="ADDRESS", type=address,
            help="transmit packet with hex address ADDRESS")
        p_transmit.add_argument(
            "payload", metavar="DATA", type=payload,
            help="transmit DATA as packet payload")
        p_transmit.add_argument(
            "--transmit-timeout", metavar="DELAY", type=int, default=1500,
            choices=range(250, 4001, 250),
            help="if not acknowledged within DELAY µs, consider packet lost "
                 "(default: %(default)s us)")
        p_transmit.add_argument(
            "--retransmit-count", metavar="COUNT", type=int, default=3,
            choices=range(16),
            help="if unacknowledged, retransmit up to COUNT times (default: %(default)s)")
        p_transmit.add_argument(
            "-N", "--no-ack", default=False, action="store_true",
            help="do not request acknowledgement (L01+ only)")

        p_receive = p_operation.add_parser(
            "receive", help="receive a packet")
        p_receive.add_argument(
            "address", metavar="ADDRESS", type=address,
            help="receive packet with hex address ADDRESS")
        p_receive.add_argument(
            "-l", "--length", metavar="LENGTH", type=length,
            help="receive packet with length LENGTH (mutually exclusive with --dynamic-length)")

    async def interact(self, device, args, nrf24l01_iface):
        self.logger.info("using channel %d (%d MHz) at %d dBm and %d kbps",
            args.channel, 2400 + args.channel, args.power, args.bandwidth)
        rf_ch = args.channel
        rf_pwr = {
             0:  RF_PWR._0_dBm,
            -6:  RF_PWR.m6_dBm,
            -12: RF_PWR.m12_dBm,
            -18: RF_PWR.m18_dBm
        }[args.power]
        rf_dr = {
            250:  RF_DR._250_kbps,
            1000: RF_DR._1_Mbps,
            2000: RF_DR._2_Mbps
        }[args.bandwidth]

        self.logger.info("using %d address bytes, %s payload length, and %d CRC bytes",
            args.address_width, "dynamic" if args.dynamic_length else "static", args.crc_width)
        aw = {
            2: AW._2_BYTES,
            3: AW._3_BYTES,
            4: AW._4_BYTES,
            5: AW._5_BYTES,
        }[args.address_width]
        crco = {
            1: CRCO._1_BYTE,
            2: CRCO._2_BYTES,
        }[args.crc_width]
        en_dpl = args.dynamic_length
        en_dyn_ack = hasattr(args, "no_ack") and args.no_ack

        feature = REG_FEATURE(EN_DPL=en_dpl, EN_DYN_ACK=en_dyn_ack).to_int()
        await nrf24l01_iface.write_register(ADDR_FEATURE, feature)
        if (await nrf24l01_iface.read_register(ADDR_FEATURE)) != feature:
            raise RadioNRF24L01Error("Cannot enable nRF24L01+ features, is this nRF24L01?")

        await nrf24l01_iface.write_register(ADDR_RF_CH,
            REG_RF_CH(RF_CH=rf_ch).to_int())
        await nrf24l01_iface.write_register(ADDR_RF_SETUP,
            REG_RF_SETUP(RF_PWR=rf_pwr, RF_DR_LOW=rf_dr & 1, RF_DR_HIGH=rf_dr >> 1).to_int())
        await nrf24l01_iface.write_register(ADDR_SETUP_AW,
            REG_SETUP_AW(AW=aw).to_int())

        if args.operation == "transmit":
            await nrf24l01_iface.write_register(ADDR_CONFIG,
                REG_CONFIG(PRIM_RX=0, PWR_UP=1, CRCO=crco, EN_CRC=1).to_int())

            if len(args.address) != args.address_width:
                raise RadioNRF24L01Error("Length of address does not match address width")
            await nrf24l01_iface.write_register_wide(ADDR_TX_ADDR, args.address)
            await nrf24l01_iface.write_register(ADDR_EN_AA,
                REG_EN_AA(ENAA_P0=1).to_int())
            await nrf24l01_iface.write_register(ADDR_EN_RXADDR,
                REG_EN_RXADDR(ERX_P0=1).to_int())
            await nrf24l01_iface.write_register_wide(ADDR_RX_ADDR_Pn(0), args.address)
            if en_dpl:
                await nrf24l01_iface.write_register(ADDR_DYNPD,
                    REG_DYNPD(DPL_P0=1).to_int())
            await nrf24l01_iface.write_register(ADDR_SETUP_RETR,
                REG_SETUP_RETR(ARD=args.transmit_timeout // 250 - 1,
                               ARC=args.retransmit_count).to_int())

            while True:
                fifo_status = REG_FIFO_STATUS.from_int(
                    await nrf24l01_iface.read_register(ADDR_FIFO_STATUS))
                if fifo_status.TX_EMPTY:
                    break
                await nrf24l01_iface.flush_tx()

            await nrf24l01_iface.write_tx_payload(args.payload, ack=not args.no_ack)

            await nrf24l01_iface.write_register(ADDR_STATUS,
                REG_STATUS(TX_DS=1, MAX_RT=1).to_int())
            await nrf24l01_iface.enable()
            try:
                while True:
                    status = REG_STATUS.from_int(
                        await nrf24l01_iface.read_register(ADDR_STATUS))
                    if status.TX_DS or status.MAX_RT:
                        break
                    await asyncio.sleep(0.010)
            finally:
                await nrf24l01_iface.disable()

            if status.TX_DS:
                if args.no_ack:
                    self.logger.info("packet sent")
                else:
                    self.logger.info("packet acknowledged")
            if status.MAX_RT:
                if args.retransmit_count > 0:
                    observe_tx = REG_OBSERVE_TX.from_int(
                        await nrf24l01_iface.read_register(ADDR_OBSERVE_TX))
                    self.logger.error("packet lost after %d retransmits", observe_tx.ARC_CNT)
                else:
                    self.logger.error("packet lost")

        if args.operation == "receive":
            await nrf24l01_iface.write_register(ADDR_CONFIG,
                REG_CONFIG(PRIM_RX=1, PWR_UP=1, CRCO=crco, EN_CRC=1).to_int())

            if len(args.address) != args.address_width:
                raise RadioNRF24L01Error("Length of address does not match address width")
            await nrf24l01_iface.write_register(ADDR_EN_AA,
                REG_EN_AA(ENAA_P0=1).to_int())
            await nrf24l01_iface.write_register(ADDR_EN_RXADDR,
                REG_EN_RXADDR(ERX_P0=1).to_int())
            await nrf24l01_iface.write_register_wide(ADDR_RX_ADDR_Pn(0), args.address)
            if en_dpl:
                if args.length is not None:
                    raise RadioNRF24L01Error(
                        "Either --dynamic-length or --length may be specified")
                await nrf24l01_iface.write_register(ADDR_DYNPD,
                    REG_DYNPD(DPL_P0=1).to_int())
            else:
                if args.length is None:
                    raise RadioNRF24L01Error(
                        "One of --dynamic-length or --length must be specified")
                await nrf24l01_iface.write_register(ADDR_RX_PW_Pn(0), args.length)

            await nrf24l01_iface.write_register(ADDR_STATUS,
                REG_STATUS(RX_DR=1).to_int())
            await nrf24l01_iface.enable()
            try:
                while True:
                    status = REG_STATUS.from_int(
                        await nrf24l01_iface.read_register(ADDR_STATUS))
                    if status.RX_DR:
                        assert status.RX_P_NO == 0
                        break
                    await asyncio.sleep(0.010)
            finally:
                await nrf24l01_iface.disable()

            if en_dpl:
                length = await nrf24l01_iface.read_rx_payload_length()
            else:
                length = args.length
            payload = await nrf24l01_iface.read_rx_payload(length)

            self.logger.info("packet received: %s", dump_hex(payload))

# -------------------------------------------------------------------------------------------------

class RadioNRF24L01AppletTestCase(GlasgowAppletTestCase, applet=RadioNRF24L01Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
