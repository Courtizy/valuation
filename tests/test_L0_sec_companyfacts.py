"""Offline tests for L0 (no network). Run: pytest tests/test_L0_sec_companyfacts.py"""
from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path

import pytest

from L0_ingest.__main__ import main
from L0_ingest.cache import FileCache
from L0_ingest.http import HttpClient, HttpError
from L0_ingest.schema import validate_raw_filing
from L0_ingest.sec_companyfacts import (
    COMPANYFACTS_URL,
    SUBMISSIONS_URL,
    TICKERS_URL,
    SecCompanyFactsAdapter,
    TickerNotFound,
    flatten_facts,
    normalize_cik,
)

FIXTURES = Path(__file__).parent / "fixtures"


class FakeClient:
    """Serves fixture files by URL and counts calls."""

    def __init__(self):
        self.calls: list[str] = []
        self.routes = {
            TICKERS_URL: FIXTURES / "company_tickers.json",
            COMPANYFACTS_URL.format(cik="0000320193"): FIXTURES
            / "companyfacts_CIK0000320193.json",
            SUBMISSIONS_URL.format(cik="0000320193"): FIXTURES / "submissions_CIK0000320193.json",
        }

    def get_bytes(self, url: str) -> bytes:
        self.calls.append(url)
        if url not in self.routes:
            raise HttpError(url, 404, "Not Found")
        return self.routes[url].read_bytes()


@pytest.fixture
def client():
    return FakeClient()


# --- CIK handling ---------------------------------------------------------

@pytest.mark.parametrize(
    "raw, expected",
    [("320193", "0000320193"), (320193, "0000320193"), ("CIK0000320193", "0000320193")],
)
def test_normalize_cik(raw, expected):
    assert normalize_cik(raw) == expected


@pytest.mark.parametrize("bad", ["abc", "12345678901", ""])
def test_normalize_cik_rejects_bad(bad):
    with pytest.raises(ValueError):
        normalize_cik(bad)


def test_resolve_cik_case_insensitive(client):
    cik, title = SecCompanyFactsAdapter(client=client).resolve_cik(" aapl ")
    assert (cik, title) == ("0000320193", "Apple Inc.")


def test_resolve_cik_unknown(client):
    with pytest.raises(TickerNotFound):
        SecCompanyFactsAdapter(client=client).resolve_cik("ZZZZ")


# --- Flattening -----------------------------------------------------------

def test_flatten_counts_and_fields():
    payload = json.loads((FIXTURES / "companyfacts_CIK0000320193.json").read_text())
    facts = flatten_facts(payload)
    assert len(facts) == 5
    instant = next(f for f in facts if f["tag"] == "Assets")
    assert instant["start"] is None and instant["unit"] == "USD"
    # Duplicate comparative rows are preserved; dedupe is L1's job.
    fy22 = [f for f in facts if f["tag"] == "Revenues" and f["end"] == "2022-09-24"]
    assert len(fy22) == 2


def test_flatten_carries_description():
    payload = json.loads((FIXTURES / "companyfacts_CIK0000320193.json").read_text())
    facts = flatten_facts(payload)
    rev = [f for f in facts if f["tag"] == "Revenues"]
    assert rev and all(f["description"].startswith("Amount of revenue") for f in rev)
    # Tags without a description still carry the key, as null.
    assets = next(f for f in facts if f["tag"] == "Assets")
    assert "description" in assets and assets["description"] is None


def test_validator_requires_description_key(client):
    doc = SecCompanyFactsAdapter(client=client).fetch(cik="320193")
    del doc["facts"][0]["description"]
    assert any("facts[0].description" in e for e in validate_raw_filing(doc))


def test_flatten_is_deterministic():
    payload = json.loads((FIXTURES / "companyfacts_CIK0000320193.json").read_text())
    shuffled = json.loads(json.dumps(payload))
    shuffled["facts"]["us-gaap"]["Revenues"]["units"]["USD"].reverse()
    assert flatten_facts(payload) == flatten_facts(shuffled)


# --- End-to-end fetch -----------------------------------------------------

def test_fetch_by_ticker_produces_valid_doc(client):
    doc = SecCompanyFactsAdapter(client=client).fetch(ticker="AAPL")
    assert validate_raw_filing(doc) == []
    assert doc["entity"] == {"cik": "0000320193", "name": "Apple Inc.", "ticker": "AAPL",
                             "sic": "3571", "sic_description": "Electronic Computers"}
    assert doc["from_cache"] is False
    assert len(doc["content_sha256"]) == 64


