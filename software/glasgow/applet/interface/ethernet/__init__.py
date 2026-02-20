# Ref: IEEE Std 802.3-2018
# Accession: G00098

from typing import BinaryIO
from collections.abc import AsyncIterator
import time
import logging
import asyncio
import argparse

from amaranth import *
from amaranth.lib import wiring, stream
from amaranth.lib.wiring import In, Out
from amaranth.lib.crc.catalog import CRC32_ETHERNET

from glasgow.support.logging import dump_hex
from glasgow.support.os_network import OSNetworkInterface
from glasgow.arch.ieee802_3 import *
from glasgow.gateware import cobs, ethernet
from glasgow.protocol import snoop
from glasgow.abstract import AbstractAssembly, GlasgowPin
from glasgow.applet import GlasgowAppletV2
from glasgow.applet.control.mdio import ControlMDIOInterface


__all__ = ["EthernetComponent", "AbstractEthernetApplet", "GlasgowPin", "ControlMDIOInterface"]


class EthernetComponent(wiring.Component):
    i_stream:  In(stream.Signature(8))
    o_stream:  Out(stream.Signature(8))

    rx_bypass: In(1)
    tx_bypass: In(1)

    def __init__(self, driver):
        self._driver = driver

        super().__init__()

    def elaborate(self, platform):
        m = Module()

        m.submodules.tx_decoder = tx_decoder = cobs.Decoder()
        wiring.connect(m, tx_decoder.i, wiring.flipped(self.i_stream))

        m.submodules.ctrl = ctrl = ethernet.Controller(self._driver)
        m.d.comb += ctrl.rx_bypass.eq(self.rx_bypass)
        m.d.comb += ctrl.tx_bypass.eq(self.tx_bypass)
        wiring.connect(m, ctrl.i, tx_decoder.o)

        m.submodules.rx_encoder = rx_encoder = cobs.Encoder(fifo_depth=2048)
        wiring.connect(m, rx_encoder.i, ctrl.o)

        wiring.connect(m, wiring.flipped(self.o_stream), rx_encoder.o)

        return m


class AbstractEthernetInterface:
    def __init__(self, logger: logging.Logger, assembly: AbstractAssembly, *,
                 driver: ethernet.AbstractDriver):
        self._logger = logger
        self._level  = logging.DEBUG if self._logger.name.startswith(__name__) else logging.TRACE

        component = assembly.add_submodule(EthernetComponent(driver))
        self._pipe = assembly.add_inout_pipe(
            component.o_stream, component.i_stream,
            in_fifo_depth=0, out_buffer_size=512 * 128)
        self._rx_bypass = assembly.add_rw_register(component.rx_bypass)
        self._tx_bypass = assembly.add_rw_register(component.tx_bypass)

        self._snoop: snoop.SnoopWriter = None

    def _log(self, message: str, *args):
        self._logger.log(self._level, "Ethernet: " + message, *args)

    @property
    def snoop_file(self) -> BinaryIO:
        if self._snoop is not None:
            return self._snoop.file

    @snoop_file.setter
    def snoop_file(self, snoop_file):
        if snoop_file is not None:
            self._snoop = snoop.SnoopWriter(snoop_file,
                datalink_type=snoop.SnoopDatalinkType.Ethernet)
        else:
            self._snoop = None

    def _snoop_packet(self, packet):
        if self._snoop is not None:
            self._snoop.write(snoop.SnoopPacket(packet, timestamp_ns=time.time_ns()))

    async def send(self, packet: bytes | bytearray | memoryview) -> bool:
        cobs_packet = cobs.encode(packet) + b"\x00"
        if self._pipe.writable is None or len(cobs_packet) <= self._pipe.writable:
            self._log("tx data=<%s>", dump_hex(packet))
            self._snoop_packet(packet)
            await self._pipe.send(cobs_packet)
            await self._pipe.flush(_wait=False)
            return True
        else:
            self._logger.warning("tx drop")
            return False

    async def recv(self) -> bytes:
        packet = cobs.decode((await self._pipe.recv_until(b"\x00"))[:-1])
        self._log("rx data=<%s> len=%d", dump_hex(packet), len(packet))
        self._snoop_packet(packet)
        return packet

    async def iter_recv(self) -> AsyncIterator[bytes]:
        while True:
            yield await self.recv()


