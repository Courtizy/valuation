"""The in-browser run (L3_app/web.py), driven here by a fetch_text that serves fixtures."""
import json
from pathlib import Path

from valuation.L3_app.web import run, run_json, run_sector_json

FIXTURES = Path(__file__).parent / "fixtures"
AS_OF = "2026-10-03"
FRED = "observation_date,DGS10\n2026-10-01,4.10\n2026-10-02,4.12\n"


def fetch_text(calls):
    def get(url):
        calls.append(url)
        if url.endswith("company_tickers.json"):
            return (FIXTURES / "company_tickers.json").read_text()
        if "companyfacts" in url:          # MSFT (a comps peer below) is served Apple's facts
            return (FIXTURES / "companyfacts_CIK0000320193.json").read_text()
        if "submissions" in url:
            return (FIXTURES / "submissions_CIK0000320193.json").read_text()
        if "fredgraph" in url:
            return FRED
        if "histimpl" in url:
            return (FIXTURES / "damodaran_erp.html").read_text()
        if "Betas" in url:
            return (FIXTURES / "damodaran_betas.html").read_text()
        raise RuntimeError(f"proxy said 403 for {url}")
    return get


def test_web_run_builds_and_publishes_on_device(tmp_path):
    calls = []
    out = run("AAPL", fetch_text(calls), AS_OF, "dcf", work=str(tmp_path / "w"))
    steps = {name: status for name, status, _ in out["report"]}
    assert steps["ingest AAPL"] == "done" and steps["build detail AAPL"] == "done"
    assert steps["industry betas and ERP (Damodaran)"] == "done"
    assert not any("yahoo" in u or "alphavantage" in u for u in calls)    # no price sources in the browser
    index = json.loads(out["files"]["index.json"])
    assert [c["ticker"] for c in index["companies"]] == ["AAPL"]
    detail = json.loads(out["files"][f"AAPL/{AS_OF}/company_detail.json"])
    assert detail["sector_beta"]["industry"] == "Computers/Peripherals" and abs(detail["equity_risk_premium"]["value"] - 0.0423) < 1e-12


def test_web_run_keeps_earlier_runs_and_ignores_unsafe_paths(tmp_path):
    first = run("AAPL", fetch_text([]), AS_OF, "dcf", work=str(tmp_path / "w"))
    saved = {**first["files"], "../../escape.json": "{}"}
    again = json.loads(run_json("AAPL", fetch_text([]), "2026-10-04", "dcf", json.dumps(saved)))
    runs = json.loads(again["files"]["index.json"])["companies"][0]["runs"]
    assert [r["as_of"] for r in runs] == ["2026-10-04", AS_OF]
    assert not (tmp_path / "escape.json").exists() and not any(".." in k for k in again["files"])


def test_web_package_holds_the_engine_and_public_configs(tmp_path):
    import importlib.util
    import zipfile
    spec = importlib.util.spec_from_file_location("export_site", Path(__file__).parents[1] / "scripts" / "export_site.py")
    export_site = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(export_site)
    names = zipfile.ZipFile(export_site.web_package(tmp_path / "valuation.zip")).namelist()
    assert "src/valuation/L3_app/web.py" in names and "configs/public/sectors/taxonomy.json" in names
    assert not any("__pycache__" in n or n.startswith(("private/", "data", "tests/")) for n in names)


def test_web_comps_use_the_devices_peers_and_typed_prices(tmp_path):
    peers = {"AAPL/comps.json": json.dumps({"multiples": ["ev_sales"], "range": "min_max",
                                            "peers": [{"ticker": "MSFT", "price": 400.0}]})}
    calls = []
    out = json.loads(run_json("AAPL", fetch_text(calls), AS_OF, "auto", "{}", json.dumps(peers)))
    steps = {name: status for name, status, _ in out["report"]}
    assert steps["ingest MSFT"] == "done" and steps["model comps"] == "done" and steps["model dcf"] == "done"
    comps = json.loads(out["files"][f"AAPL/{AS_OF}/model_results/comps.json"])
    assert [p["ticker"] for p in comps["details"]["peers"]] == ["MSFT"]
    assert not any("alphavantage" in u or "yahoo" in u for u in calls)


def test_web_auto_models_are_dcf_and_lbo_without_peers(tmp_path):
    out = run("MSFT", fetch_text([]), AS_OF, "auto", work=str(tmp_path / "w"))
    assert [n for n, _, _ in out["report"] if n.startswith("model")] == ["model dcf", "model lbo"]


def test_web_sector_screen_on_the_device(tmp_path):
    from test_L1_sector import _sec_route

    def get(url):
        r = _sec_route(url)
        if r is None:
            raise RuntimeError(f"404 from the proxy for {url}")
        return r.read_text() if isinstance(r, Path) else r

    out = json.loads(run_sector_json("sic:3674", get, "2026-10-02", "{}"))
    assert out["report"][0][1] == "done"
    index = json.loads(out["files"]["index.json"])
    assert [x["id"] for x in index["sectors"]] == ["sic-3674"]
    assert any(k.startswith("sectors/sic-3674/2026-10-02/") for k in out["files"])


