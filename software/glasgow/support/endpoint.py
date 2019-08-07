import argparse
import asyncio
import logging
import re
from collections import deque

from .aobject import *


__all__ = ["ServerEndpoint", "ClientEndpoint"]


def endpoint(spec):
    m = re.match(r"^(unix):(.*)$", spec)
    if m: return (m[1], m[2])

    m = re.match(r"^(tcp):(?:()|\*|\[([a-fA-F0-9:]+)\]|(\d+(?:\.\d){3})|([a-zA-Z.-]+))"
                 r":(\d+)$", spec)
    if m: return (m[1], m[3] or m[4] or m[5] if m[2] is None else "localhost", int(m[6]))

    raise argparse.ArgumentTypeError("invalid format")


class ServerEndpoint(aobject, asyncio.Protocol):
    @classmethod
    def add_argument(cls, parser, name, default=None):
        metavar = name.upper().replace("_", "-")
        help    = "listen at %s, either unix:PATH or tcp:HOST:PORT" % metavar
        if default is None:
            nargs = None
        else:
            nargs = "?"
            help += " (default: %(default)s)"

        parser.add_argument(
            name, metavar=metavar, type=endpoint, nargs=nargs, default=default,
            help=help)

    async def __init__(self, name, logger, sock_addr, queue_size=None):
        assert isinstance(sock_addr, tuple)

        self.name    = name
        self._logger = logger

        proto, *proto_args = sock_addr
        loop = asyncio.get_event_loop()
        if proto == "unix":
            self.server = await loop.create_unix_server(lambda: self, *proto_args, backlog=1)
            unix_path, = proto_args
            self._log(logging.INFO, "listening at unix:%s", unix_path)
        elif proto == "tcp":
            self.server = await loop.create_server(lambda: self, *proto_args, backlog=1)
            tcp_host, tcp_port = proto_args
            self._log(logging.INFO, "listening at tcp:%s:%d", tcp_host or "*", tcp_port)
        else:
            raise ValueError("unknown protocol %s" % proto)

        self._transport     = None
        self._new_transport = None

        self._send_epoch = 0
        self._recv_epoch = 1
        self._queue      = deque()
        self._queued     = 0
        self._queue_size = queue_size
        self._future     = None

        self._buffer = None
        self._pos    = 0

        self._read_paused = False

    def _log(self, level, message, *args):
        self._logger.log(level, self.name + ": " + message, *args)

    def connection_made(self, transport):
        self._send_epoch += 1

        peername = transport.get_extra_info("peername")
        if peername:
            self._log(logging.INFO, "new connection from [%s]:%d", *peername[0:2])
        else:
            self._log(logging.INFO, "new connection")

        if self._transport is None:
            self._transport = transport
        else:
            self._log(logging.INFO, "closing old connection")
            self._transport.close()
            self._new_transport = transport

    def connection_lost(self, exc):
        peername = self._transport.get_extra_info("peername")
        if peername:
            self._log(logging.INFO, "connection from [%s]:%d lost", *peername[0:2])
        else:
            self._log(logging.INFO, "connection lost")

        self._transport, self._new_transport = self._new_transport, None
        self._queue.append(exc)
        self._check_future()

    def data_received(self, data):
        self._log(logging.TRACE, "endpoint received %d bytes", len(data))
        self._queue.append(data)
        self._queued += len(data)
        self._check_pushback()
        self._check_future()

    def _check_pushback(self):
        if self._queue_size is None:
            return
        elif not self._read_paused and self._queued >= self._queue_size:
            self._log(logging.TRACE, "queue full, pausing reads")
            self._transport.pause_reading()
            self._read_paused = True
        elif self._read_paused and self._queued < self._queue_size:
            self._log(logging.TRACE, "queue not full, resuming reads")
            self._transport.resume_reading()
            self._read_paused = False

    def _check_future(self):
        if self._queue and self._future is not None:
            item = self._queue.popleft()
            if isinstance(item, Exception):
                self._future.set_exception(item)
            else:
                self._future.set_result(item)
            self._future = None

    async def _refill(self):
        self._future = future = asyncio.Future()
        self._check_future()
        self._buffer = await future
        if self._buffer is None:
            self._buffer = b""
            self._log(logging.TRACE, "recv end-of-stream")
            self._recv_epoch += 1
            raise asyncio.CancelledError

    async def recv(self, length=0):
        data = bytearray()
        while length == 0 or len(data) < length:
            if not self._buffer:
                self._log(logging.TRACE, "recv waits for %d bytes", length - len(data))
                await self._refill()

            if length == 0:
                length = len(self._buffer)

            chunk = self._buffer[:length - len(data)]
            self._buffer = self._buffer[len(chunk):]
            self._queued -= len(chunk)
            self._check_pushback()
            data += chunk

        self._log(logging.TRACE, "recv <%s>", data.hex())
        return data

    async def recv_until(self, separator):
        separator = bytes(separator)
        data = bytearray()
        while True:
            if not self._buffer:
                self._log(logging.TRACE, "recv waits for <%s>", separator.hex())
                await self._refill()

            try:
                index = self._buffer.index(separator)
                chunk = self._buffer[:index]
                self._buffer = self._buffer[index + 1:]
                self._queued -= len(chunk)
                self._check_pushback()
                data += chunk
                break

            except ValueError:
                data += self._buffer
                self._queued -= len(self._buffer)
                self._check_pushback()
                self._buffer = None

        self._log(logging.TRACE, "recv <%s%s>", data.hex(), separator.hex())
        return data

    async def recv_wait(self):
        if not self._buffer:
            self._log(logging.TRACE, "recv wait")
            await self._refill()

    async def send(self, data):
        data = bytes(data)
        if self._send_epoch == self._recv_epoch:
            self._log(logging.TRACE, "send <%s>", data.hex())
            self._transport.write(data)
            return True
        else:
            self._log(logging.TRACE, "send to previous connection discarded")
            return False

    async def close(self):
        if self._transport:
            self._transport.close()


