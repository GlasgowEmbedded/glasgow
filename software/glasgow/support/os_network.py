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
        """Raw file descriptor.

        The file descriptor may be useful for operations such as :meth:`fcntl.ioctl` or fine-grained
        buffering that is not achievable with :meth:`send` and :meth:`recv`.
        """
        return self._fd

    async def send(self, packets: 'list[bytes | bytearray | memoryview]'):
        """"Send packets.

        To improve throughput, :meth:`send` can queue multiple packets.

        Calling :meth:`send` twice concurrently on the same interface has undefined behavior.
        """
        try:
            for packet in packets:
                os.write(self._fd, packet)
        except BlockingIOError: # write until the buffer is full
            pass

    async def recv(self, *, length=65536) -> 'list[bytes | bytearray | memoryview]':
        """"Receive packets.

        To improve throughput, :meth:`recv` dequeues all available packets. Packets longer than
        :py:`length` are truncated to that length, without indication of it.

        Calling :meth:`recv` twice concurrently on the same interface has undefined behavior.
        """
        loop = asyncio.get_event_loop()
        future = asyncio.Future()
        def callback():
            loop.remove_reader(self._fd)
            try:
                packets = []
                while True:
                    packets.append(os.read(self._fd, length))
            except BlockingIOError: # read all of the ones available
                future.set_result(packets)
            except Exception as exc:
                future.set_exception(exc)
            else:
                future.set_result(packets)
        # I have benchmarked this and trying to do a speculative `os.read` instead of requiring
        # the loop to poll the fd at least once doesn't result in any performance improvement.
        loop.add_reader(self._fd, callback)
        return await future
