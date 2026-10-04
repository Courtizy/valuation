"""Market data (offline): Yahoo primary, Alpha Vantage backup and cross-check, FRED risk-free,
beta and the market WACC estimate, and how the runner, DCF and comps use them.
Run: pytest tests/test_L0_market.py

tests/fixtures/yahoo_chart.json holds real Yahoo chart responses (AAPL and ^GSPC
monthly Sep 2021 - Oct 2026, AAPL daily to 2026-10-02), pulled 2026-10-03.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from valuation._core.market import beta, monthly_returns, wacc_estimate
from fakes import FakeSecClient
from valuation.L0_ingest.market import MarketAdapter, MarketDataError, parse_alphavantage, parse_fred, parse_yahoo
from valuation.L0_ingest.sec_companyfacts import SecCompanyFactsAdapter
from valuation.L1_detail.build import _market_block
from valuation.L2_models.comps import company_figures
from valuation.runner import Paths, execute, plan

FIXTURES = Path(__file__).parent / "fixtures"
FX = json.loads((FIXTURES / "yahoo_chart.json").read_text())
AS_OF = "2026-10-02"
FRED_CSV = "observation_date,DGS10\n2026-09-29,5.26\n2026-09-30,5.29\n2026-10-01,5.24\n2026-10-02,.\n"


FUND = (FIXTURES / "yahoo_fundamentals.json").read_text()


def yahoo_route(url: str):
    if "fundamentals-timeseries" in url:
        return FUND if "/timeseries/AAPL?" in url else None
    sym = url.split("/chart/")[1].split("?")[0]
    if "interval=1d" in url and sym == "AAPL":
        return json.dumps(FX["AAPL_1d"])
    if "interval=1mo" in url:
        return json.dumps(FX["AAPL_1mo" if sym == "AAPL" else "GSPC_1mo" if sym == "%5EGSPC" else "missing"]) \
            if sym in ("AAPL", "%5EGSPC") else None
    return None


def av_route(bump: float = 1.0, notice: str | None = None):
    """Alpha Vantage-shaped series built from the Yahoo fixture (SPY stands in for the index), scaled by `bump`."""
    def route(url: str):
        if notice:
            return json.dumps({"Information": notice})
        sym = url.split("symbol=")[1].split("&")[0]
        key = {"AAPL": "AAPL", "SPY": "GSPC"}.get(sym)
        monthly = "MONTHLY_ADJUSTED" in url
        if not key or (key == "GSPC" and not monthly):
            return None
        rows = parse_yahoo(FX[f"{key}_{'1mo' if monthly else '1d'}"])["rows"]
        series = {d: {"4. close": str(c * bump), **({"5. adjusted close": str(a * bump)} if monthly else {})} for d, c, a in rows}
        return json.dumps({"Meta Data": {}, ("Monthly Adjusted Time Series" if monthly else "Time Series (Daily)"): series})
    return route


def adapter(yahoo=yahoo_route, av_bump=1.0, key="test-key", notice=None):
    return MarketAdapter(yahoo=FakeSecClient(fallback=yahoo), alphavantage=FakeSecClient(fallback=av_route(av_bump, notice)),
                         fred=FakeSecClient(fallback=lambda url: FRED_CSV), av_key=key)


# ---------------------------------------------------------------- L0

def test_yahoo_price_is_last_close_on_or_before_as_of():
    doc = adapter().fetch("AAPL", AS_OF)
    assert doc["source"] == "yahoo" and not doc["fallback"]
    assert doc["price"] == pytest.approx(333.69) and doc["price_date"] == AS_OF
    earlier = adapter().fetch("AAPL", "2026-09-27")          # a Sunday: Friday's close, never a later one
    assert earlier["price_date"] == "2026-09-25" and earlier["price"] == pytest.approx(341.07)
    assert doc["monthly"][-1]["month"] == "2026-10" and len({p["month"] for p in doc["monthly"]}) == len(doc["monthly"])
    assert doc["index"]["symbol"] == "^GSPC" and doc["check"] is None


def test_cross_check_ok_mismatch_and_skipped():
    assert adapter().fetch("AAPL", AS_OF, cross_check=True)["check"]["status"] == "ok"
    off = adapter(av_bump=1.03).fetch("AAPL", AS_OF, cross_check=True)["check"]
    assert off["status"] == "mismatch" and off["diff_pct"] == pytest.approx(0.03)
    assert adapter(key="").fetch("AAPL", AS_OF, cross_check=True)["check"]["status"] == "skipped"


def test_falls_back_to_alphavantage_when_yahoo_fails():
    doc = adapter(yahoo=lambda url: None).fetch("AAPL", AS_OF, cross_check=True)
    assert doc["source"] == "alphavantage" and doc["fallback"] and doc["index"]["symbol"] == "SPY"
    assert doc["monthly"][-1]["month"] == "2026-10" and len(doc["monthly"]) >= 60
    assert doc["price"] == pytest.approx(333.69) and doc["check"] is None and doc["errors"][0].startswith("yahoo:")
    with pytest.raises(MarketDataError):
        adapter(yahoo=lambda url: None, key="").fetch("AAPL", AS_OF)


def test_alphavantage_notices_and_key_redaction():
    with pytest.raises(MarketDataError, match="rate limit"):
        parse_alphavantage({"Information": "rate limit reached"})
    capped = adapter(notice="25 requests per day reached").fetch("AAPL", AS_OF, cross_check=True)["check"]
    assert capped["status"] == "unavailable" and "25 requests" in capped["note"]
    from valuation.L0_ingest.http import HttpError

    class Boom:
        def get_bytes(self, url):
            raise HttpError(url, 500, "server error")
    a = MarketAdapter(yahoo=Boom(), alphavantage=Boom(), fred=Boom(), av_key="SECRETKEY")
    with pytest.raises(MarketDataError) as e:
        a.fetch("AAPL", AS_OF)
    assert "SECRETKEY" not in str(e.value) and "***" in str(e.value)


def test_risk_free_skips_missing_days():
    assert parse_fred(FRED_CSV)[-1] == ("2026-10-01", pytest.approx(0.0524))
    rf = adapter().risk_free(AS_OF)
    assert rf == {"series": "DGS10", "value": pytest.approx(0.0524), "date": "2026-10-01", "source": "FRED (Federal Reserve H.15)"}


# ---------------------------------------------------------------- core math + L1

def test_beta_matches_the_published_five_year_monthly_figure():
    doc = adapter().fetch("AAPL", AS_OF)
    b = beta(doc["monthly"], doc["index"]["monthly"])
    assert b["months"] == 60 and b["value"] == pytest.approx(1.08, abs=0.01)   # Yahoo shows 1.09 for the same window
    assert beta(doc["monthly"][-10:], doc["index"]["monthly"][-10:]) is None     # too few months
    gap = [p for p in doc["monthly"] if p["month"] != "2024-06"]
    assert "2024-07" not in monthly_returns(gap)                                 # no return across a missing month


def test_wacc_estimate_cost_of_debt_basis():
    w = wacc_estimate(beta_value=1.0, risk_free=0.04, market_cap=900, debt=100, interest_expense=6, tax_rate=0.2)
    assert w["cost_of_debt_basis"] == "interest / debt" and w["value"] == pytest.approx(0.09 * 0.9 + 0.06 * 0.8 * 0.1)
    low = wacc_estimate(beta_value=1.0, risk_free=0.04, market_cap=900, debt=100, interest_expense=1, tax_rate=None)
    assert low["cost_of_debt_basis"] == "risk-free + spread" and low["tax_rate"] == 0.21


def test_market_block_uses_filing_share_count_and_adds_wacc():
    raw = adapter().fetch("AAPL", AS_OF, cross_check=True)
    views = {"quarterly": [{"values": {"shares_year_end": 14.7e9}}],
             "ttm": [{"values": {"long_term_debt": 90e9, "short_term_debt": 10e9, "interest_expense": 4e9, "effective_tax_rate": 0.16}}]}
    m = _market_block(raw, AS_OF, views, {"value": 0.0524, "date": "2026-10-01", "series": "DGS10"})
    assert m["market_cap"] == pytest.approx(333.69 * 14.7e9) and m["beta"]["index"] == "^GSPC"
    assert m["check"]["status"] == "ok" and 0.08 < m["wacc"]["value"] < 0.11
    assert "monthly" not in m                       # the price history stays in raw_market.json
    with pytest.raises(ValueError):
        _market_block({**raw, "price_date": "2026-10-05"}, AS_OF, views)


# ---------------------------------------------------------------- L2 + runner

def test_comps_peer_price_from_market_data_unless_typed():
    detail = {"views": {"annual": [{"values": {"revenue": 10, "shares_year_end": 5}}]},
              "market": {"price": 20.0, "shares_outstanding": 6, "source": "yahoo", "price_date": AS_OF}}
    assert company_figures(detail)["price"] == 20.0 and company_figures(detail)["shares"] == 6
    typed = company_figures(detail, {"price": 25.0})
    assert typed["price"] == 25.0 and typed["price_source"] == "comps.json"


def test_dcf_fills_blank_price_beta_and_risk_free_from_market_data(tmp_path):
    from valuation.L2_models.base import get_model
    from valuation.L3_app.demo import write_demo
    detail = json.loads((write_demo(tmp_path) / "company_detail.json").read_text())
    detail["market"] = {"price": 41.0, "price_date": AS_OF, "source": "yahoo",
                        "beta": {"value": 1.2, "months": 60, "index": "^GSPC"}, "wacc": {"risk_free": 0.045, "risk_free_date": "2026-10-01"}}
    a = {"mode": "forecast", "market": {"price": None, "basic_shares": 330e6},
         "forecast": {"revenue_growth": 0.05, "terminal_growth": 0.025, "tax_rate": 0.21},
         "cost_of_capital": {"risk_free": None, "beta": None, "equity_risk_premium": 0.05, "pre_tax_cost_of_debt": 0.06}}
    r = get_model("dcf").run(detail, deepcopy(a)).to_dict()
    d = r["details"]
    assert d["market_price"] == 41.0 and d["rates"]["beta_levered_observed"] == 1.2
    assert "market data" in r["assumptions_used"]["sources"]["price"]
    a["cost_of_capital"]["beta"] = 0.9                                   # a value in the file wins
    assert get_model("dcf").run(detail, a).to_dict()["details"]["rates"]["beta_levered_observed"] == 0.9


def sec_factory():
    return SecCompanyFactsAdapter(client=FakeSecClient(fallback=lambda url: FIXTURES / (
        "company_tickers.json" if url.endswith("company_tickers.json") else "companyfacts_CIK0000320193.json")))


def test_runner_adds_market_steps_and_detail_gets_market_block(tmp_path):
    paths = Paths(tmp_path / "data", tmp_path / "assumptions")
    steps = plan("AAPL", ["dcf"], AS_OF, paths, sec_factory, "L1", market_factory=adapter)
    assert [s.name for s in steps] == ["risk-free rate", "ingest AAPL", "market AAPL", "normalize AAPL", "build detail AAPL"]
    report = execute(steps)
    assert all(st == "done" for _, st, _ in report), report
    m = json.loads(paths.detail("AAPL", AS_OF).read_text())["market"]
    assert m["price"] == pytest.approx(333.69) and m["check"]["status"] == "ok" and m["wacc"]["risk_free"] == pytest.approx(0.0524)


def test_market_failure_is_a_warning_and_the_run_continues(tmp_path):
    paths = Paths(tmp_path / "data", tmp_path / "assumptions")
    dead = lambda: adapter(yahoo=lambda url: None, key="")   # noqa: E731
    report = execute(plan("AAPL", ["dcf"], AS_OF, paths, sec_factory, "L1", market_factory=dead))
    status = {n: st for n, st, _ in report}
    assert status["market AAPL"] == "warning" and status["build detail AAPL"] == "done"
    assert json.loads(paths.detail("AAPL", AS_OF).read_text())["market"] is None


# ---------------------------------------------------------------- showcase mode (public site)

def test_showcase_runs_fetch_only_the_risk_free_rate(tmp_path):
    paths = Paths(tmp_path / "data", tmp_path / "assumptions")
    steps = plan("AAPL", ["dcf"], AS_OF, paths, sec_factory, "L1", market_factory=adapter, market_prices=False)
    assert [s.name for s in steps] == ["risk-free rate", "ingest AAPL", "normalize AAPL", "build detail AAPL"]


def test_showcase_filter_keeps_synthetic_and_strips_real_market_figures():
    from valuation.L3_app.publish import showcase_filter
    real = {"market": {"price": 333.69, "source": "yahoo"}}
    assert showcase_filter("company_detail.json", real)["market"] is None
    synthetic = {"market": {"price": 45.0, "source": "synthetic"}}
    assert showcase_filter("company_detail.json", synthetic)["market"]["price"] == 45.0
    assert showcase_filter("company_detail.json", {**real, "demo": True})["market"]["price"] == 333.69
    comp = showcase_filter("comparison.json", {"price": 333.69, "price_source": "market data", "upside": {"p50": 0.1}})
    assert comp["price"] is None and comp["upside"] is None
    typed = showcase_filter("comparison.json", {"price": 300.0, "price_source": "dcf assumptions", "upside": {"p50": 0.1}})
    assert typed["price"] == 300.0                              # a price you typed yourself is your call
    comps = {"details": {"peers": [{"ticker": "MSFT", "price_source": "market data (yahoo, 2026-10-02)"}]}}
    assert showcase_filter("comps.json", comps) is None
    dcf = {"assumptions_used": {"sources": {"price": "close 2026-10-02 from market data (yahoo)"}},
           "details": {"market_price": 333.69, "implied_growth": 0.05}}
    assert showcase_filter("dcf.json", dcf)["details"]["market_price"] is None


def test_publish_records_the_market_mode(tmp_path):
    from valuation.L3_app.publish import publish
    site = tmp_path / "site"
    publish(tmp_path / "data", site)
    assert json.loads((site / "data" / "index.json").read_text())["market_data"] == "showcase"
    publish(tmp_path / "data", site, "real")
    assert json.loads((site / "data" / "index.json").read_text())["market_data"] == "real"
    with pytest.raises(ValueError):
        publish(tmp_path / "data", site, "live")


# ---------------------------------------------------------------- Yahoo backfill (private runs)

def test_fundamentals_parsed_and_cut_at_as_of():
    from valuation.L0_ingest.market import parse_fundamentals
    s = parse_fundamentals(json.loads(FUND))
    assert s["annualCapitalExpenditure"][-1] == {"end": "2025-09-30", "value": -12715000000, "period": "12M", "currency": "USD"}
    f = adapter().fundamentals("AAPL", "2026-01-15")
    assert all(r["end"] <= "2026-01-15" for rows in f["series"].values() for r in rows)


def test_backfill_fills_only_gaps_in_periods_the_filings_define(tmp_path):
    paths = Paths(tmp_path / "data", tmp_path / "assumptions")
    execute(plan("AAPL", ["dcf"], AS_OF, paths, sec_factory, "L1", market_factory=adapter))
    det = json.loads(paths.detail("AAPL", AS_OF).read_text())
    filled = {(b["concept"], b["end"]) for b in det["backfill"]}
    # the two-fact SEC fixture has revenue for FY2022 (52-week year ending 2022-09-24) and FY2023
    assert ("depreciation_amortization_cf", "2022-09-24") in filled          # matched despite the 6-day offset
    assert ("capital_expenses", "2023-09-30") in filled
    assert not any(c == "revenue" for c, _ in filled)                        # filed revenue is never replaced
    fy23 = next(p for p in det["views"]["annual"] if p["label"] == "FY2023")
    assert fy23["values"]["revenue"] == 383285000000 and fy23["methods"]["revenue"] != "yahoo_backup"
    assert fy23["values"]["capital_expenses"] == 10959000000                 # Yahoo's negative capex flipped
    assert fy23["methods"]["depreciation_amortization_cf"] == "yahoo_backup"
    assert not any(e > "2026" for _, e in filled)                            # no period the filings don't define


def test_backfill_respects_filing_lag():
    from valuation.L1_detail.backfill import backfill_records
    from valuation.L1_detail.registry import load_registry
    recs = [{"concept": "revenue", "period_type": "duration", "months": 3, "end": "2026-06-30", "start": "2026-04-01",
             "fiscal_year": 2026, "fiscal_period": "Q3"}]
    fund = {"series": {"quarterlyReconciledDepreciation": [{"end": "2026-06-30", "value": 5, "period": "3M", "currency": "USD"}]}}
    assert backfill_records(recs, fund, load_registry(), "2026-07-20") == []            # 20 days: not yet filed
    assert len(backfill_records(recs, fund, load_registry(), "2026-08-15")) == 1


def test_showcase_publish_skips_runs_with_backfill(tmp_path):
    from valuation.L3_app.publish import publish
    run = tmp_path / "data" / "DELL" / "2026-10-02"
    run.mkdir(parents=True)
    (run / "company_detail.json").write_text(json.dumps({"backfill": [{"concept": "ebitda"}], "views": {}, "analysis": {}}))
    out = publish(tmp_path / "data", tmp_path / "site")
    assert not any(c.startswith("DELL") for c in out["copied"])
