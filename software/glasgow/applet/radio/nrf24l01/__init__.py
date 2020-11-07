# Reference: https://infocenter.nordicsemi.com/pdf/nRF24L01P_PS_v1.0.pdf
# Accession: G00044

import math
import asyncio
import logging
import argparse
from nmigen.compat import *

from ....support.logging import *
from ....support.bits import *
from ....arch.nrf24l import *
from ....arch.nrf24l.rf import *
from ...interface.spi_controller import SPIControllerSubtarget, SPIControllerInterface
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

    async def sync(self):
        self._log("sync")
        await self.lower.write([OP_NOP])
        await self.lower.read(1)

    async def enable(self):
        await self.sync()
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

    async def poll_rx_status(self, delay=0.010):
        poll_bits = clear_bits = REG_STATUS(RX_DR=1).to_int()
        while True:
            status_bits, _ = await self.lower.transfer([OP_W_REGISTER|ADDR_STATUS, clear_bits])
            status = REG_STATUS.from_int(status_bits)
            self._log("poll rx status %s", status.bits_repr(omit_zero=True))
            if status_bits & poll_bits:
                break
            await asyncio.sleep(delay)
        return status

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

    async def flush_rx_all(self):
        while True:
            fifo_status = REG_FIFO_STATUS.from_int(
                await self.read_register(ADDR_FIFO_STATUS))
            if fifo_status.RX_EMPTY:
                break
            await self.flush_rx()

    async def poll_tx_status(self, delay=0.010):
        # Don't clear MAX_RT, since it prevents REUSE_TX_PL and clears ARC_CNT.
        poll_bits  = REG_STATUS(TX_DS=1, MAX_RT=1).to_int()
        clear_bits = REG_STATUS(TX_DS=1).to_int()
        while True:
            status_bits, _ = await self.lower.transfer([OP_W_REGISTER|ADDR_STATUS, clear_bits])
            status = REG_STATUS.from_int(status_bits)
            self._log("poll rx status %s", status.bits_repr(omit_zero=True))
            if status_bits & poll_bits:
                break
            await asyncio.sleep(delay)
        return status

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

    async def flush_tx_all(self):
        while True:
            fifo_status = REG_FIFO_STATUS.from_int(
                await self.read_register(ADDR_FIFO_STATUS))
            if fifo_status.TX_EMPTY:
                break
            await self.flush_tx()


