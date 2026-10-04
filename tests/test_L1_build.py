"""L1 stage 2 build: company_detail.json. Run: pytest tests/test_L1_build.py"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from valuation.L1_detail.__main__ import main as l1_main
from valuation.L1_detail.build import build_detail, run, validate_detail
from test_L1_periods import rec, year_records

ROOT = Path(__file__).resolve().parent.parent


def two_years():
    recs = year_records() + year_records(
        revenue_q=(200, 210, 220, 230), fy=2024, start="2023-10-01",
        ends=("2023-12-31", "2024-03-31", "2024-06-30", "2024-09-28"))
    for end, re in (("2023-09-30", 300), ("2024-09-28", 400)):
        recs += [rec("liabilities", None, end, 600), rec("current_assets_total", None, end, 400),
                 rec("current_liabilities_total", None, end, 250), rec("retained_earnings", None, end, re),
                 rec("cash_and_marketable_securities", None, end, 100), rec("long_term_debt", None, end, 200)]
    return {"stage": "L1.normalize", "as_of": "2026-09-30", "entity": {"ticker": "TEST"}, "records": recs}


def test_build_detail_views_and_analysis():
    d = build_detail(two_years(), "2026-09-30")
    assert validate_detail(d) == []
    assert [p["label"] for p in d["views"]["annual"]] == ["FY2023", "FY2024"]
    assert d["latest"] == {"annual": "FY2024", "ttm": "TTM 2024-09-28"}
    a23, a24 = d["analysis"]["annual"]
    assert a23["ratios"]["traditional"] == {}                 # no prior year
    # no net income in the records: NOPAT and RNOA are missing, not zero
    assert a24["reformulated_income_statement"]["nopat"] is None
    assert a24["ratios"]["reformulated"]["avg"]["rnoa"] is None
    assert a24["ratios"]["reformulated"]["avg"]["noat"] is not None
    assert a24["managerial_balance_sheet"]["fixed_assets"] == 1030 - 400
    # TTM ending at the FY24 year end uses the FY23 values as its prior
    assert d["analysis"]["ttm"][-1]["ratios"]["signals"]["gross_margin_signal"] is None
    assert d["analysis"]["ttm"][-1]["ratios"]["managerial"]["current_ratio"] == pytest.approx(400 / 250)
    assert d["statement_date"] == "2024-09-28" and d["market"] is None


def test_market_join_feeds_public_z_and_keeps_dates_apart():
    d = build_detail(two_years(), "2026-09-30",
                     raw_market={"price": 10.0, "price_date": "2026-09-29", "shares_outstanding": 50})
    assert d["market"]["market_cap"] == 500
    assert d["market"]["price_date"] != d["statement_date"]
    with pytest.raises(ValueError):
        build_detail(two_years(), "2026-09-30", raw_market={"price": 1, "price_date": "2026-10-01"})


def test_pack_overrides_classification():
    pack = {"l1": {"classification": {"marginal_tax_rate": 0.3}}}
    d = build_detail(two_years(), "2026-09-30", pack=pack)
    assert d["classification"]["marginal_tax_rate"] == 0.3


def test_as_of_mismatch_rejected():
    with pytest.raises(ValueError):
        build_detail(two_years(), "2026-06-30")


def test_run_writes_file_with_lineage_and_cli(tmp_path):
    canon = tmp_path / "canonical_statements.json"
    canon.write_text(json.dumps(two_years()))
    out = run(canon, None, "2026-09-30", tmp_path / "company_detail.json")
    doc = json.loads(out.read_text())
    assert doc["lineage"]["inputs"][0]["file"] == "canonical_statements.json"
    assert l1_main(["validate-detail", str(out)]) == 0
    assert l1_main(["build", str(canon), "--as-of", "2026-09-30", "--out", str(tmp_path / "b.json")]) == 0
    bad = tmp_path / "raw.json"
    bad.write_text(json.dumps({"facts": []}))
    with pytest.raises(ValueError):
        run(bad, None, "2026-09-30", tmp_path / "x.json")


def test_validator_flags_problems():
    d = build_detail(two_years(), "2026-09-30")
    d["views"]["annual"].reverse()
    d["schema_version"] = "9"
    errs = validate_detail(d)
    assert any("schema_version" in e for e in errs) and any("not sorted" in e for e in errs)
    assert validate_detail({}) != []


def test_core_imports_nothing_else_from_the_package():
    """_core moves to courtoy-core later, so it may import only itself (relative or valuation._core)."""
    for py in (ROOT / "src" / "valuation" / "_core").rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else \
                [node.module or ""] if isinstance(node, ast.ImportFrom) and not node.level else []
            bad = [n for n in names if n.startswith("valuation") and not n.startswith("valuation._core")]
            bad += [n for n in names if n.split(".")[0] in ("L0_ingest", "L1_detail", "L2_models", "L3_app", "runner")]
            assert not bad, f"{py.name} imports {bad}"


def test_foreign_ifrs_filer_fails_clearly():
    from valuation.L1_detail.normalize import normalize
    fact = lambda tag, val, start, end: {"taxonomy": "ifrs-full", "tag": tag, "label": tag, "description": None,  # noqa: E731
                                          "unit": "TWD", "value": val, "start": start, "end": end, "fy": 2025,
                                          "fp": "FY", "form": "20-F", "filed": "2026-04-15", "accn": "x", "frame": None}
    raw = {"facts": [fact("Revenue", 3.8e12, "2025-01-01", "2025-12-31"), fact("ProfitLoss", 1.7e12, "2025-01-01", "2025-12-31")]}
    canon = normalize(raw, "2026-09-30")
    assert canon["reporting_basis"]["taxonomy"] == "ifrs-full" and canon["reporting_basis"]["currency"] == "TWD"
    assert any("ifrs-full in TWD" in w for w in canon["warnings"])
    with pytest.raises(ValueError, match="ifrs-full in TWD"):
        build_detail(canon, "2026-09-30")


def test_trend_case_projection_is_calculated_from_history():
    from valuation.L1_detail.forecast import TERMINAL_GROWTH, trend_case
    d = build_detail(two_years(), "2026-09-30")
    p = d["projection"]
    assert p is not None and p == trend_case(d)
    assert p["case"] == "trend" and len(p["years"]) == 10
    assert p["base_period"]["kind"] == "fiscal" and p["base_period"]["fiscal_year"] == 2024
    a = p["assumptions"]
    assert -0.20 <= a["revenue_growth_start"] <= 0.40 and a["terminal_growth"] == TERMINAL_GROWTH
    revs = [d["views"]["annual"][-1]["values"]["revenue"]] + [y["revenue"] for y in p["years"]]
    growth = [b / a_ - 1 for a_, b in zip(revs, revs[1:])]
    assert growth[0] == pytest.approx(a["revenue_growth_start"])
    assert growth[-1] == pytest.approx(TERMINAL_GROWTH)
    for y in p["years"]:   # rows tie out
        assert y["gross_profit"] == pytest.approx(y["revenue"] - y["cogs"])
        assert y["ebt"] == pytest.approx(y["ebit"] - y["interest_net"])


def test_trend_case_none_without_revenue():
    from valuation.L1_detail.forecast import trend_case
    assert trend_case({"views": {"ttm": [], "annual": []}, "analysis": {}}) is None