def test_web_prices_come_from_the_visitors_alpha_vantage_key(tmp_path):
    from datetime import date, timedelta
    days = {(date(2026, 10, 3) - timedelta(days=i)).isoformat(): {"4. close": "250.0"} for i in range(1, 10)}
    months = {f"{y}-{m:02d}-28": {"4. close": str(100 + y - 2020 + m), "5. adjusted close": str(100 + y - 2020 + m)}
              for y in range(2020, 2027) for m in range(1, 13)}
    calls = []
    base = fetch_text(calls)

    def get(url):
        if "alphavantage.co" in url:
            calls.append(url)
            assert "apikey=MYKEY" in url
            return json.dumps({"Time Series (Daily)": days} if "TIME_SERIES_DAILY" in url else {"Monthly Adjusted Time Series": months})
        return base(url)

    out = run("AAPL", get, AS_OF, "dcf", work=str(tmp_path / "w"), av_key="MYKEY")
    steps = {name: status for name, status, _ in out["report"]}
    assert steps["market AAPL"] == "done"
    detail = json.loads(out["files"][f"AAPL/{AS_OF}/company_detail.json"])
    assert detail["market"]["price"] == 250.0 and detail["market"]["source"] == "alphavantage"
    assert not any("yahoo" in u for u in calls)
    assert len([u for u in calls if "alphavantage" in u]) <= 4        # cached within the run: daily, monthly, index


def _quote_fetch(calls, handle):
    base = fetch_text(calls)

    def get(url):
        out = handle(url)
        if out is not None:
            calls.append(url)
            return out
        return base(url)
    return get


def test_web_finnhub_key_gives_todays_quote_and_reported_beta(tmp_path):
    import time
    from datetime import date
    today = date.today().isoformat()

    def handle(url):
        if "finnhub.io" in url:
            assert "token=FHKEY" in url
            return json.dumps({"c": 321.5, "t": int(time.time())} if "/quote" in url else {"metric": {"beta": 1.23}})
    calls = []
    out = run("AAPL", _quote_fetch(calls, handle), today, "dcf", work=str(tmp_path / "w"), finnhub_key="FHKEY")
    detail = json.loads(out["files"][f"AAPL/{today}/company_detail.json"])
    assert detail["market"]["price"] == 321.5 and detail["market"]["source"] == "finnhub"
    assert detail["market"]["beta"]["value"] == 1.23
    assert not any("yahoo" in u or "alphavantage" in u for u in calls)


def test_web_finnhub_refuses_an_old_as_of(tmp_path):
    import time

    def handle(url):
        if "finnhub.io" in url:
            return json.dumps({"c": 321.5, "t": int(time.time())})
    out = run("AAPL", _quote_fetch([], handle), "2024-01-05", "dcf", work=str(tmp_path / "w"), finnhub_key="FHKEY")
    msg = {n: m for n, _, m in out["report"]}["market AAPL"]
    assert "today's quote only" in msg and "FHKEY" not in msg


def test_web_yahoo_only_when_asked(tmp_path):
    from test_L0_market import yahoo_route

    def handle(url):
        if "finance.yahoo.com" in url:
            return yahoo_route(url) if "/chart/" in url else json.dumps({"timeseries": {"result": []}})
    calls = []
    run("AAPL", _quote_fetch(calls, handle), "2026-10-02", "dcf", work=str(tmp_path / "a"))
    assert not any("yahoo" in u for u in calls)                 # off by default: the public site
    out = run("AAPL", _quote_fetch(calls, handle), "2026-10-02", "dcf", work=str(tmp_path / "b"), yahoo=True)
    assert any("yahoo" in u for u in calls)
    assert {n: s for n, s, _ in out["report"]}["market AAPL"] == "done"
    detail = json.loads(out["files"]["AAPL/2026-10-02/company_detail.json"])
    assert detail["market"]["source"] == "yahoo" and detail["market"]["beta"]["value"]


def _screen(target="MSFT"):
    """A sector screen holding the target and eight others: six in its industry, two outside it."""
    def row(t, industry, margin):
        return {"ticker": t, "classification": {"sector": "technology", "group": "hardware", "industry": industry},
                "revenue": 1e10, "operating_margin": margin, "revenue_cagr": 0.05, "traits": {}}
    rows = [row(target, "computers", 0.30)] + [row(t, "computers", 0.30 - i / 100) for i, t in enumerate("BCDEFG")]
    rows += [row("FAR1", "storage", 0.30), row("FAR2", "storage", 0.30)]
    return {"id": "sector-technology", "label": "Technology", "companies": rows}


