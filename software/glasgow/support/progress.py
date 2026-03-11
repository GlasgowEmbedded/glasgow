from __future__ import annotations
from abc import ABCMeta, abstractmethod
from typing import Literal
from collections.abc import Generator, Sequence
import sys

from tqdm import tqdm
from tqdm.contrib import DummyTqdmFile


__all__ = ["Progress"]


class Progress:
    """Progress tracker.

    This context manager is used to indicate progress of a slow process within applet code in
    a generic way, decoupling it from a specific type of user interface. For example, if an applet
    is used with a CLI frontend, terminal escape sequences could be used to repeatedly display
    a text description on the last used line, whereas with a GUI frontend, a progress bar widget
    would be used.

    To use it, modify applet code that processes multiple items by wrapping it in
    :py:`with Progress(...):`. For example, let's consider a method that uploads a bitstream via
    :class:`SPIControllerInterface<glasgow.applet.interface.spi_controller.SPIControllerInterface>`:

    .. code:: python

        async def load(bitstream: bytes):
            async with self._spi.select():
                await self._spi.write(bitstream)

    To add progress indication here, the bitstream will need to be explicitly chunked (while
    avoiding copies using :class:`memoryview`) and individual chunks iterated through:

    .. code:: python

        async def load(bitstream: bytes):
            bitstream  = memoryview(bitstream)
            chunk_size = 0x10000
            async with self._spi.select():
                with Progress(total=len(bitstream),
                        action="programming", item="B", scale=1024) as progress:
                    for start in range(0, len(bitstream), chunk_size):
                        await self._spi.write(bitstream[start:start + chunk_size])
                        await self._spi.synchronize()
                        progress.advance(chunk_size)

    .. note::

        The :py:`synchronize()` call is added because the :py:`write()` method does not wait for
        the operation to complete; without it, the :py:`load()` method would quickly finish, with
        the command buffer draining slowly after. In most cases (e.g. Flash programming) there is
        a requirement to wait for feedback, making explicit synchronization unnecessary.

    The particluar case of chunking a sequence (of bytes, or otherwise) is common enough that
    this class provides a helper method for it, :meth:`chunks`. Using this helper the :py:`load()`
    function becomes:

    .. code:: python

        async def load(bitstream: bytes):
            async with self._spi.select():
                for chunk in Progress.chunks(memoryview(bitstream), 0x10000,
                        action="programming", item="B", scale=1024):
                    await self._spi.write(chunk)
                    await self._spi.synchronize()

    With this change to the applet code, a CLI frontend can now indicate the progress of
    the operation, for example, by printing:

    .. code::

        programming... 13% (65536/500000 bytes)
        programming... 26% (131072/500000 bytes)
        (and so on until completion)
    """

    _total: int | None
    _done: int
    _action: str
    _item: str | None
    _scale: Literal[1, 1000, 1024]

    def __init__(self, *,
        total: int | None = None,
        action: str,
        item: str | None = None,
        scale: Literal[1, 1000, 1024] = 1,
    ):
        self._total  = total
        self._done   = 0
        self._action = action
        self._item   = item
        self._scale  = scale

    @classmethod
    def chunks[T](cls, items: Sequence[T], chunk_size: int, **kwargs) -> Generator[Sequence[T]]:
        """Chunked progress tracker.

        This helper method exists to handle the case where a sequence must be brought into chunks
        for processing, but progress must be tracked per-item, not per-chunk. For example, when
        manipulating large byte sequences, it would be too inefficient to process bytes one by one
        just to report progress, but processing 64 KiB chunks is usually fine.

        All keyword arguments not explicitly declared are passed to the class constructor. Returns
        a :term:`python:generator` yielding the result of indexing slices of :py:`items` up to
        :py:`chunk_size` in length, and advancing progress whenever control is returned.

        To split a byte array into chunks of up to :py:`chunk_size`, such as for a write
        operation, use:

        .. code:: python

            for chunk in Progress.chunks(memoryview(data), chunk_size,
                    action="programming", item="B", scale=1024):
                write_data(chunk) # here `chunk` is a `memoryview`

        To split an address range into chunks of up to :py:`chunk_size`, such as for a read
        operation, use:

        .. code:: python

            for chunk in Progress.chunks(range(start, start + length), chunk_size,
                    action="reading", item="B", scale=1024):
                data += read_data(chunk.start, len(chunk)) # here `chunk` is a `range`

        .. note::

            Avoid passing :class:`bytes` or :class:`bytearray` values as :py:`items`; wrap them
            in :class:`memoryview` so that chunks reference the original bytes instead of copying.
        """
        with cls(**kwargs, total=len(items)) as progress:
            for start in range(0, len(items), chunk_size):
                yield items[start:start + chunk_size]
                progress.advance(chunk_size)

    @property
    def action(self) -> str:
        """Action taking progress.

        Should have a `present participle` with no punctuation at the end, e.g. :py:`"writing"`
        or :py:`"programming flash"`.
        """
        return self._action

    @property
    def item(self) -> str | None:
        """Item being operated on.

        Should be a singular noun, e.g. :py:`"byte"` or :py:`"B"`. If :py:`None`, then the unit
        of processing is unspecified: either clear from context, or not feasible to specify exactly.
        """
        return self._item

    @property
    def scale(self) -> Literal[1, 1000, 1024]:
        """Scale of item count.

        May be one of 1, 1000, or 1024. If not 1, an appropriate SI prefix (K, M, G... or
        Ki, Mi, Gi...) will be used when counting items.
        """
        return self._scale

    @property
    def total(self) -> int | None:
        """Total number of items.

        If :py:`None`, impossible to know until the operation finishes.
        """
        return self._total

    @property
    def done(self) -> int:
        """Number of completed items."""
        return self._done

    def advance(self, count: int):
        """Indicate completion of :py:`count` items.

        Advancing progress beyond :py:`self.total` completed items may result in confusing UI
        behavior, but will not raise errors. However, :py:`count` must not be negative.
        """
        assert count >= 0
        self._done += count
        if self._impl:
            self._impl.update(self, count)

    def __enter__(self):
        """Register the progress indicator.

        Adds :py:`self` to the stack of displayed progress indicators.

        This :term:`python:dunder` method is called implicitly by the :py:`with Progress(...):`
        block.
        """
        if self._impl:
            self._impl.open(self)
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Unregister the progress indicator.

        Removes :py:`self` from the stack of displayed progress indicators.

        This :term:`python:dunder` method is called implicitly by the :py:`with Progress(...):`
        block.
        """
        if self._impl:
            self._impl.close(self)

    _impl: AbstractProgressImpl | None = None


class AbstractProgressImpl(metaclass=ABCMeta):
    @abstractmethod
    def open(self, progress: Progress):
        ...

    @abstractmethod
    def close(self, progress: Progress):
        ...

    @abstractmethod
    def update(self, progress: Progress, count: int):
        ...


class TqdmProgressImpl(AbstractProgressImpl):
    def __init__(self):
        self._bars = dict[Progress, tqdm]()

    def register(self):
        self._orig_impl, Progress._impl = Progress._impl, self
        self._orig_stdout, sys.stdout = sys.stdout, DummyTqdmFile(sys.stdout)
        self._orig_stderr, sys.stderr = sys.stderr, DummyTqdmFile(sys.stderr)
        # https://github.com/tqdm/tqdm/pull/1719
        self._orig_format_sizeof, tqdm.format_sizeof = tqdm.format_sizeof, \
            lambda num, suffix="", divisor=1000.0: \
                self._orig_format_sizeof(num, "i" if divisor == 1024 else "", divisor)

    def unregister(self):
        Progress._impl = self._orig_impl
        sys.stdout = self._orig_stdout
        sys.stderr = self._orig_stderr
        tqdm.format_sizeof = self._orig_format_sizeof

    def open(self, progress: Progress):
        self._bars[progress] = tqdm(
            desc=progress.action,
            unit=progress.item or "it", # explicit default to work around tqdm typing issue
            unit_scale=True if progress.scale != 1 else False,
            unit_divisor=progress.scale,
            total=float("+inf") if progress.total is None else progress.total,
            initial=progress.done,
            file=self._orig_stderr,
            dynamic_ncols=True
        )

    def close(self, progress: Progress):
        self._bars.pop(progress).close()

    def update(self, progress: Progress, delta: int):
        self._bars[progress].update(delta)
