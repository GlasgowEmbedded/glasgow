import asyncio
import threading


__all__ = ["asyncio_run_in_thread"]


def asyncio_run_in_thread(coro):
    thread_res = thread_exn = None
    def run():
        nonlocal thread_res, thread_exn
        loop = asyncio.new_event_loop()
        try:
            thread_res = loop.run_until_complete(coro)
        except Exception as exn:
            thread_exn = exn
        finally:
            loop.close()

    thread = threading.Thread(target=run)
    thread.start()
    thread.join()
    if thread_exn is not None:
        raise thread_exn
    return thread_res