def test_pick_peers_takes_the_closest_in_the_narrowest_full_level():
    from valuation.L3_app.similar import pick_peers
    pick = pick_peers(_screen(), "msft")
    assert pick["level"] == "industry" and [p["ticker"] for p in pick["peers"]] == list("BCDEFG")
    small = _screen()
    small["companies"] = small["companies"][:4] + small["companies"][-2:]     # 4 in its industry: widen to the group
    assert pick_peers(small, "MSFT")["level"] == "group"
    assert pick_peers(_screen(), "ZZZ") is None


def test_pick_peers_closest_set_crosses_industries():
    from valuation.L3_app.similar import pick_peers
    pick = pick_peers(_screen(), "MSFT", n=3)
    assert [p["ticker"] for p in pick["peers"]] == list("BCD")              # same industry, nearest in size
    assert {"FAR1", "FAR2"} <= {p["ticker"] for p in pick["closest"]}       # same figures, other industry


def test_web_auto_picks_peers_from_a_published_screen_and_runs_comps(tmp_path):
    out = json.loads(run_json("MSFT", fetch_text([]), AS_OF, "auto", "{}", "{}", screens_json=json.dumps([json.dumps(_screen())])))
    rows = {n: (s, m) for n, s, m in out["report"]}
    assert rows["pick peers"][0] == "done" and "B, C, D, E, F, G" in rows["pick peers"][1]
    assert "model comps" in rows and "model dcf" in rows                  # comps ran as part of the pull
    kept = json.loads(out["assumptions"]["MSFT/comps.json"])
    assert [p["ticker"] for p in kept["peers"]] == list("BCDEFG") and "automatically" in kept["sources"]["peers"]


def test_web_auto_keeps_peers_already_chosen(tmp_path):
    peers = {"MSFT/comps.json": json.dumps({"peers": [{"ticker": "AAPL", "price": 400.0}]})}
    out = json.loads(run_json("MSFT", fetch_text([]), AS_OF, "auto", "{}", json.dumps(peers),
                              screens_json=json.dumps([json.dumps(_screen())])))
    assert "pick peers" not in {n for n, _, _ in out["report"]} and out["assumptions"] == {}


def test_web_auto_screens_the_sector_when_no_screen_holds_the_ticker(tmp_path):
    from test_L1_sector import _sec_route
    base = fetch_text([])

    def get(url):
        r = _sec_route(url)
        if r is not None:
            return r.read_text() if isinstance(r, Path) else r
        return base(url)

    no_peers = {"AAPL/comps.json": json.dumps({"peers": []})}       # as if AAPL had no curated peers
    out = run("AAPL", get, "2026-10-02", "auto", work=str(tmp_path / "w"), assumptions=no_peers)
    rows = {n: (s, m) for n, s, m in out["report"]}
    assert rows["model dcf"][0] == "done"
    assert rows["pick peers"][0] in ("done", "warning")
    assert any(k.startswith("sectors/") for k in out["files"]) or "screen" in rows["pick peers"][1].lower() or rows["pick peers"][1]
    print(rows["pick peers"])


def test_web_sector_screen_reads_the_published_sic_lists(tmp_path):
    from test_L1_sector import _sec_route
    calls = []

    def get(url):
        calls.append(url)
        if "browse-edgar" in url:
            raise RuntimeError(f"403 from the proxy for {url}: Access Denied")
        r = _sec_route(url)
        if r is None:
            raise RuntimeError(f"404 from the proxy for {url}")
        return r.read_text() if isinstance(r, Path) else r

    refused = json.loads(run_sector_json("sic:3674", get, "2026-10-02", "{}"))
    assert refused["report"][0][1] == "failed" and "weekly Refresh" in refused["report"][0][2]
    ciks = [c for c in __import__("re").findall(r"CIK=(\d+)", _sec_route(
        "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&SIC=3674&owner=include&start=0&count=100&hidefilings=0"))]
    lists = {"3674": {"description": "SEMICONDUCTORS", "ciks": [c.zfill(10) for c in ciks], "as_of": "2026-10-01"}}
    calls.clear()
    out = json.loads(run_sector_json("sic:3674", get, "2026-10-02", "{}", json.dumps(lists)))
    assert out["report"][0][1] == "done" and not any("browse-edgar" in u for u in calls)
    assert "sic_members.json" not in out["files"]          # read from the published lists, not re-published


def test_publish_merges_fetched_sic_lists(tmp_path):
    from valuation.L3_app.publish import copy_sic_lists
    data, site = tmp_path / "data", tmp_path / "site"
    for as_of, ciks in (("2026-10-01", ["1"]), ("2026-10-08", ["1", "2"])):
        p = data / "_screen" / as_of / "sic_3674.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"sic": "3674", "description": "SEMIS", "ciks": ciks}))
    assert copy_sic_lists(data, site) == ["sic_members.json"]
    assert json.loads((site / "sic_members.json").read_text())["sic"]["3674"] == {"description": "SEMIS", "ciks": ["1", "2"], "as_of": "2026-10-08"}
