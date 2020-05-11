# Ref: LoRaWAN 1.0.3 Specification
# Accession: G00052

from collections import namedtuple
import time
import enum
import random
import struct
from Crypto.Hash import CMAC
from Crypto.Cipher import AES
import datetime
import re
import asyncio
import math

from ..support.bitstruct import bitstruct
from .semtech_udp_forwarder import SemtechPacketForwarder, SemtechPacket
from ..arch.sx1272.apis import RadioSX1272APILoRa
from ..arch.sx1272 import regs_lora

__all__ = [
    "EU863870_PARAMETERS",
    "LoRa_Device_API", "LoRaWAN_Node", "LoRaWAN_Gateway", "SX1272_LoRa_Device_API"
]

DevAddr = bitstruct("DevAddr", 32, [
    ("NwkAddr", 25),
    ("NwkID", 7)
])

class MTYPE(enum.IntEnum):
    _JOIN_REQUEST           = 0b000
    _JOIN_ACCEPT            = 0b001
    _UNCONFIRMED_DATA_UP    = 0b010
    _UNCONFIRMED_DATA_DOWN  = 0b011
    _CONFIRMED_DATA_UP      = 0b100
    _CONFIRMED_DATA_DOWN    = 0b101
    _RFU                    = 0b110
    _PROPIETARY             = 0b111

class MAJOR(enum.IntEnum):
    _LORAWAN_R1 = 0b00
    _RFUa        = 0b01
    _RFUb        = 0b10
    _RFUc        = 0b11

MacHDR = bitstruct("MacHDR", 8, [
    ("Major", 2),
    ("RFU", 3),
    ("MType", 3)
])

DLsettings = bitstruct("DLsettings", 8, [
    ("RX2DataRate", 4),
    ("RX1DRoffset", 3),
    ("RFU", 1)
])

PhyPayload = namedtuple('PhyPayload', 'MacHDR MacPayload MIC')
MacPayload = namedtuple('MacPayload', 'FrameHDR FPort FramePayload')
FrameHeader = namedtuple('FrameHeader', 'DevAddr FCtrl FCnt FOpts')
JoinRequest = namedtuple('JoinRequest', 'AppEUI DevEUI DevNonce')
JoinAccept = namedtuple('JoinAccept', 'AppNonce NetID DevAddr DLSettings RxDelay CFList')

FCtrlDownlink = bitstruct("FCtrlDownlink", 8, [
    ("FOptsLen", 4),
    ("FPending", 1),
    ("ACK", 1),
    ("RFU", 1),
    ("ADR", 1)
])

FCtrlUplink = bitstruct("FCtrlUplink", 8, [
    ("FOptsLen", 4),
    ("ClassB", 1),
    ("ACK", 1),
    ("ADRACKReq", 1),
    ("ADR", 1)
])

class MODULATION(enum.IntEnum):
    _LoRa = 0
    _GFSK = 1

class BITRATE(enum.IntEnum):
    _DR0 = 0
    _DR1 = 1
    _DR2 = 2
    _DR3 = 3
    _DR4 = 4
    _DR5 = 5
    _DR6 = 6
    _DR7 = 7
    _DR8 = 8
    _DR9 = 9
    _DR10 = 10
    _DR11 = 11
    _DR12 = 12
    _DR13 = 13
    _DR14 = 14
    _DR15 = 15

DataRate = namedtuple('DataRate', 'Modulation SpreadingFactor Bandwidth')
PreambleFormat = namedtuple('PreambleFormat', 'Modulation SyncWord PreambleLength')
ChannelConfiguration = namedtuple('ChannelConfiguration', 'Modulation Frequency Datarates MaxDuty')

