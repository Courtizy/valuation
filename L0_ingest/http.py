"""Minimal stdlib HTTP client: SEC User-Agent, rate limiting, retries."""
from __future__ import annotations

import time
import urllib.error
import urllib.request
from typing import Callable

RETRY_STATUSES = {429, 500, 502, 503, 504}


class HttpError(RuntimeError):
    def __init__(self, url: str, status: int | None, msg: str):
        super().__init__(f"{url}: {status} {msg}")
        self.url, self.status = url, status


class HttpClient:
    """GET bytes politely. SEC asks for <= 10 req/s and a contact User-Agent."""

    def __init__(
        self,
        user_agent: str,
        min_interval: float = 0.12,
        max_retries: int = 3,
        backoff: float = 1.0,
        timeout: float = 30.0,
        opener: Callable = urllib.request.urlopen,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        if not user_agent or "@" not in user_agent:
            raise ValueError(
                "SEC requires a User-Agent with contact info, "
                "e.g. 'Jane Doe jane@example.com' (or set $SEC_USER_AGENT)"
            )
        self.user_agent = user_agent
        self.min_interval = min_interval
        self.max_retries = max_retries
        self.backoff = backoff
        self.timeout = timeout
        self._open, self._sleep, self._clock = opener, sleep, clock
        self._last = float("-inf")

    def _throttle(self) -> None:
        wait = self.min_interval - (self._clock() - self._last)
        if wait > 0:
            self._sleep(wait)
        self._last = self._clock()

    def get_bytes(self, url: str) -> bytes:
        req = urllib.request.Request(
            url, headers={"User-Agent": self.user_agent, "Accept": "application/json"}
        )
        for attempt in range(self.max_retries + 1):
            self._throttle()
            try:
                with self._open(req, timeout=self.timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as e:
                if e.code in RETRY_STATUSES and attempt < self.max_retries:
                    self._sleep(self.backoff * 2**attempt)
                    continue
                raise HttpError(url, e.code, str(e.reason)) from e
            except urllib.error.URLError as e:
                if attempt < self.max_retries:
                    self._sleep(self.backoff * 2**attempt)
                    continue
                raise HttpError(url, None, str(e.reason)) from e
        raise HttpError(url, None, "retries exhausted")  # pragma: no cover