class AbstractEthernetApplet(GlasgowAppletV2):
    logger = logging.getLogger(__name__)
    help = "send and receive Ethernet packets"
    description = """
    Communicate with an Ethernet network using a PHY connected via the $PHYIF$ interface.

    The `bridge` operation is supported only on Linux. To create a suitable TAP interface, run:

    ::

        sudo ip tuntap add glasgow0 mode tap user $USER
        sudo ip link set glasgow0 up
    """
    required_revision = "C0"

    @classmethod
    def add_setup_arguments(cls, parser):
        parser.add_argument("--snoop", dest="snoop_file", type=argparse.FileType("wb"),
            metavar="SNOOP-FILE", help="save packets to a file in RFC 1761 format")

    async def setup(self, args):
        self.eth_iface.snoop_file = args.snoop_file

    @classmethod
    def add_run_arguments(cls, parser):
        p_operation = parser.add_subparsers(dest="operation", metavar="OPERATION", required=True)

        p_bridge = p_operation.add_parser(
            "bridge", help="bridge network to the host OS")
        p_bridge.add_argument(
            "interface", metavar="INTERFACE", nargs="?", type=str, default="glasgow0",
            help="forward packets to and from this TAP interface (default: %(default)s)")

        p_loopback = p_operation.add_parser(
            "loopback", help="test connection to PHY using near-end loopback")
        p_loopback.add_argument(
            "--delay", "-d", metavar="DELAY", type=float, default=1.0,
            help="wait for DELAY seconds between sending packets (default: %(default)s)")

    async def run(self, args):
        if args.operation == "bridge":
            os_iface = OSNetworkInterface(args.interface)

            async def forward_rx():
                async for packet in self.eth_iface.iter_recv():
                    if len(packet) >= 14: # must be at least ETH_HLEN, or we'll get EINVAL on Linux
                        await os_iface.send([packet])

            async def forward_tx():
                while True:
                    for packet in await os_iface.recv():
                        if not await self.eth_iface.send(packet):
                            break

            async with asyncio.TaskGroup() as group:
                group.create_task(forward_rx())
                group.create_task(forward_tx())

        if args.operation == "loopback":
            # Enable near-end loopback.
            basic_control = REG_BASIC_CONTROL.from_int(
                await self.mdio_iface.c22_read(0, REG_BASIC_CONTROL_addr))
            basic_control.LOOPBACK = 1
            await self.mdio_iface.c22_write(0, REG_BASIC_CONTROL_addr, basic_control.to_int())

            # Accept all packets, even those with CRC errors.
            await self.eth_iface._rx_bypass.set(True)

            count_ok   = 0
            count_bad  = 0
            count_lost = 0
            try:
                packet_data = bytes(range(256))
                packet_fcs  = CRC32_ETHERNET().compute(packet_data).to_bytes(4, "little")
                packet_full = packet_data + packet_fcs
                while True:
                    await self.eth_iface.send(packet_data)
                    try:
                        async with asyncio.timeout(args.delay):
                            packet_recv = await self.eth_iface.recv()
                        if packet_recv == packet_full:
                            self.logger.info("packet ok")
                            count_ok += 1
                        else:
                            if len(packet_recv) < len(packet_full):
                                self.logger.warning("packet bad (short)")
                            elif len(packet_recv) > len(packet_full):
                                self.logger.warning("packet bad (long)")
                            elif packet_recv[:len(packet_data)] != packet_data:
                                self.logger.warning("packet bad (data)")
                            else:
                                self.logger.warning("packet bad (crc)")
                            count_bad += 1
                        await asyncio.sleep(args.delay)
                    except TimeoutError:
                        self.logger.warning("packet lost")
                        count_lost += 1
            finally:
                count_all = count_ok + count_bad + count_lost
                if count_all:
                    self.logger.info(f"statistics: "
                        f"ok {count_ok}/{count_all} ({count_ok/count_all*100:.0f}%), "
                        f"bad {count_bad}/{count_all} ({count_bad/count_all*100:.0f}%), "
                        f"lost {count_lost}/{count_all} ({count_lost/count_all*100:.0f}%)")