class REGION_PARAMETERS:
    def __init__(self):
        self.PREAMBLE_FORMATS = None
        self.DATARATES = None
        self.CHANNEL_CONF = None
        self.MAX_MAC_PALOAD_SIZE = None
        self.RX1_DL_DATARATE = None
        self.RECEIVE_DELAY1_S = None
        self.RECEIVE_DELAY2_S = None
        self.JOIN_ACCEPT_DELAY1_S = None
        self.JOIN_ACCEPT_DELAY2_S = None
        self.MAX_FCNT_GAP = None
        self.ADR_ACK_LIMIT = None
        self.ADR_ACK_DELAY = None

    def get_ack_timeout(self):
        pass

    def get_join_req_conf(self, chn, datr):
        pass

    def get_rx1_conf(self, up_chn, up_datr):
        pass

    def get_rx2_conf(self, up_chn, up_datr):
        pass


class EU863870_PARAMETERS(REGION_PARAMETERS):
    def __init__(self):
        self.PREAMBLE_FORMATS = [
            PreambleFormat(MODULATION._LoRa, 0x34, 8),
            PreambleFormat(MODULATION._GFSK, 0xC194C1, 5)
        ]
        self.DATARATES = [
            DataRate(MODULATION._LoRa, 12, 125e3),
            DataRate(MODULATION._LoRa, 11, 125e3),
            DataRate(MODULATION._LoRa, 10, 125e3),
            DataRate(MODULATION._LoRa, 9,  125e3),
            DataRate(MODULATION._LoRa, 8,  125e3),
            DataRate(MODULATION._LoRa, 7,  125e3),
            DataRate(MODULATION._LoRa, 7,  250e3),
            DataRate(MODULATION._GFSK, 0, 50e3)
        ]
        self.CHANNEL_CONF = [
            ChannelConfiguration(MODULATION._LoRa, 868.10e6, [BITRATE._DR0, BITRATE._DR1, BITRATE._DR2, BITRATE._DR3, BITRATE._DR4, BITRATE._DR5], 0.01),
            ChannelConfiguration(MODULATION._LoRa, 868.30e6, [BITRATE._DR0, BITRATE._DR1, BITRATE._DR2, BITRATE._DR3, BITRATE._DR4, BITRATE._DR5], 0.01),
            ChannelConfiguration(MODULATION._LoRa, 868.50e6, [BITRATE._DR0, BITRATE._DR1, BITRATE._DR2, BITRATE._DR3, BITRATE._DR4, BITRATE._DR5], 0.01),
            ChannelConfiguration(MODULATION._LoRa, 869.525e6, [BITRATE._DR0, BITRATE._DR1, BITRATE._DR2, BITRATE._DR3, BITRATE._DR4, BITRATE._DR5], 0.01)
        ]
        self.MAX_MAC_PALOAD_SIZE = [59, 59, 59, 123, 230, 230, 230, 230]
        self.RX1_DL_DATARATE = [
            [BITRATE._DR0, BITRATE._DR0, BITRATE._DR0, BITRATE._DR0, BITRATE._DR0, BITRATE._DR0],
            [BITRATE._DR1, BITRATE._DR0, BITRATE._DR0, BITRATE._DR0, BITRATE._DR0, BITRATE._DR0],
            [BITRATE._DR2, BITRATE._DR1, BITRATE._DR0, BITRATE._DR0, BITRATE._DR0, BITRATE._DR0],
            [BITRATE._DR3, BITRATE._DR2, BITRATE._DR1, BITRATE._DR0, BITRATE._DR0, BITRATE._DR0],
            [BITRATE._DR4, BITRATE._DR3, BITRATE._DR2, BITRATE._DR1, BITRATE._DR0, BITRATE._DR0],
            [BITRATE._DR5, BITRATE._DR4, BITRATE._DR3, BITRATE._DR2, BITRATE._DR1, BITRATE._DR0],
            [BITRATE._DR6, BITRATE._DR5, BITRATE._DR4, BITRATE._DR3, BITRATE._DR2, BITRATE._DR1],
            [BITRATE._DR7, BITRATE._DR6, BITRATE._DR5, BITRATE._DR4, BITRATE._DR3, BITRATE._DR2],
        ]
        self.RECEIVE_DELAY1_S = 1
        self.RECEIVE_DELAY2_S = 2
        self.JOIN_ACCEPT_DELAY1_S = 5
        self.JOIN_ACCEPT_DELAY2_S = 6
        self.MAX_FCNT_GAP = 16384
        self.ADR_ACK_LIMIT = 64
        self.ADR_ACK_DELAY = 32

    def get_ack_timeout(self):
        return 2 # TODO +/- 1s random

    def get_join_req_conf(self, chn, datr):
        return (chn, datr)

    def get_rx1_conf(self, up_chn, up_datr):
        return (up_chn, up_datr)

    def get_rx2_conf(self, up_chn, up_datr):
        return (3, 0)

