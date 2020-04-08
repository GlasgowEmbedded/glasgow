from collections import namedtuple
import socket
import random
import struct
import datetime
import math
import base64
import asyncio
import asyncio_dgram
import queue
import json

PROTOCOL_VERSION = 2

PKT_PUSH_DATA   = 0
PKT_PUSH_ACK    = 1
PKT_PULL_DATA   = 2
PKT_PULL_RESP   = 3
PKT_PULL_ACK    = 4
PKT_TX_ACK      = 5

SemtechPacket = namedtuple('SemtechPacket', 'tmst freq chan crc datr pwr codr rssi snr payload')

class SemtechPacketForwarder:
    def __init__(self, server, port, gw_eui, pkt_verif, initTmst, logger):
        self.ip = socket.gethostbyname(server)
        self.port = port
        self.gw_eui = gw_eui
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setblocking(False)
        self.sock.connect((self.ip, self.port))
        self.initTmst = initTmst
        self.logger = logger
        self.pkt_verif = pkt_verif

        self.rcv_pkt_cnt = 0        # All packets
        self.rcv_pkt_crc_cnt = 0    # Valid CRC
        self.fwd_pkt_cnt = 0
        self.fwd_pkt_cnt_ack = 0
        self.pct_pkt_ack = 100
        self.rcv_downlinks = 0
        self.emitted = 0

        self.packets_dict = {}

        self.__devDownlinkQueue = queue.SimpleQueue()
        self.__devUplinkQueue = queue.SimpleQueue()

    def __create_pkt(self, pkt):
        tmst = '"tmst":{}'.format(int(datetime.datetime.utcnow().timestamp() * 1e6) - self.initTmst)
        freq = '"freq":{}'.format(pkt.freq/1e6)
        chan = '"chan":{}'.format(pkt.chan)
        rfch = '"rfch":0'
        stat = '"stat":{}'.format(pkt.crc)
        modu = '"modu":"LORA"'
        datr = '"datr":"{}"'.format(pkt.datr)
        codr = '"codr":"{}"'.format(pkt.codr)
        rssi = '"rssi":{}'.format(math.floor(pkt.rssi))
        lsnr = '"lsnr":{}'.format(pkt.snr)
        size = '"size":{}'.format(len(pkt.payload))
        data = '"data":"{}"'.format(base64.b64encode(pkt.payload).decode())

        buf = ','.join((tmst, freq, chan, rfch, stat, modu, datr, codr, rssi, lsnr, size, data))
        return '{'+buf+'}'

    def __create_stat(self):
        time = '"time":"{}"'.format(datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S GMT'))
        rxnb = '"rxnb":{}'.format(self.rcv_pkt_cnt)
        rxok = '"rxok":{}'.format(self.rcv_pkt_crc_cnt)
        rxfw = '"rxfw":{}'.format(self.fwd_pkt_cnt)
        ackr = '"ackr":{}'.format(self.pct_pkt_ack)
        dwnb = '"dwnb":{}'.format(self.rcv_downlinks)
        txnb = '"txnb":{}'.format(self.emitted)

        buf = ','.join((time, rxnb, rxok, rxfw, ackr, dwnb, txnb))
        return '"stat":{'+buf+'}'

    def __create_rxpk(self, pkts):
        if len(pkts) == 0:
            return ''

        buf = '"rxpk":['
        for pkt in pkts:
            buf += self.__create_pkt(pkt) + ','
        buf = buf[:-1]
        return buf+']'

    def __create_msg(self, pkts, stat):
        buf = '{'
        buf += self.__create_rxpk(pkts)
        if stat and len(pkts) > 0:
            buf += ','
        if stat:
            buf += self.__create_stat()
        buf += '}'
        return buf

    def __create_txack(self, nonce, error):
        data = struct.pack('>BHBQ',
            PROTOCOL_VERSION,
            nonce,
            PKT_TX_ACK, self.gw_eui)
        return data + '{{"tkpk_ack":{{"error":"{}"}}}}'.format(error).encode()

    def __process_app_downlink(self, payload):
        data = struct.unpack_from('>BBBB%ds' % (len(payload)-4), payload)
        header = data[0:4]
        nonce = int.from_bytes(header[1:3], 'little')
        snonce = format(nonce, 'X')

        if header[0] != PROTOCOL_VERSION:
            return

        if header[3] == PKT_PUSH_ACK and snonce in self.packets_dict:
            self.logger.debug("Semtech FWD Push Ack")
            del self.packets_dict[snonce]
            self.fwd_pkt_cnt_ack += 1
            return

        if header[3] == PKT_PULL_ACK and snonce in self.packets_dict:
            self.logger.debug("Semtech FWD Pull Ack")
            del self.packets_dict[snonce]
            return

        if header[3] == PKT_PULL_RESP:
            self.logger.debug("Semtech FWD Pull Resp")
            pkt = json.loads(data[4].decode('utf-8'))
            pkt = pkt['txpk']
            if 'imme' in pkt and pkt['imme']:
                pkt['tmst'] = int(datetime.datetime.utcnow().timestamp() * 1e6) - self.initTmst
            pkt = SemtechPacket(pkt['tmst'], pkt['freq'], 0, not pkt['ncrc'], pkt['datr'], pkt['powe'], pkt['codr'], 0, 0, base64.b64decode(pkt['data']))
            error = self.pkt_verif(pkt)
            self.logger.debug("Pkt {}, error {}".format(pkt, error))
            if error == 'NONE':
                self.__devDownlinkQueue.put(pkt)
            resp = self.__create_txack(nonce, error)
            self.sock.send(resp)

    def __process_dev_uplink(self, pkt):
        msg = self.__create_msg([pkt], True)
        data = struct.pack('>BBBBQ',
            PROTOCOL_VERSION,
            random.randint(0, 0xFF), random.randint(0, 0xFF),
            PKT_PUSH_DATA, self.gw_eui) + msg.encode()
        nonce = int.from_bytes(data[1:3], 'little')
        nonce = format(nonce, 'X')
        self.packets_dict[nonce] = 0
        self.logger.debug("App uplink: {}".format(data))
        self.sock.send(data)

    def __pull_data(self):
        data = struct.pack('>BBBBQ',
            PROTOCOL_VERSION,
            random.randint(0, 0xFF), random.randint(0, 0xFF),
            PKT_PULL_DATA, self.gw_eui
        )
        nonce = int.from_bytes(data[1:3], 'little')
        nonce = format(nonce, 'X')
        self.packets_dict[nonce] = 0
        self.sock.send(data)

    async def main(self):
        appDownlink = None
        try:
            appDownlink = self.__app_downlink_task()
        except:
            pass
        if None != appDownlink:
            self.__process_app_downlink(appDownlink)

        devUplink = None
        try:
            devUplink = self.__devUplinkQueue.get_nowait()
        except:
            pass
        if None != devUplink:
            self.__process_dev_uplink(devUplink)

        self.__pull_data()

    def __app_downlink_task(self):
        data = []
        try:
            data = self.sock.recv(2048)
        except:
            pass

        if len(data) > 0:
            return data
        else:
            return None

    def put_dev_uplink(self, data):
        self.__devUplinkQueue.put(data)

    def get_dev_downlink(self):
        data = None
        try:
            data = self.__devDownlinkQueue.get_nowait()
        except:
            pass
        return data

    def put_dev_downlink(self, pkt):
        self.__devDownlinkQueue.put(pkt)
