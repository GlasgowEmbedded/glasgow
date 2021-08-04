import signal
import asyncio


__all__ = ["wait_for_signal"]


def wait_for_signal(signum, loop=None):
    if loop is None:
        loop = asyncio.get_event_loop()
    future = asyncio.Future(loop=loop)
    def callback(future):
        if future.cancelled():
            signal.signal(signum, old_handler)
    future.add_done_callback(callback)
    def handler(signum, frame):
        loop.call_soon_threadsafe(lambda: future.set_result(None))
        signal.signal(signum, old_handler)
    old_handler = signal.signal(signum, handler)
    return future
