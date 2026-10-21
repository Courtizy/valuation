"""The in-browser run (L3_app/web.py), driven here by a fetch_text that serves fixtures."""
import json
from pathlib import Path

from valuation.L3_app.web import run, run_json

FIXTURES = Path(__file__).parent / "fixtures"
AS_OF = "2026-10-03"
FRED = "observation_date,DGS10\n2026-10-01,4.10\n2026-10-02,4.12\n"


def fetch_text(calls):
    def get(url):
        calls.append(url)
        if url.endswith("company_tickers.json"):
            return (FIXTURES / "company_tickers.json").read_text()
        if "companyfacts" in url:
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