def test_fetch_by_cik_skips_ticker_lookup(client):
    SecCompanyFactsAdapter(client=client).fetch(cik=320193)
    assert TICKERS_URL not in client.calls


def test_fetch_requires_exactly_one_identifier(client):
    adapter = SecCompanyFactsAdapter(client=client)
    with pytest.raises(ValueError):
        adapter.fetch()
    with pytest.raises(ValueError):
        adapter.fetch(ticker="AAPL", cik="320193")


# --- Caching --------------------------------------------------------------

def test_cache_hit_avoids_network(client, tmp_path):
    adapter = SecCompanyFactsAdapter(client=client, cache=FileCache(tmp_path))
    first = adapter.fetch(cik="320193")
    second = adapter.fetch(cik="320193")
    assert len(client.calls) == 2   # companyfacts + submissions, each once
    assert second["from_cache"] is True
    assert first["content_sha256"] == second["content_sha256"]
    assert first["retrieved_at"] == second["retrieved_at"]


def test_cache_expiry_refetches(client, tmp_path):
    now = [1_000_000.0]
    cache = FileCache(tmp_path, ttl_seconds=60, clock=lambda: now[0])
    adapter = SecCompanyFactsAdapter(client=client, cache=cache)
    adapter.fetch(cik="320193")
    now[0] += 61
    adapter.fetch(cik="320193")
    assert len(client.calls) == 4   # both files fetched again after expiry


def test_industry_lookup_failure_does_not_stop_ingest(client):
    client.routes.pop(SUBMISSIONS_URL.format(cik="0000320193"))
    doc = SecCompanyFactsAdapter(client=client).fetch(cik="320193")
    assert doc["entity"]["sic"] is None and validate_raw_filing(doc) == []


def test_cache_only_run_needs_no_user_agent(client, tmp_path, monkeypatch):
    monkeypatch.delenv("SEC_USER_AGENT", raising=False)
    SecCompanyFactsAdapter(client=client, cache=FileCache(tmp_path)).fetch(cik="320193")
    offline = SecCompanyFactsAdapter(cache=FileCache(tmp_path))  # no client, no UA
    assert offline.fetch(cik="320193")["from_cache"] is True


# --- HTTP client ----------------------------------------------------------

def test_http_client_requires_contact_user_agent():
    with pytest.raises(ValueError):
        HttpClient("")
    with pytest.raises(ValueError):
        HttpClient("my-script")


def test_http_client_retries_on_429():
    attempts = []

    def opener(req, timeout):
        attempts.append(req.get_header("User-agent"))
        if len(attempts) < 3:
            raise urllib.error.HTTPError(req.full_url, 429, "Too Many", {}, None)
        return io.BytesIO(b'{"ok": true}')

    c = HttpClient("Test tester@example.com", opener=opener, sleep=lambda s: None)
    assert c.get_bytes("https://example.test/x") == b'{"ok": true}'
    assert len(attempts) == 3
    assert attempts[0] == "Test tester@example.com"


def test_http_client_does_not_retry_404():
    attempts = []

    def opener(req, timeout):
        attempts.append(1)
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)

    c = HttpClient("Test tester@example.com", opener=opener, sleep=lambda s: None)
    with pytest.raises(HttpError) as exc:
        c.get_bytes("https://example.test/x")
    assert exc.value.status == 404 and len(attempts) == 1


# --- Schema validator -----------------------------------------------------

def test_validator_flags_problems(client):
    doc = SecCompanyFactsAdapter(client=client).fetch(cik="320193")
    del doc["facts"][0]["accn"]
    doc["facts"][1]["value"] = "lots"
    errors = validate_raw_filing(doc)
    assert any("facts[0].accn" in e for e in errors)
    assert any("facts[1].value" in e for e in errors)


def test_validator_missing_top_level():
    assert "missing top-level key: facts" in validate_raw_filing(
        {"schema_version": "0.2.0"}
    )


# --- CLI ------------------------------------------------------------------

def test_cli_fetch_and_validate(client, tmp_path):
    out = tmp_path / "raw" / "AAPL" / "raw_filing.json"

    def factory(**kw):
        return SecCompanyFactsAdapter(client=client, **kw)

    rc = main(
        ["sec-companyfacts", "--ticker", "AAPL", "--out", str(out),
         "--cache-dir", str(tmp_path / "cache")],
        adapter_factory=factory,
    )
    assert rc == 0 and out.exists()
    assert main(["validate", str(out)]) == 0