class RadioNRF24L01Applet(GlasgowApplet, name="radio-nrf24l01"):
    logger = logging.getLogger(__name__)
    help = "transmit and receive using nRF24L01(+) RF PHY"
    description = """
    Transmit and receive packets using the nRF24L01/nRF24L01+ RF PHY.

    This applet allows configuring all channel and packet parameters, and provides basic transmit
    and receive workflow, as well as monitor mode. It supports Enhanced ShockBurst (new packet
    framing with automatic transaction handling) with one pipe, as well as ShockBurst (old packet
    framing). It does not support multiple pipes or acknowledgement payloads.

    Note that in the CLI, the addresses are most significant byte first (the same as on-air order,
    and reversed with regards to register access order.)

    The `monitor` subcommand is functionally identical to the `receive` subcommand, except that
    it will never attempt to acknowledge packets; this way, it is possible to watch a transaction
    started by a node with a known address without disturbing either party. It is not natively
    supported by nRF24L01(+), and is emulated in an imperfect way.

    The pinout of a common 8-pin nRF24L01+ module is as follows (live bug view):

    ::
          GND @ * VCC
           CE * * CS
          SCK * * COPI
         CIPO * * IRQ
    """

    __pins = ("ce", "cs", "sck", "copi", "cipo", "irq")

    @classmethod
    def add_build_arguments(cls, parser, access):
        access.add_build_arguments(parser)

        # Order matches the pin order, in clockwise direction.
        access.add_pin_argument(parser, "ce",   default=True)
        access.add_pin_argument(parser, "cs",   default=True)
        access.add_pin_argument(parser, "sck",  default=True)
        access.add_pin_argument(parser, "copi", default=True)
        access.add_pin_argument(parser, "cipo", default=True)
        access.add_pin_argument(parser, "irq",  default=True)

        parser.add_argument(
            "-f", "--frequency", metavar="FREQ", type=int, default=1000,
            help="set SPI frequency to FREQ kHz (default: %(default)s)")

    def build(self, target, args):
        dut_ce, self.__addr_dut_ce = target.registers.add_rw(1)

        self.mux_interface = iface = target.multiplexer.claim_interface(self, args)
        pads = iface.get_pads(args, pins=self.__pins)

        subtarget = iface.add_subtarget(SPIControllerSubtarget(
            pads=pads,
            out_fifo=iface.get_out_fifo(),
            in_fifo=iface.get_in_fifo(),
            period_cyc=math.ceil(target.sys_clk_freq / (args.frequency * 1000)),
            delay_cyc=math.ceil(target.sys_clk_freq / 1e6),
            sck_idle=0,
            sck_edge="rising",
            cs_active=0,
        ))
        subtarget.comb += [
            pads.ce_t.o.eq(dut_ce),
            pads.ce_t.oe.eq(1),
        ]

        return subtarget

    async def run(self, device, args):
        iface = await device.demultiplexer.claim_interface(self, self.mux_interface, args)
        spi_iface = SPIControllerInterface(iface, self.logger)
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
            # In our API, byte 0 is LSB (which matches the order of writes to registers).
            # But in our CLI, byte 0 is MSB (which matches the on-air format).
            return bytes(reversed(bytes.fromhex(value)))
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
            choices=(0, 1, 2),
            help="set CRC width to WIDTH bytes (one of: 0 1 2)")
        parser.add_argument(
            "-L", "--compat-framing", default=False, action="store_true",
            help="disable automatic transaction handling, for pre-L01 compatibility")
        parser.add_argument(
            "-d", "--dynamic-length", default=False, action="store_true",
            help="enable dynamic payload length (L01+ only)")

        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_transmit = p_operation.add_parser(
            "transmit", help="transmit packets")
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

        def add_rx_arguments(parser):
            parser.add_argument(
                "address", metavar="ADDRESS", type=address,
                help="receive packet with hex address ADDRESS")
            parser.add_argument(
                "-l", "--length", metavar="LENGTH", type=length,
                help="receive packet with length LENGTH "
                     "(mutually exclusive with --dynamic-length)")
            parser.add_argument(
                "-R", "--repeat", default=False, action="store_true",
                help="keep receiving packets until interrupted")

        p_receive = p_operation.add_parser(
            "receive", help="receive packets")
        add_rx_arguments(p_receive)

        p_monitor = p_operation.add_parser(
            "monitor", help="monitor packets")
        add_rx_arguments(p_monitor)

    async def interact(self, device, args, nrf24l01_iface):
        if args.crc_width == 0 and not args.compat_framing:
            raise RadioNRF24L01Error("Automatic transaction handling requires CRC to be enabled")
        if args.dynamic_length and args.compat_framing:
            raise RadioNRF24L01Error("Dynamic length requires automatic transaction handling")

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
            0: CRCO._1_BYTE,
            1: CRCO._1_BYTE,
            2: CRCO._2_BYTES,
        }[args.crc_width]
        en_crc = args.crc_width > 0
        en_aa  = not args.compat_framing
        en_dpl = args.dynamic_length
        en_dyn_ack = hasattr(args, "no_ack") and args.no_ack

        await nrf24l01_iface.write_register(ADDR_CONFIG,
            REG_CONFIG(PWR_UP=0).to_int())

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
            if len(args.address) != args.address_width:
                raise RadioNRF24L01Error("Length of address does not match address width")
            await nrf24l01_iface.write_register_wide(ADDR_TX_ADDR, args.address)
            if en_aa:
                await nrf24l01_iface.write_register(ADDR_EN_AA,
                    REG_EN_AA(ENAA_P0=1).to_int())
                await nrf24l01_iface.write_register(ADDR_SETUP_RETR,
                    REG_SETUP_RETR(ARD=args.transmit_timeout // 250 - 1,
                                   ARC=args.retransmit_count).to_int())
                await nrf24l01_iface.write_register(ADDR_EN_RXADDR,
                    REG_EN_RXADDR(ERX_P0=1).to_int())
                await nrf24l01_iface.write_register_wide(ADDR_RX_ADDR_Pn(0), args.address)
            else:
                await nrf24l01_iface.write_register(ADDR_EN_AA,
                    REG_EN_AA().to_int()) # disable on all pipes to release EN_CRC
                await nrf24l01_iface.write_register(ADDR_SETUP_RETR,
                    REG_SETUP_RETR().to_int())
            if en_dpl:
                await nrf24l01_iface.write_register(ADDR_DYNPD,
                    REG_DYNPD(DPL_P0=1).to_int())

            await nrf24l01_iface.flush_tx_all()
            await nrf24l01_iface.write_register(ADDR_CONFIG,
                REG_CONFIG(PRIM_RX=0, PWR_UP=1, CRCO=crco, EN_CRC=en_crc).to_int())

            await nrf24l01_iface.write_tx_payload(args.payload,
                ack=not args.compat_framing and not args.no_ack)

            await nrf24l01_iface.enable()
            try:
                status = await nrf24l01_iface.poll_tx_status()
            finally:
                await nrf24l01_iface.disable()

            if status.TX_DS:
                if args.no_ack or args.compat_framing:
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
                await nrf24l01_iface.write_register(ADDR_STATUS,
                    REG_STATUS(MAX_RT=1).to_int())

        if args.operation in ("receive", "monitor"):
            if len(args.address) != args.address_width:
                raise RadioNRF24L01Error("Length of address does not match address width")
            if en_dpl:
                if args.length is not None:
                    raise RadioNRF24L01Error(
                        "Either --dynamic-length or --length may be specified")
            else:
                if args.length is None:
                    raise RadioNRF24L01Error(
                        "One of --dynamic-length or --length must be specified")

        if args.operation == "receive":
            if en_aa:
                await nrf24l01_iface.write_register(ADDR_EN_AA,
                    REG_EN_AA(ENAA_P0=1).to_int())
            else:
                await nrf24l01_iface.write_register(ADDR_EN_AA,
                    REG_EN_AA().to_int()) # disable on all pipes to release EN_CRC
            await nrf24l01_iface.write_register(ADDR_EN_RXADDR,
                REG_EN_RXADDR(ERX_P0=1).to_int())
            await nrf24l01_iface.write_register_wide(ADDR_RX_ADDR_Pn(0), args.address)
            if en_dpl:
                await nrf24l01_iface.write_register(ADDR_DYNPD,
                    REG_DYNPD(DPL_P0=1).to_int())
            else:
                await nrf24l01_iface.write_register(ADDR_RX_PW_Pn(0), args.length)

            await nrf24l01_iface.flush_rx_all()
            await nrf24l01_iface.write_register(ADDR_CONFIG,
                REG_CONFIG(PRIM_RX=1, PWR_UP=1, CRCO=crco, EN_CRC=en_crc).to_int())

            await nrf24l01_iface.enable()
            try:
                while True:
                    status = REG_STATUS.from_int(
                        await nrf24l01_iface.read_register(ADDR_STATUS))
                    if status.RX_P_NO == 0b111:
                        await nrf24l01_iface.poll_rx_status()
                        continue

                    if en_dpl:
                        length = await nrf24l01_iface.read_rx_payload_length()
                        if length > 32:
                            self.logger.warn("corrupted packet received with length %d",
                                             length)
                            await nrf24l01_iface.flush_rx()
                            continue
                    else:
                        length = args.length

                    payload = await nrf24l01_iface.read_rx_payload(length)
                    self.logger.info("packet received: %s", dump_hex(payload))

                    if not args.repeat:
                        break
            finally:
                await nrf24l01_iface.disable()

        if args.operation == "monitor":
            if en_aa:
                overhead = 2 + args.crc_width
                if en_dpl:
                    length = 32 + overhead
                else:
                    length = args.length + overhead
            else:
                length = args.length
            if length > 32:
                self.logger.warn("packets may be up to %d bytes long, but only %d bytes will "
                                 "be captured", length, 32)

            await nrf24l01_iface.write_register(ADDR_FEATURE,
                REG_FEATURE(EN_DPL=0, EN_DYN_ACK=0).to_int())
            await nrf24l01_iface.write_register(ADDR_EN_AA,
                REG_EN_AA().to_int()) # disable on all pipes to release EN_CRC
            await nrf24l01_iface.write_register(ADDR_EN_RXADDR,
                REG_EN_RXADDR(ERX_P0=1).to_int())
            await nrf24l01_iface.write_register_wide(ADDR_RX_ADDR_Pn(0), args.address)
            await nrf24l01_iface.write_register(ADDR_RX_PW_Pn(0), min(32, length))

            await nrf24l01_iface.flush_rx_all()
            if en_aa:
                await nrf24l01_iface.write_register(ADDR_CONFIG,
                    REG_CONFIG(PRIM_RX=1, PWR_UP=1, CRCO=CRCO._1_BYTE, EN_CRC=0).to_int())
            else:
                await nrf24l01_iface.write_register(ADDR_CONFIG,
                    REG_CONFIG(PRIM_RX=1, PWR_UP=1, CRCO=crco, EN_CRC=en_crc).to_int())

            await nrf24l01_iface.enable()
            try:
                while True:
                    status = REG_STATUS.from_int(
                        await nrf24l01_iface.read_register(ADDR_STATUS))
                    if status.RX_P_NO == 0b111:
                        await nrf24l01_iface.poll_rx_status()
                        continue

                    payload = await nrf24l01_iface.read_rx_payload(length)
                    if en_aa:
                        dyn_length = payload[0] >> 2
                        packet_id  = payload[0] & 0b11
                        no_ack     = payload[1] >> 7
                        data_crc   = bytes([
                            ((payload[1 + n + 0] << 1) & 0b1111111_0) |
                            ((payload[1 + n + 1] >> 7) & 0b0000000_1)
                            for n in range(len(payload) - 2)
                        ])

                        if dyn_length == 0:
                            data, crc = b"", data_crc
                            payload_msg = "(ACK)"
                        elif en_dpl:
                            data, crc = data_crc[:dyn_length], data_crc[dyn_length:]
                            payload_msg = data.hex()
                        else:
                            data, crc = data_crc[:args.length], data_crc[args.length:]
                            payload_msg = data.hex()

                        if len(crc) < args.crc_width:
                            crc_msg = " (CRC?)"
                        elif args.crc_width in (1, 2):
                            if args.crc_width == 1:
                                crc_func = crc8_nrf24l
                            else:
                                crc_func = crc16_nrf24l
                            crc_actual   = int.from_bytes(crc[:args.crc_width], "big")
                            crc_expected = crc_func(bytes(reversed(args.address)) + payload,
                                bits=len(args.address) * 8 + 9 + len(data) * 8)
                            if crc_actual != crc_expected:
                                crc_msg = " (CRC!)"
                            else:
                                crc_msg = ""
                        else:
                            crc_msg = ""

                        self.logger.info("packet received: PID=%s %s%s",
                                         "{:02b}".format(packet_id), payload_msg, crc_msg)
                    else:
                        self.logger.info("packet received: %s", dump_hex(payload))

                    if not args.repeat:
                        break
            finally:
                await nrf24l01_iface.disable()

# -------------------------------------------------------------------------------------------------

class RadioNRF24L01AppletTestCase(GlasgowAppletTestCase, applet=RadioNRF24L01Applet):
    @synthesis_test
    def test_build(self):
        self.assertBuilds()
