"""Bounded-memory sequential audit storage, spilling full records inside the project."""

import json
import tempfile
from collections import deque
from collections.abc import Iterator, Sequence
from itertools import islice
from pathlib import Path
from typing import Any, overload


class AuditLog(Sequence[dict[str, Any]]):
    """Keep a bounded recent tail and a complete JSONL spool; access at event barriers."""

    def __init__(self, *, max_bytes: int = 2 * 1024 * 1024, tail_size: int = 100):
        directory = Path(__file__).resolve().parents[3] / ".cache" / "simulator"
        directory.mkdir(parents=True, exist_ok=True)
        self._stream = tempfile.SpooledTemporaryFile(
            max_size=max_bytes, mode="w+t", encoding="utf-8", dir=str(directory)
        )
        self._tail: deque[dict[str, Any]] = deque(maxlen=tail_size)
        self._length = 0
        self._last_offset = 0

    def append(self, record: dict[str, Any]):
        self._stream.seek(0, 2)
        self._last_offset = self._stream.tell()
        self._stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + "\n")
        self._tail.append(record)
        self._length += 1

    def update_last(self, fields: dict[str, Any]):
        if not self._length:
            raise IndexError("empty audit log")
        value = self._tail[-1]
        value.update(fields)
        self._stream.seek(self._last_offset)
        self._stream.truncate()
        self._stream.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")

    def __len__(self) -> int:
        return self._length

    def __iter__(self) -> Iterator[dict[str, Any]]:
        self._stream.flush()
        self._stream.seek(0)
        try:
            for _ in range(self._length):
                yield json.loads(self._stream.readline())
        finally:
            self._stream.seek(0, 2)

    @overload
    def __getitem__(self, key: int) -> dict[str, Any]: ...
    @overload
    def __getitem__(self, key: slice) -> list[dict[str, Any]]: ...
    def __getitem__(self, key):
        offset = self._length - len(self._tail)
        if isinstance(key, int):
            index = key if key >= 0 else self._length + key
            if not 0 <= index < self._length:
                raise IndexError(key)
            return (
                list(self._tail)[index - offset]
                if index >= offset
                else next(islice(iter(self), index, index + 1))
            )
        start, stop, step = key.indices(self._length)
        if start >= offset and step > 0:
            return list(self._tail)[start - offset : stop - offset : step]
        return list(self)[key] if step < 0 else list(islice(iter(self), start, stop, step))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Sequence) or len(other) != len(self):
            return False
        return all(a == b for a, b in zip(self, other, strict=True))

    @property
    def spilled(self) -> bool:
        return bool(getattr(self._stream, "_rolled", False))

    def close(self):
        self._stream.close()
