import os
import signal
import asyncio


__all__ = ["register_wakeup_fd", "wait_for_signal"]


def register_wakeup_fd(loop):
    read_fd, write_fd = os.pipe()
    os.set_blocking(write_fd, False)
    old_write_fd = signal.set_wakeup_fd(write_fd)
    def chain_wakeup_fd():
        sigdata = os.read(read_fd, 1)
        if old_write_fd != -1:
            os.write(old_write_fd, sigdata)
    loop.add_reader(read_fd, chain_wakeup_fd)


def wait_for_signal(signum):
    future = asyncio.Future()
    def handler(signum, frame):
        future.set_result(None)
        signal.signal(signum, old_handler)
    old_handler = signal.signal(signum, handler)
    return future
