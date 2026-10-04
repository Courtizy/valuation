"""Shared offline SEC client for the tests: serves fixtures by URL and logs every call."""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from valuation.L0_ingest.http import HttpError

FIXTURES = Path(__file__).parent / "fixtures"
Body = "Path | bytes | str | None"


class FakeSecClient:
    """routes: exact URL -> fixture path, bytes or text. fallback(url) answers anything else
    (return None for a 404). Unknown URLs raise HttpError 404, like SEC."""

    def __init__(self, routes: dict | None = None, fallback: Callable[[str], object] | None = None):
        self.calls: list[str] = []
        self.routes = dict(routes or {})
        self.fallback = fallback

    def get_bytes(self, url: str) -> bytes:
        self.calls.append(url)
        body = self.routes.get(url)
        if body is None and self.fallback:
            body = self.fallback(url)
        if body is None:
            raise HttpError(url, 404, "Not Found")
        if isinstance(body, Path):
            return body.read_bytes()
        return body.encode() if isinstance(body, str) else body