class LoRa_Device_API:
    async def configure(self, freq, bw, sf, pwr, codr, syncword, prelength):
        pass

    async def transmit(self, payload):
        pass

    async def receive(self, symTimeout, onpayload):
        pass

    async def listen(self, onpayload):
        pass

    async def sleep(self):
        pass

    async def wakeup(self):
        pass

class LoRaWAN_Device:
    def __init__(self, api, region):
        assert isinstance(api, LoRa_Device_API)
        self.api = api
        self.rfparams = region()
        self.rfconf = None
        self.initTmst = int(datetime.datetime.utcnow().timestamp() * 1e6)

    def _get_symbol_period(self, datr):
        bw = self.rfparams.DATARATES[datr].Bandwidth
        sf = self.rfparams.DATARATES[datr].SpreadingFactor
        return (2 ** sf) / bw

    def _get_symbol_timeout(self, timeout_s, datr):
        ts = self._get_symbol_period(datr)
        return math.ceil(timeout_s / ts)

    def _get_timestamp(self):
        return int(datetime.datetime.utcnow().timestamp() * 1e6) - self.initTmst

    def _pad_16(self, data):
        n = len(data) % 16
        if n:
            data += bytes(16 - n)
        return data

    def _byte_xor(self, ba1, ba2):
        return bytes([_a ^ _b for _a, _b in zip(ba1, ba2)])

    def validate_rf_params(self, freq, bw, sf, pwr, codr):
        channel_conf = None

        for chn in self.rfparams.CHANNEL_CONF:
            if chn.Frequency == freq:
                channel_conf = chn
                break

        _bw = None
        _sf = None
        if channel_conf != None:
            for drate in channel_conf.Datarates:
                drate = self.rfparams.DATARATES[drate]
                if drate.SpreadingFactor == sf and drate.Bandwidth == bw:
                    _bw = bw
                    _sf = sf
                    break
        else:
            freq = None

        if pwr > 13:
            pwr = None # TODO PA_BOOST 20 dBm

        if codr not in range(5, 9):
            codr = None
        return (freq, _bw, _sf, pwr, codr)
        
    async def configure_by_channel(self, channel, drate):
        freq = self.rfparams.CHANNEL_CONF[channel].Frequency
        bw = self.rfparams.DATARATES[drate].Bandwidth
        sf = self.rfparams.DATARATES[drate].SpreadingFactor
        pwr = 13 # dBm
        codr = 5 # 4/5
        self.rfconf = (channel, drate)
        await self.configure(freq, bw, sf, pwr, codr)

    async def configure(self, freq, bw, sf, pwr, codr):
        freq, bw, sf, pwr, codr = self.validate_rf_params(freq, bw, sf, pwr, codr)
        if freq == None or bw == None or sf == None or pwr == None or codr == None:
            return False

        sword = self.rfparams.PREAMBLE_FORMATS[0].SyncWord
        plength = self.rfparams.PREAMBLE_FORMATS[0].PreambleLength
        await self.api.configure(freq, bw, sf, pwr, codr, sword, plength)
        return True