class ClientEndpoint(aobject, asyncio.Protocol):
    @classmethod
    def add_argument(cls, parser, name, default=None):
        metavar = name.upper().replace("_", "-")
        help    = "connect to %s, either unix:PATH or tcp:HOST:PORT" % metavar
        if default is None:
            nargs = None
        else:
            nargs = "?"
            help += " (default: %(default)s)"

        parser.add_argument(
            name, metavar=metavar, type=endpoint, nargs=nargs, default=default,
            help=help)

    # FIXME: finish this

# -------------------------------------------------------------------------------------------------

import unittest
import tempfile


class EndpointArgumentTestCase(unittest.TestCase):
    def test_unix(self):
        proto, path = endpoint("unix:/foo/bar")
        self.assertEqual(proto, "unix")
        self.assertEqual(path, "/foo/bar")

    def test_tcp_localhost(self):
        proto, host, port = endpoint("tcp::1234")
        self.assertEqual(proto, "tcp")
        self.assertEqual(host, "localhost")
        self.assertEqual(port, 1234)

    def test_tcp_all(self):
        proto, host, port = endpoint("tcp:*:1234")
        self.assertEqual(proto, "tcp")
        self.assertEqual(host, None)
        self.assertEqual(port, 1234)

    def test_tcp_ipv4(self):
        proto, host, port = endpoint("tcp:0.0.0.0:1234")
        self.assertEqual(proto, "tcp")
        self.assertEqual(host, "0.0.0.0")
        self.assertEqual(port, 1234)

    def test_tcp_ipv6(self):
        proto, host, port = endpoint("tcp:[2001:DB8::1]:1234")
        self.assertEqual(proto, "tcp")
        self.assertEqual(host, "2001:DB8::1")
        self.assertEqual(port, 1234)

    def test_tcp_hostname(self):
        proto, host, port = endpoint("tcp:eXample.org:1234")
        self.assertEqual(proto, "tcp")
        self.assertEqual(host, "eXample.org")
        self.assertEqual(port, 1234)


class ServerEndpointTestCase(unittest.TestCase):
    async def do_test_lifecycle(self):
        sock = ("unix", "{}/test_lifecycle_sock".format(tempfile.gettempdir()))
        endp = await ServerEndpoint("test_lifecycle", logging.getLogger(__name__), sock)

        conn_rd, conn_wr = await asyncio.open_unix_connection(*sock[1:])
        conn_wr.write(b"ABC")
        await conn_wr.drain()
        self.assertEqual(await endp.recv(1), b"A")
        self.assertEqual(await endp.recv(2), b"BC")
        await endp.send(b"XYZ")
        self.assertEqual(await conn_rd.readexactly(2), b"XY")
        self.assertEqual(await conn_rd.readexactly(1), b"Z")
        await endp.close()
        self.assertEqual(await conn_rd.read(1), b"")
        with self.assertRaises(asyncio.CancelledError):
            await endp.recv(1)

        conn_rd, conn_wr = await asyncio.open_unix_connection(*sock[1:])
        conn_wr.write(b"ABC")
        await conn_wr.drain()
        self.assertEqual(await endp.recv(3), b"ABC")
        conn_wr.close()
        with self.assertRaises(asyncio.CancelledError):
            await endp.recv(1)

    def test_lifecycle(self):
        asyncio.get_event_loop().run_until_complete(
            self.do_test_lifecycle())

    async def do_test_until(self):
        sock = ("unix", "{}/test_until_sock".format(tempfile.gettempdir()))
        endp = await ServerEndpoint("test_until", logging.getLogger(__name__), sock)

        conn_rd, conn_wr = await asyncio.open_unix_connection(*sock[1:])
        conn_wr.write(b"ABC;DEF")
        await conn_wr.drain()
        self.assertEqual(await endp.recv_until(b";"), b"ABC")
        conn_wr.write(b";")
        await conn_wr.drain()
        self.assertEqual(await endp.recv_until(b";"), b"DEF")

    def test_until(self):
        asyncio.get_event_loop().run_until_complete(
            self.do_test_until())

    async def do_test_tcp(self):
        sock = ("tcp", "localhost", 9999)
        endp = await ServerEndpoint("test_tcp", logging.getLogger(__name__), sock)

        conn_rd, conn_wr = await asyncio.open_connection(*sock[1:])
        conn_wr.write(b"ABC")
        await conn_wr.drain()
        self.assertEqual(await endp.recv(3), b"ABC")
        await endp.send(b"XYZ")
        self.assertEqual(await conn_rd.readexactly(3), b"XYZ")
        conn_wr.close()
        self.assertEqual(await endp.recv(1), None)

    def test_tcp(self):
        asyncio.get_event_loop().run_until_complete(
            self.do_test_lifecycle())
