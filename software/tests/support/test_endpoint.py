import asyncio
import logging
import unittest
import tempfile

from glasgow.support.endpoint import endpoint, ServerEndpoint


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

        proto, host, port = endpoint("tcp:111.111.111.111:1234")
        self.assertEqual(proto, "tcp")
        self.assertEqual(host, "111.111.111.111")
        self.assertEqual(port, 1234)

        proto, host, port = endpoint("tcp:123.45.67.8:1234")
        self.assertEqual(proto, "tcp")
        self.assertEqual(host, "123.45.67.8")
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
        sock = ("unix", f"{tempfile.gettempdir()}/test_lifecycle_sock")
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
        conn_wr.close()

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
        sock = ("unix", f"{tempfile.gettempdir()}/test_until_sock")
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
        with self.assertRaises(asyncio.exceptions.CancelledError):
            await endp.recv(1)

    def test_tcp(self):
        asyncio.get_event_loop().run_until_complete(
            self.do_test_tcp())

    async def do_test_server_banner(self):
        sock = ("tcp", "localhost", 2345)
        endp = await ServerEndpoint("test_server_banner", logging.getLogger(__name__), sock)

        async def endpoint_task():
            await endp.recv_wait()
            await endp.send(b"Hello")
        asyncio.create_task(endpoint_task())

        conn_rd, _ = await asyncio.open_connection(*sock[1:])
        r = await conn_rd.read(5)
        self.assertEqual(r, b"Hello")

    def test_server_banner(self):
        logging.basicConfig(level=logging.TRACE)
        asyncio.get_event_loop().run_until_complete(
            self.do_test_server_banner())
