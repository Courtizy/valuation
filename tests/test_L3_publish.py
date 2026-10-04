"""L3: publishing pipeline outputs to the static site. Run: pytest tests/test_L3_publish.py"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from valuation.L1_detail.build import validate_detail
from valuation.L3_app.demo import write_demo
from valuation.L3_app.publish import publish
from valuation.runner import Paths, plan

ROOT = Path(__file__).resolve().parent.parent


def test_publish_copies_outputs_and_indexes(tmp_path):
    data = tmp_path / "data"
    run = data / "ABC" / "2026-09-30"
    (run / "model_results").mkdir(parents=True)
    (run / "company_detail.json").write_text(json.dumps({"entity": {"name": "ABC Inc."}, "latest": {"ttm": "x"}}))
    (run / "canonical_statements.json").write_text("{}")         # never published
    (run / "model_results" / "dcf.json").write_text("{}")
    (data / "ABC" / "raw").mkdir()
    (data / "ABC" / "raw" / "raw_filing.json").write_text("{}")   # never published
    site = tmp_path / "site"
    out = publish(data, site)
    assert sorted(out["copied"]) == ["ABC/2026-09-30/company_detail.json", "ABC/2026-09-30/company_detail_full.json",
                                     "ABC/2026-09-30/model_results/dcf.json"]
    index = json.loads((site / "data" / "index.json").read_text())
    (c,) = index["companies"]
    assert c["ticker"] == "ABC" and c["name"] == "ABC Inc." and not c["demo"]
    assert c["runs"][0] == {"as_of": "2026-09-30", "detail": "ABC/2026-09-30/company_detail.json",
                            "full": "ABC/2026-09-30/company_detail_full.json", "comparison": None, "models": ["dcf"], "latest": {"ttm": "x"}}
    # earlier runs already in site/data stay listed
    publish(tmp_path / "empty", site)
    assert json.loads((site / "data" / "index.json").read_text())["companies"][0]["ticker"] == "ABC"


def test_publish_sectors_and_skips_raw_screens(tmp_path):
    data = tmp_path / "data"
    run = data / "ABC" / "2026-09-30"
    run.mkdir(parents=True)
    (run / "company_detail.json").write_text(json.dumps({"entity": {"name": "ABC Inc.", "sic": "3674"}}))
    for as_of in ("2026-09-30", "2026-10-02"):
        d = data / "sectors" / "sic-3674" / as_of
        d.mkdir(parents=True)
        (d / "sector.json").write_text(json.dumps({"id": "sic-3674", "label": "SIC 3674", "kind": "sic", "year": 2025,
                                                   "companies": [{"ticker": "ABC"}, {"ticker": "XYZ"}]}))
    (data / "_screen" / "2026-10-02").mkdir(parents=True)
    (data / "_screen" / "2026-10-02" / "raw_screen.json").write_text("{}")    # never published
    site = tmp_path / "site"
    out = publish(data, site)
    assert "sectors/sic-3674/2026-10-02/sector.json" in out["copied"]
    assert not any("_screen" in c for c in out["copied"]) and out["companies"] == ["ABC"]
    (s,) = json.loads((site / "data" / "index.json").read_text())["sectors"]
    assert s["as_of"] == "2026-10-02" and s["members"] == ["ABC", "XYZ"] and s["count"] == 2
    assert s["path"] == "sectors/sic-3674/2026-10-02/sector.json" and s["as_of_all"] == ["2026-10-02", "2026-09-30"]
    card = json.loads((site / "data" / "companies.json").read_text())["companies"][0]
    assert card["sic"] == "3674"


def test_site_copy_is_sliced_compact_and_full_history_kept(tmp_path):
    data = tmp_path / "data"
    run = data / "ABC" / "2026-09-30"
    run.mkdir(parents=True)
    detail = {"entity": {"name": "ABC"}, "views": {"annual": [{"label": f"FY{y}"} for y in range(2000, 2026)],
              "quarterly": [{}] * 40, "ttm": [{}] * 40}, "analysis": {"annual": [{}] * 26, "ttm": [{}] * 40}}
    (run / "company_detail.json").write_text(json.dumps(detail, indent=2))
    publish(data, tmp_path / "site")
    site = tmp_path / "site" / "data" / "ABC" / "2026-09-30"
    small, full = json.loads((site / "company_detail.json").read_text()), json.loads((site / "company_detail_full.json").read_text())
    assert len(small["views"]["annual"]) == 11 and small["views"]["annual"][-1]["label"] == "FY2025"
    assert len(small["analysis"]["ttm"]) == 12 and len(full["views"]["annual"]) == 26
    assert "\n" not in (site / "company_detail.json").read_text()        # compact


def test_site_keeps_latest_three_runs(tmp_path):
    data = tmp_path / "data"
    for d in ("2026-06-30", "2026-07-31", "2026-08-31", "2026-09-30"):
        (data / "ABC" / d).mkdir(parents=True)
        (data / "ABC" / d / "company_detail.json").write_text(json.dumps({"entity": {"name": "ABC"}}))
    out = publish(data, tmp_path / "site")
    assert out["removed"] == ["ABC/2026-06-30"]
    assert [r["as_of"] for r in json.loads((tmp_path / "site" / "data" / "index.json").read_text())["companies"][0]["runs"]] == \
        ["2026-09-30", "2026-08-31", "2026-07-31"]


def test_demo_is_valid_and_flagged(tmp_path):
    out = write_demo(tmp_path)
    detail = json.loads((out / "company_detail.json").read_text())
    assert detail["demo"] is True and "synthetic" in detail["entity"]["name"]
    assert validate_detail(detail) == []
    assert len(detail["views"]["annual"]) == 5 and detail["views"]["ttm"]
    comp = json.loads((out / "comparison.json").read_text())
    assert comp["demo"] is True and len(comp["football_field"]) == 3


def test_plan_stop_after_drops_later_layers(tmp_path):
    paths = Paths(tmp_path / "data", tmp_path / "assumptions")
    names = [s.name for s in plan("AAPL", ["dcf"], "2026-09-30", paths, lambda: None, stop_after="L1")]
    assert names == ["ingest AAPL", "normalize AAPL", "build detail AAPL"]
    with pytest.raises(KeyError):
        plan("AAPL", ["dcf"], "2026-09-30", paths, lambda: None, stop_after="L9")


def test_site_references_exist():
    html = (ROOT / "site" / "index.html").read_text()
    for ref in re.findall(r'(?:src|href)="(assets/[^"]+)"', html):
        assert (ROOT / "site" / ref).exists(), ref


def test_brand_references_come_from_the_repo_brand_folder():
    """site/brand is copied from brand/ by scripts/export_site.py, so check the source."""
    html = (ROOT / "site" / "index.html").read_text()
    refs = re.findall(r'(?:src|href)="brand/([^"]+)"', html)
    assert refs and all((ROOT / "brand" / r).exists() for r in refs), refs


def test_export_changelog_parses():
    import importlib.util
    spec = importlib.util.spec_from_file_location("export_site", ROOT / "scripts" / "export_site.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    releases = mod.changelog()
    assert releases[0]["version"] == "0.2.0" and releases[0]["items"]
