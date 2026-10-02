"""File cache for raw source payloads. Stores bytes exactly as received."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path
from typing import Callable


class FileCache:
    def __init__(
        self,
        root: str | Path,
        ttl_seconds: float | None = 86_400,
        clock: Callable[[], float] = time.time,
    ):
        self.root = Path(root)
        self.ttl = ttl_seconds
        self._clock = clock

    def _path(self, key: str) -> Path:
        return self.root / re.sub(r"[^A-Za-z0-9._-]", "_", key)

    def get(self, key: str) -> tuple[bytes, float] | None:
        """Return (payload, fetched_at_epoch), or None if missing/expired."""
        p = self._path(key)
        if not p.exists():
            return None
        mtime = p.stat().st_mtime
        if self.ttl is not None and self._clock() - mtime > self.ttl:
            return None
        return p.read_bytes(), mtime

    def put(self, key: str, data: bytes) -> float:
        """Atomically write payload; return fetched_at_epoch."""
        self.root.mkdir(parents=True, exist_ok=True)
        p = self._path(key)
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_bytes(data)
        os.replace(tmp, p)
        now = self._clock()
        os.utime(p, (now, now))
        return now
