"""Adapter for the SEC XBRL companyfacts API.

Endpoint:   https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json
Ticker map: https://www.sec.gov/files/company_tickers.json
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Protocol

from .cache import FileCache
from .http import HttpClient
from .schema import SCHEMA_VERSION

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"


class BytesClient(Protocol):
    def get_bytes(self, url: str) -> bytes: ...


class TickerNotFound(KeyError):
    pass


def normalize_cik(cik: str | int) -> str:
    """'320193', 320193, or 'CIK0000320193' -> '0000320193'."""
    s = str(cik).strip()
    if s.upper().startswith("CIK"):
        s = s[3:]
    if not s.isdigit() or len(s) > 10:
        raise ValueError(f"invalid CIK: {cik!r}")
    return s.zfill(10)


def flatten_facts(payload: dict) -> list[dict]:
    """Turn companyfacts' nested taxonomy/tag/unit tree into flat records.

    Sorted deterministically so identical source data gives an identical file.
    """
    out: list[dict] = []
    for taxonomy, tags in (payload.get("facts") or {}).items():
        for tag, body in tags.items():
            label = body.get("label")
            description = body.get("description")
            for unit, rows in (body.get("units") or {}).items():
                for r in rows:
                    out.append(
                        {
                            "taxonomy": taxonomy,
                            "tag": tag,
                            "label": label,
                            "description": description,
                            "unit": unit,
                            "value": r.get("val"),
                            "start": r.get("start"),
                            "end": r.get("end"),
                            "fy": r.get("fy"),
                            "fp": r.get("fp"),
                            "form": r.get("form"),
                            "filed": r.get("filed"),
                            "accn": r.get("accn"),
                            "frame": r.get("frame"),
                        }
                    )
    out.sort(
        key=lambda f: (
            f["taxonomy"], f["tag"], f["unit"], f["end"] or "",
            f["start"] or "", f["filed"] or "", f["accn"] or "",
        )
    )
    return out


class SecCompanyFactsAdapter:
    name = "sec_companyfacts"

    def __init__(
        self,
        client: BytesClient | None = None,
        cache: FileCache | None = None,
        user_agent: str | None = None,
    ):
        self._client = client
        self._user_agent = user_agent or os.environ.get("SEC_USER_AGENT")
        self.cache = cache

    @property
    def client(self) -> BytesClient:
        # Built lazily so cache-only runs never need a User-Agent.
        if self._client is None:
            self._client = HttpClient(self._user_agent or "")
        return self._client

    def _get(self, url: str, cache_key: str) -> tuple[bytes, float, bool]:
        if self.cache:
            hit = self.cache.get(cache_key)
            if hit:
                return hit[0], hit[1], True
        data = self.client.get_bytes(url)
        if self.cache:
            fetched_at = self.cache.put(cache_key, data)
        else:
            fetched_at = datetime.now(timezone.utc).timestamp()
        return data, fetched_at, False

    def resolve_cik(self, ticker: str) -> tuple[str, str]:
        """Return (10-digit CIK, company title) for a ticker."""
        data, _, _ = self._get(TICKERS_URL, "company_tickers.json")
        t = ticker.strip().upper()
        for row in json.loads(data).values():
            if str(row.get("ticker", "")).upper() == t:
                return normalize_cik(row["cik_str"]), row.get("title", "")
        raise TickerNotFound(f"ticker not found in SEC map: {ticker!r}")

    def fetch(self, *, ticker: str | None = None, cik: str | int | None = None) -> dict:
        """Fetch companyfacts and return a raw_filing dict (not yet written)."""
        if (ticker is None) == (cik is None):
            raise ValueError("pass exactly one of ticker= or cik=")
        cik10 = self.resolve_cik(ticker)[0] if ticker is not None else normalize_cik(cik)

        url = COMPANYFACTS_URL.format(cik=cik10)
        data, fetched_at, from_cache = self._get(url, f"companyfacts_CIK{cik10}.json")
        payload = json.loads(data)

        return {
            "schema_version": SCHEMA_VERSION,
            "source": self.name,
            "source_url": url,
            "retrieved_at": datetime.fromtimestamp(fetched_at, timezone.utc).isoformat(
                timespec="seconds"
            ),
            "from_cache": from_cache,
            "content_sha256": hashlib.sha256(data).hexdigest(),
            "entity": {
                "cik": cik10,
                "name": payload.get("entityName", ""),
                "ticker": ticker.strip().upper() if ticker else None,
            },
            "facts": flatten_facts(payload),
        }
