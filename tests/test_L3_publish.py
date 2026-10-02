"""L3: publishing pipeline outputs to the static site. Run: pytest tests/test_L3_publish.py"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from L1_detail.build import validate_detail
from L3_app.demo import write_demo
from L3_app.publish import publish
from pipeline import Paths, plan

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
    assert sorted(out["copied"]) == ["ABC/2026-09-30/company_detail.json", "ABC/2026-09-30/model_results/dcf.json"]
    index = json.loads((site / "data" / "index.json").read_text())
    (c,) = index["companies"]
    assert c["ticker"] == "ABC" and c["name"] == "ABC Inc." and not c["demo"]
    assert c["runs"][0] == {"as_of": "2026-09-30", "detail": "ABC/2026-09-30/company_detail.json",
                            "comparison": None, "models": ["dcf"], "latest": {"ttm": "x"}}
    # earlier runs already in site/data stay listed
    publish(tmp_path / "empty", site)
    assert json.loads((site / "data" / "index.json").read_text())["companies"][0]["ticker"] == "ABC"


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
