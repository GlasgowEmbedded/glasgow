from collections import deque


__all__ = ["ChunkedFIFO"]


class ChunkedFIFO:
    """
    A first-in first-out byte buffer that uses discontiguous storage to operate without copying.
    """
    def __init__(self):
        self._queue  = deque()
        self._chunk  = None
        self._offset = 0
        self._length = 0
        self._rtotal = 0
        self._wtotal = 0

    def clear(self):
        """Remove all data from the buffer."""
        self._queue.clear()
        self._chunk  = None
        self._offset = 0
        self._length = 0

    def write(self, data):
        """Enqueue ``data``."""
        try:
            data = memoryview(data)
        except TypeError:
            data = memoryview(bytes(data))

        if not data:
            return
        self._length += len(data)
        self._wtotal += len(data)
        self._queue.append(data)

    def read(self, max_length=None):
        """
        Dequeue at most ``max_length`` bytes. If ``max_length`` is not specified, dequeue
        the maximum possible contiguous amount of bytes (at least one).

        Regardless of what was written into the FIFO, ``read`` always returns a ``memoryview``
        object.
        """
        if max_length is None and self._chunk is None:
            # Fast path.
            chunk = self._queue.popleft()
            self._length -= len(chunk)
            self._rtotal += len(chunk)
            return chunk

        if max_length == 0:
            return memoryview(b"")

        if self._chunk is None:
            if not self._queue:
                return memoryview(b"")

            self._chunk  = self._queue.popleft()
            self._offset = 0

        if max_length is None:
            result = self._chunk[self._offset:]
        else:
            result = self._chunk[self._offset:self._offset + max_length]

        if self._offset + len(result) == len(self._chunk):
            self._chunk = None
        else:
            self._offset += len(result)

        self._length -= len(result)
        self._rtotal += len(result)
        return result

    def read_until(self, delimiter: bytes) -> memoryview:
        """
        Dequeue bytes up to and and including ``delimiter`` (if any). If ``delimiter`` is not
        found, dequeue the maximum possible contiguous amount of bytes (at least one).

        Regardless of what was written into the FIFO, ``read_until`` always returns a ``memoryview``
        object.
        """
        assert len(delimiter) == 1

        if self._chunk is None:
            if not self._queue:
                return memoryview(b"")

            self._chunk  = self._queue.popleft()
            self._offset = 0

        try:
            # This copies `self._chunk`, but it is unavoidable: `memoryview` can't be searched.
            index = self._chunk.tobytes().index(delimiter, self._offset)
            result = self._chunk[self._offset:index + len(delimiter)]
        except ValueError:
            result = self._chunk[self._offset:]

        if self._offset + len(result) == len(self._chunk):
            self._chunk = None
        else:
            self._offset += len(result)

        self._length -= len(result)
        self._rtotal += len(result)
        return result

    def __bool__(self):
        """Check whether there are any bytes in the FIFO."""
        return bool(self._queue) or self._chunk is not None

    def __len__(self):
        """Count bytes in the FIFO."""
        return self._length

    @property
    def total_read_bytes(self):
        """Determine the total amount of bytes read from the FIFO."""
        return self._rtotal

    @property
    def total_written_bytes(self):
        """Determine the total amount of bytes written to the FIFO."""
        return self._wtotal
