import os
import fcntl
import struct
import asyncio


LINUX_TUNSETIFF = 0x400454CA
LINUX_IFF_TUN   = 0x0001
LINUX_IFF_TAP   = 0x0002
LINUX_IFF_NO_PI = 0x1000


# Linux-only at the moment.
class OSNetworkInterface:
    """Userspace network interface driver for the host operating system."""

    def __init__(self, name: 'str | bytes'):
        if not (isinstance(name, (str, bytes)) and len(name) in range(1, 16)):
            raise TypeError(f"invalid interface name: {name!r}")
        if isinstance(name, str):
            name = name.encode()

        self._fd = os.open("/dev/net/tun", os.O_RDWR | os.O_NONBLOCK)
        fcntl.ioctl(self._fd, LINUX_TUNSETIFF,
            struct.pack("16sH22s", name, LINUX_IFF_TAP | LINUX_IFF_NO_PI, b""))

    def fileno(self):
        return self._fd

    def send(self, packet: 'bytes | bytearray | memoryview') -> asyncio.Future:
        loop = asyncio.get_event_loop()
        future = asyncio.Future()
        def callback():
            loop.remove_writer(self._fd)
            try:
                os.write(self._fd, packet)
                future.set_result(None)
            except Exception as exc:
                future.set_exception(exc)
        loop.add_writer(self._fd, callback)
        return future

    def recv(self, *, length=65536) -> asyncio.Future:
        loop = asyncio.get_event_loop()
        future = asyncio.Future()
        def callback():
            loop.remove_reader(self._fd)
            try:
                future.set_result(os.read(self._fd, length))
            except Exception as exc:
                future.set_exception(exc)
        loop.add_reader(self._fd, callback)
        return future
