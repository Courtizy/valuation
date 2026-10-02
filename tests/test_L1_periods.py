"""L1 stage 2 frequency views. Run: pytest tests/test_L1_periods.py"""
from __future__ import annotations

import pytest

from L1_detail.periods import build_views, calendar_label
from L1_detail.registry import load_registry


@pytest.fixture
def reg():
    return load_registry()


def rec(concept, start, end, value, months=None, fy=2023, fp="FY", restated=False):
    from L1_detail.normalize import _months
    return {"concept": concept, "start": start, "end": end, "value": value,
            "months": _months(start, end) if start else None, "fiscal_year": fy, "fiscal_period": fp,
            "restated": restated, "method": "reported", "value_as_filed": value,
            "statement": "", "period_type": "duration" if start else "instant", "unit": "USD", "source": {}}


# FY2023 runs 2022-10-01 .. 2023-09-30 with quarter ends 12-31, 03-31, 06-30.
FY_S, Q1E, Q2E, Q3E, FY_E = "2022-10-01", "2022-12-31", "2023-03-31", "2023-06-30", "2023-09-30"


def year_records(revenue_q=(100, 110, 120, 130), cfo_q=(10, 20, 30, 40), opinc_q=(20, 22, 24, 26),
                 da_q=(5, 5, 5, 5), fy=2023, start=FY_S, ends=(Q1E, Q2E, Q3E, FY_E)):
    """Typical filing pattern: IS reported per quarter (Q1-Q3) and FY; CF reported YTD only."""
    r = []
    q_starts = [start] + [_nd(e) for e in ends[:3]]
    for i in range(3):  # 10-Q income statement: own quarter
        r.append(rec("revenue", q_starts[i], ends[i], revenue_q[i], fy=fy, fp=f"Q{i+1}"))
        r.append(rec("operating_income_loss", q_starts[i], ends[i], opinc_q[i], fy=fy, fp=f"Q{i+1}"))
        r.append(rec("depreciation_amortization_cf", start, ends[i], sum(da_q[:i + 1]), fy=fy))
        r.append(rec("operating_cash_flow", start, ends[i], sum(cfo_q[:i + 1]), fy=fy))
    for i in (1, 2):  # 10-Q also has IS YTD columns
        r.append(rec("revenue", start, ends[i], sum(revenue_q[:i + 1]), fy=fy))
        r.append(rec("operating_income_loss", start, ends[i], sum(opinc_q[:i + 1]), fy=fy))
    r += [rec("revenue", start, ends[3], sum(revenue_q), fy=fy),
          rec("operating_income_loss", start, ends[3], sum(opinc_q), fy=fy),
          rec("depreciation_amortization_cf", start, ends[3], sum(da_q), fy=fy),
          rec("operating_cash_flow", start, ends[3], sum(cfo_q), fy=fy)]
    for i, e in enumerate(ends):
        r.append(rec("assets", None, e, 1000 + 10 * i, fy=fy))
    return r


def _nd(s):
    from datetime import date, timedelta
    return (date.fromisoformat(s) + timedelta(days=1)).isoformat()


def test_annual_view(reg):
    v = build_views(year_records(), reg)
    (fy,) = v["annual"]
    assert fy["label"] == "FY2023" and fy["start"] == FY_S and fy["end"] == FY_E
    assert fy["values"]["revenue"] == 460
    assert fy["values"]["assets"] == 1030          # instant at year end
    assert fy["values"]["ebitda"] == 92 + 20        # recomputed derived


def test_quarters_reported_and_derived(reg):
    q = build_views(year_records(), reg)["quarterly"]
    assert [p["fiscal_period"] for p in q] == ["Q1", "Q2", "Q3", "Q4"]
    assert [p["values"]["revenue"] for p in q] == [100, 110, 120, 130]
    assert [p["methods"]["revenue"] for p in q] == ["reported"] * 3 + ["q4_derived"]
    # cash flow only reported YTD: Q2 and Q3 come from YTD differences
    assert [p["values"]["operating_cash_flow"] for p in q] == [10, 20, 30, 40]
    assert [p["methods"]["operating_cash_flow"] for p in q] == \
        ["reported", "ytd_derived", "ytd_derived", "q4_derived"]
    assert [p["values"]["assets"] for p in q] == [1000, 1010, 1020, 1030]
    assert q[3]["values"]["ebitda"] == 26 + 5


def test_instant_never_summed_in_ttm(reg):
    recs = year_records() + year_records(
        revenue_q=(200, 210, 220, 230), fy=2024, start="2023-10-01",
        ends=("2023-12-31", "2024-03-31", "2024-06-30", "2024-09-28"))
    v = build_views(recs, reg)
    ttm = v["ttm"]
    assert len(ttm) == 5                            # quarter 4 of FY23 .. quarter 4 of FY24
    first, last = ttm[0], ttm[-1]
    assert first["values"]["revenue"] == 460
    assert last["values"]["revenue"] == 860
    assert ttm[1]["values"]["revenue"] == 110 + 120 + 130 + 200
    assert last["values"]["assets"] == 1030          # FY24 year-end instant, not a sum
    assert last["methods"]["revenue"] == "summed_4q_with_derived"


def test_year_in_progress_has_quarters_but_no_annual(reg):
    recs = year_records() + [
        rec("revenue", "2023-10-01", "2023-12-31", 300, fy=2024, fp="Q1"),
        rec("operating_cash_flow", "2023-10-01", "2023-12-31", 50, fy=2024, fp="Q1")]
    v = build_views(recs, reg)
    assert [p["label"] for p in v["annual"]] == ["FY2023"]
    assert v["quarterly"][-1]["label"] == "FY2024 Q1"
    assert v["ttm"][-1]["values"]["revenue"] == 110 + 120 + 130 + 300


def test_gap_breaks_ttm(reg):
    # missing FY figure means no Q4 for revenue; TTM needs all four quarters
    recs = [r for r in year_records() if not (r["concept"] == "revenue" and r["months"] == 12)]
    v = build_views(recs, reg)
    assert "revenue" not in v["quarterly"][3]["values"]
    assert all("revenue" not in p["values"] for p in v["ttm"])


def test_ratio_concepts_not_differenced(reg):
    recs = year_records() + [rec("eps_basic", FY_S, FY_E, 4.0), rec("eps_basic", FY_S, Q3E, 3.0)]
    for r in recs:
        if r["concept"] == "eps_basic":
            r["unit"] = "USD/shares"
    q = build_views(recs, reg)["quarterly"]
    assert "eps_basic" not in q[3]["values"]


def test_restated_flag_carried(reg):
    recs = year_records()
    for r in recs:
        if r["concept"] == "revenue" and r["months"] == 12:
            r["restated"] = True
    fy = build_views(recs, reg)["annual"][0]
    assert "revenue" in fy["restated"]


def test_calendar_label_shifts_early_month_ends():
    assert calendar_label("2023-09-30") == (2023, 3)
    assert calendar_label("2024-01-02") == (2023, 4)   # 52/53-week year ending in early Jan
