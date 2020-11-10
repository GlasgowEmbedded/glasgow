import time
import asyncio
from collections import deque


__all__ = ["TaskQueue"]


class TaskQueue:
    """
    A queue of asyncio tasks that can be used for pipelining operations.

    Consider a situation where a small buffer must be emptied with a low latency.Submitting
    a single large read wouldn't meet the latency requirements, and submitting small reads in
    a loop will cause buffer overflows due to the fact that Python's runtime (and probably the OS)
    are not real-time. Submitting many small reads in sequence, and immediately resubmitting
    another read after one finishes, avoids overflow and ensures low latency.
    """
    def __init__(self):
        self._live = set()
        self._done = deque()
        self._wait_time = 0.0
        self._wait_count = 0

    def _callback(self, future):
        self._live.remove(future)
        self._done.append(future)

    def submit(self, coro):
        """
        Submit a task to the queue. The task may return ``None`` or a Future-like object; in
        the latter case, the returned future is submitted to the queue as well.
        """
        future = asyncio.ensure_future(coro)
        self._live.add(future)
        future.add_done_callback(self._callback)

    async def cancel(self):
        """
        Cancel all tasks in the queue, and wait until cancellation is finished.
        """
        for task in self._live:
            task.cancel()
        if self._live:
            await asyncio.wait(self._live, return_when=asyncio.ALL_COMPLETED)
        self._done.clear()

    async def poll(self):
        """
        Await all finished tasks that have been submitted to the queue. Returns ``True`` if there
        were any finished tasks, ``False`` otherwise.

        This method needs to be called regularly to ensure that exceptions are propagated upwards
        in the call stack. If it is not called, the queue will leak memory.
        """
        had_done = bool(self._done)
        while self._done:
            await self._done.popleft()
        return had_done

    async def wait_one(self):
        """
        Await at least one task in the queue. If there are no finished tasks, waits until the first
        pending task finishes.
        """
        if not self._done:
            started_at = time.monotonic()
            await asyncio.wait(self._live, return_when=asyncio.FIRST_COMPLETED)
            self._wait_time += time.monotonic() - started_at
            self._wait_count += 1
        await self.poll()

    async def wait_all(self):
        """
        Await all tasks in the queue, if any.
        """
        if self._live:
            started_at = time.monotonic()
            await asyncio.wait(self._live, return_when=asyncio.ALL_COMPLETED)
            self._wait_time += time.monotonic() - started_at
            self._wait_count += 1
        await self.poll()

    def __bool__(self):
        """Check whether there are any pending tasks in the queue."""
        return bool(self._live)

    def __len__(self):
        """Count pending tasks in the queue."""
        return len(self._live)

    @property
    def total_wait_time(self):
        """Determine the total duration spent waiting for pending tasks in the queue to finish."""
        return self._wait_time

    @property
    def total_wait_count(self):
        """Determine the total number of calls to :meth:`wait_one` or :meth:`wait_all` that had
        to wait for a pending task in the queue to finish."""
        return self._wait_count