class LoRaWAN_Node(LoRaWAN_Device):
    def __init__(self, api, region, appkey, deveui, appeui, logger, frame_cb):
        super().__init__(api, region)
        self.__AppKey = appkey.to_bytes(16, byteorder='big')
        self.__DevEUI = deveui
        self.__AppEUI = appeui
        self.logger = logger
        self.__fcnt = 0
        self.__ackflagup = False
        self.__ackflagdwn = False
        self.__frame_cb = frame_cb
        random.seed()

    def __gen_join_request(self):
        machdr = MacHDR(MTYPE._JOIN_REQUEST, 0, MAJOR._LORAWAN_R1)
        nonce = random.getrandbits(16)
        reqpl = struct.pack('QQH', self.__AppEUI, self.__DevEUI, nonce)
        phypl = machdr.to_bytes()
        phypl += reqpl
        cmac = CMAC.new(self.__AppKey, ciphermod=AES)
        cmac.update(phypl)
        cmac = cmac.digest()[0:4]
        phypl += cmac
        return phypl

    def __process_join_accept(self, data, crcerr, snr, rssi, codr):
        if data == None:
            return False

        aes = AES.new(self.__AppKey, AES.MODE_ECB)

        tmp = aes.encrypt(data[1:])
        cmac = CMAC.new(self.__AppKey, ciphermod=AES)
        mic = cmac.update(bytes([data[0]]) + tmp[0:-4]).digest()[0:4]
        if mic != tmp[-4:]:
            return False

        jacc = tmp[0:-4]
        appNonce = tmp[0:3]
        netId = tmp[3:6]
        one = (1).to_bytes(1, 'little')
        two = (2).to_bytes(1, 'little')
        self.__DevAddr = DevAddr.from_int(int.from_bytes(jacc[6:10], 'little'))
        self.__DLsettings = DLsettings.from_int(int(jacc[10]))

        self.logger.debug("Download Settings: {}".format(self.__DLsettings))

        nkey = one + appNonce + netId + self.__devNonce
        nkey = self._pad_16(nkey)
        self.__NwkSKey = aes.encrypt(nkey)

        akey = two + appNonce + netId + self.__devNonce
        akey = self._pad_16(akey)
        self.__AppSKey = aes.encrypt(akey)

        self.logger.debug("Joined network. DevAddr: {}".format(self.__DevAddr))

        return True

    async def join_network(self):
        joinreq = self.__gen_join_request()
        self.__devNonce = joinreq[17:19]
        chn, datr = self.rfparams.get_join_req_conf(*self.rfconf)
        await self.configure_by_channel(chn, datr)

        self.logger.debug("Joining network ...")
        await self.api.transmit(joinreq)
        await asyncio.sleep(self.rfparams.JOIN_ACCEPT_DELAY1_S)
        chn1, datr1 = self.rfparams.get_rx1_conf(chn, datr)
        # Time Between Windows
        tbw = self.rfparams.JOIN_ACCEPT_DELAY2_S - self.rfparams.JOIN_ACCEPT_DELAY1_S
        # Symbol period
        symTimeout_s = 0.7 * tbw
        symTimeout = self._get_symbol_timeout(symTimeout_s, datr1)
        await self.configure_by_channel(chn1, datr1)
        self.logger.debug("Listen RX1 ...")
        joined = await self.api.receive(symTimeout, self.__process_join_accept)

        if joined:
            return joined

        await asyncio.sleep(self.rfparams.JOIN_ACCEPT_DELAY2_S - self.rfparams.JOIN_ACCEPT_DELAY1_S - symTimeout_s)
        chn2, datr2 = self.rfparams.get_rx2_conf(chn, datr)
        # Symbol period
        symTimeout = self._get_symbol_timeout(symTimeout_s, datr2)
        await self.configure_by_channel(chn2, datr2)
        self.logger.debug("Listen RX2 ...")
        joined = await self.api.receive(symTimeout, self.__process_join_accept)
        return joined

    def __create_encryption_sequence(self, payload, dir, fcnt, key):
        aes = AES.new(key, AES.MODE_ECB)
        k = math.ceil(len(payload)/16)
        S = bytes(0)
        for i in range(1, k + 1):
            A = struct.pack('<BIBIIBB', 1, 0, dir, self.__DevAddr.to_int(), fcnt, 0, i)
            S += aes.encrypt(A)
        return S

    def __encrypt_uplink(self, payload, key):
        S = self.__create_encryption_sequence(payload, 0, self.__fcnt, key)
        epayload = self._pad_16(payload)
        epayload = self._byte_xor(epayload, S)
        return epayload[0:len(payload)]

    def __decrypt_downlink(self, payload, fcnt, key):
        S = self.__create_encryption_sequence(payload, 1, fcnt, key)
        dpayload = self._pad_16(payload)
        dpayload = self._byte_xor(dpayload, S)
        return dpayload[0:len(payload)]

    def __compute_mic(self, msg):
        B0 = struct.pack('<BIBIIBB', 0x49, 0, 0, self.__DevAddr.to_int(), self.__fcnt, 0, len(msg))
        cmac = CMAC.new(self.__NwkSKey, ciphermod=AES)
        cmac.update(B0 + msg)
        return cmac.digest()[0:4]

    async def transmit(self, port, payload, confirmed):
        self.logger.debug("Transmitting ...")
        chn, datr = self.rfconf
        M = self.rfparams.MAX_MAC_PALOAD_SIZE[datr]
        fctrlup = FCtrlUplink()
        fctrlup.FOptsLen = 0
        fctrlup.ClassB = 0
        fctrlup.ACK = 0
        fctrlup.ADR = 0
        fhdr = FrameHeader(self.__DevAddr.to_int(), fctrlup.to_int(), self.__fcnt, None)
        fhdr = struct.pack('<IBH', *list(fhdr)[0:-1])
        assert len(payload) <= M - 1 - len(fhdr)
        key = self.__NwkSKey if port == 0 else self.__AppSKey
        payload = self.__encrypt_uplink(payload, key)
        mpl = fhdr + bytes([port]) + payload
        mhdr = MacHDR()
        mhdr.MType = MTYPE._CONFIRMED_DATA_UP if confirmed else MTYPE._UNCONFIRMED_DATA_UP
        self.__ackflagdwn = True if confirmed else False
        mhdr.RFU = 0
        mhdr.Major = MAJOR._LORAWAN_R1
        phypl = bytes([mhdr.to_int()]) + mpl
        phypl += self.__compute_mic(phypl)
        await self.api.transmit(phypl)
        self.__fcnt += 1
        chn1, datr1 = self.rfparams.get_rx1_conf(chn, datr)
        await self.configure_by_channel(chn1, datr1)
        # Time Between Windows
        tbw = self.rfparams.RECEIVE_DELAY2_S - self.rfparams.RECEIVE_DELAY1_S
        # Symbol period
        symTimeout_s = 0.7 * tbw
        symTimeout = self._get_symbol_timeout(symTimeout_s, datr1)
        await asyncio.sleep(self.rfparams.RECEIVE_DELAY1_S)
        self.logger.debug("Listen RX1 ...")
        rcvok = await self.api.receive(symTimeout, self.mac_process)
        if rcvok:
            return
        chn2, datr2 = self.rfparams.get_rx2_conf(chn, datr)
        # Overwrite with DLsettings
        datr2 = self.__DLsettings.RX2DataRate
        await self.configure_by_channel(chn2, datr2)
        symTimeout = self._get_symbol_timeout(symTimeout_s, datr2)
        await asyncio.sleep(self.rfparams.RECEIVE_DELAY2_S - self.rfparams.RECEIVE_DELAY1_S - symTimeout_s)
        self.logger.debug("Listen RX2 ...")
        await self.api.receive(1000, self.mac_process)
        # Go back to known configuration
        await self.configure_by_channel(chn, datr)

    def mac_process(self, payload, crcerr, snr, rssi, codr):
        if payload == None:
            return False
        self.logger.debug("Payload recived: {}".format(payload))
        if len(payload) < 6:
            self.logger.error("Payload is smaller than the minimum size")
            return False
        hdr = payload[0]
        mic = payload[-4:]
        payload = payload[1:-4]
        hdr = MacHDR.from_int(hdr)
        if hdr.Major != MAJOR._LORAWAN_R1:
            return False
        self.logger.debug("Received header: {}".format(hdr))
        self.logger.debug("Received MIC: {}".format(mic))
        if hdr.MType == MTYPE._CONFIRMED_DATA_DOWN:
            self.__ackflagup = True

        return self.frame_process(payload)

    def frame_process(self, macpayload):
        devAddr = DevAddr.from_int(int.from_bytes(macpayload[0:4], 'little'))

        if devAddr != self.__DevAddr:
            self.logger.debug("Received frame with incorrect address")
            return False

        fCtrl = FCtrlDownlink.from_int(macpayload[4])
        if fCtrl.ACK == 1:
            self.__ackflagdwn = False
        fCnt = int.from_bytes(macpayload[5:7], 'little')
        optslen = fCtrl.FOptsLen
        fOpts = macpayload[7:7 + optslen]

        fhdr = FrameHeader(devAddr, fCtrl, fCnt, fOpts)

        n = len(macpayload) - 7 - optslen

        fport = None
        fpl = None
        if n > 0:
            fport = macpayload[7 + optslen]
            key = self.__NwkSKey if fport == 0 else self.__AppSKey
            fpl = macpayload[8 + optslen:]
            fpl = self.__decrypt_downlink(fpl, fCnt, key)

        self.__frame_cb(fport, fpl)
        return True


class LoRaWAN_Gateway(LoRaWAN_Device):
    def __init__(self, api, region, server, port, eui, logger):
        super().__init__(api, region)
        self.pkt_fwd = SemtechPacketForwarder(server, port, eui, self.get_txack_error, self.initTmst, logger)
        self.logger = logger

    def get_txack_error(self, pkt):
        # Packets are sometime late-ish from the UDP forwarder, here we give a 0.5 s margin
        # These two lines can be commented out to receive all packets
        #if pkt.tmst < self._get_timestamp() - 1 * 1e6:
        #    return 'TOO_LATE'
        freq = pkt.freq * 1e6
        m = re.match(r'SF(\d+)BW(\d+)', pkt.datr)
        sf = int(m.groups()[0])
        bw = int(m.groups()[1]) * 1e3
        codr = int(pkt.codr[-1])
        pwr = pkt.pwr
        freq, bw, sf, _, codr = self.validate_rf_params(freq, bw, sf, pwr, codr)
        if bw == None or freq == None:
            return 'TX_FREQ'
        return 'NONE'

    async def main(self):
        # Save initial configuration
        chn1, datr1 = self.rfconf
        # Create parameters to configure each time we listen
        rxfreq = self.rfparams.CHANNEL_CONF[chn1].Frequency
        rxbw = self.rfparams.DATARATES[datr1].Bandwidth
        rxsf = self.rfparams.DATARATES[datr1].SpreadingFactor
        rxpwr = 13 # Not used in rx, but we need a param to configure
        # Timeout for each receive
        symTimeout_s = 0.25
        fastTimeout_s = 7
        self.logger.info("Listening ...")
        while True:
            # 1. Configure RF parameters 
            symTimeout = self._get_symbol_timeout(symTimeout_s, datr1)
            await self.configure_by_channel(chn1, datr1)
            # 2. Listen with a given symbol timeout
            payload, crcerr, snr, rssi, codr = await self.api.receive(symTimeout)
            if None != payload:
                datr = 'SF{}BW{}'.format(rxsf, round(rxbw/1e3))
                codr = '4/{}'.format(codr)
                chan = 0
                freq = rxfreq
                pkt = SemtechPacket(0, freq, chan, -1 if crcerr == 1 else 1, datr, rxpwr, codr, rssi, snr, payload)
                self.logger.info("Device Uplink : {} {}".format(self._get_timestamp(), pkt))
                # 3. Send packet to UDP forwarder
                self.pkt_fwd.put_dev_uplink(pkt)
                # Set fast timeout to send gateway downlink packets more precisely
                symTimeout_s = 0.05

            if fastTimeout_s <= 0:
                fastTimeout_s = 7
                symTimeout_s = 0.25
            else:
                fastTimeout_s -= symTimeout_s

            # 4. Execute forwarder process
            await self.pkt_fwd.main()

            # 5. Get any downlink packet
            appData = self.pkt_fwd.get_dev_downlink()
            later = []
            now = []
            while appData != None:
                # 6. Send packet now or later based on timestamp
                if appData.tmst <= self._get_timestamp():
                    now.append(appData)
                else:
                    later.append(appData)
                appData = self.pkt_fwd.get_dev_downlink()

            for pkt in now:
                self.logger.info("Gateway Downlink : {} {}".format(self._get_timestamp(), pkt))
                freq = pkt.freq * 1e6
                m = re.match(r'SF(\d+)BW(\d+)', pkt.datr)
                sf = int(m.groups()[0])
                bw = int(m.groups()[1]) * 1e3
                codr = int(pkt.codr[-1])
                await self.api.configure(freq, bw, sf, 13, codr)
                await self.api.transmit(pkt.payload)

            for pkt in later:
                # 7. If the packet is to be sent later, put in back in the queue
                self.pkt_fwd.put_dev_downlink(pkt)
        

class SX1272_LoRa_Device_API(LoRa_Device_API):
    def __init__(self, iface, logger):
        self.lower = RadioSX1272APILoRa(iface, logger)
        self.logger = logger

    async def __get_pkt_snr(self):
        regsnr = await self.lower.get_pkt_snr()
        return regsnr/4

    async def __get_pkt_rssi(self, snr):
        regrssi = await self.lower.get_pkt_rssi()
        if snr >= 0:
            return -139 + regrssi
        else:
            return -139 + regrssi + snr

    async def configure(self, freq, bw, sf, pwr, codr, syncword=0x34, prelength=8):
        await self.lower.set_opmode_mode(regs_lora.MODE._SLEEP)
        await self.lower.set_opmode_lora(regs_lora.LONGRANGEMODE._LORA)
        await self.lower.set_modem_config_1_rxcrcon(1)
        await self.lower.set_sync_word(syncword)
        await self.lower.set_preamble_length(prelength)
        bw = {
            125e3: regs_lora.MODEMBW._BW_125kHz,
            250e3: regs_lora.MODEMBW._BW_250kHz
        }[bw]
        sf = {
            7: regs_lora.SPREADINGFACTOR._SPREAD_7,
            8: regs_lora.SPREADINGFACTOR._SPREAD_8,
            9: regs_lora.SPREADINGFACTOR._SPREAD_9,
            10: regs_lora.SPREADINGFACTOR._SPREAD_10,
            11: regs_lora.SPREADINGFACTOR._SPREAD_11,
            12: regs_lora.SPREADINGFACTOR._SPREAD_12,
        }[sf]
        frf = math.floor((freq * (2**19)) / 32e6)
        await self.lower.set_modem_config_1_bw(bw)
        codr = {
            5: regs_lora.CODINGRATE._4_OVER_5,
            6: regs_lora.CODINGRATE._4_OVER_6,
            7: regs_lora.CODINGRATE._4_OVER_7,
            8: regs_lora.CODINGRATE._4_OVER_8,
        }[codr]
        await self.lower.set_modem_config_1_codingrate(codr)
        if sf == regs_lora.SPREADINGFACTOR._SPREAD_12 or sf == regs_lora.SPREADINGFACTOR._SPREAD_11:
            await self.lower.set_modem_config_1_ldoptim(1)
        else:
            await self.lower.set_modem_config_1_ldoptim(0)
        await self.lower.set_modem_config_2_spreading(sf)
        await self.lower.set_frf(frf)
        await self.lower.set_pa_config_outpower(pwr + 1) # RFIO pin
        await self.lower.set_opmode_mode(regs_lora.MODE._STDBY)

    async def transmit(self, payload):
        addr = await self.lower.get_fifo_tx_base_addr()
        await self.lower.set_fifo_addr_ptr(addr)
        await self.lower.set_fifo(payload)
        await self.lower.set_payload_length(len(payload))
        await self.lower.set_opmode_mode(regs_lora.MODE._TX)
        irqs = await self.lower.get_irq_flags()
        while irqs.TX_DONE != 1:
            await asyncio.sleep(0.1)
            irqs = await self.lower.get_irq_flags()
        self.logger.debug("Sent payload {}".format(payload))

    async def receive(self, symTimeout = 15, onpayload = None):
        data = None
        crcerr = None
        snr = None
        rssi = None
        codr = None

        await self.lower.set_symbol_timeout(symTimeout)
        await self.lower.clear_irq_flags()
        addr = await self.lower.get_fifo_rx_base_addr()
        await self.lower.set_fifo_addr_ptr(addr)
        await self.lower.set_opmode_mode(regs_lora.MODE._RXSINGLE)
        irqs = await self.lower.get_irq_flags()
        while irqs.RX_DONE == 0 and irqs.RX_TIMEOUT == 0:
            await asyncio.sleep(0.1)
            irqs = await self.lower.get_irq_flags()

        nb = await self.lower.get_rx_nb_bytes()

        if irqs.RX_TIMEOUT != 1 and nb != 0:
            addr = await self.lower.get_fifo_rx_curr_addr()
            await self.lower.set_fifo_addr_ptr(addr)
            data = await self.lower.get_fifo(nb)
            crcerr = irqs.PAYLOAD_CRC_ERROR
            snr = await self.__get_pkt_snr()
            rssi = await self.__get_pkt_rssi(snr)
            codr = await self.lower.get_modem_stat()
            codr = {
                regs_lora.CODINGRATE._4_OVER_5: 5,
                regs_lora.CODINGRATE._4_OVER_6: 6,
                regs_lora.CODINGRATE._4_OVER_7: 7,
                regs_lora.CODINGRATE._4_OVER_8: 8,
            }[codr.RX_CODING_RATE]

        if onpayload != None:
            return onpayload(data, crcerr, snr, rssi, codr)
        else:
            return data, crcerr, snr, rssi, codr

    async def listen(self, onpayload):
        await self.lower.clear_irq_flags()
        addr = await self.lower.get_fifo_rx_base_addr()
        await self.lower.set_fifo_addr_ptr(addr)
        await self.lower.set_opmode_mode(regs_lora.MODE._RXCONT)
        while True:
            await self.lower.clear_irq_flags()
            irqs = await self.lower.get_irq_flags()
            while irqs.RX_DONE == 0:
                await asyncio.sleep(0.1)
                irqs = await self.lower.get_irq_flags()
            nb = await self.lower.get_rx_nb_bytes()
            addr = await self.lower.get_fifo_rx_curr_addr()
            await self.lower.set_fifo_addr_ptr(addr)

            data = await self.lower.get_fifo(nb)
            crcerr = irqs.PAYLOAD_CRC_ERROR
            snr = await self.__get_pkt_snr()
            rssi = await self.__get_pkt_rssi(snr)
            codr = await self.lower.get_modem_stat()
            codr = {
                regs_lora.CODINGRATE._4_OVER_5: 5,
                regs_lora.CODINGRATE._4_OVER_6: 6,
                regs_lora.CODINGRATE._4_OVER_7: 7,
                regs_lora.CODINGRATE._4_OVER_8: 8,
            }[codr.RX_CODING_RATE]

            onpayload(data, crcerr, snr, rssi, codr)

    async def sleep(self):
        await self.lower.set_opmode_mode(regs_lora.MODE._SLEEP)

    async def wakeup(self):
        await self.lower.set_opmode_mode(regs_lora.MODE._STDBY)