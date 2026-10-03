"""Sector screens: SEC frames -> per-company metrics, traits, benchmarks. Run: pytest tests/test_L1_sector.py

The fixture holds real SEC frames rows for eight filers (seven SIC 3674 chip
makers plus Apple), pulled 2026-10-03.
"""
from __future__ import annotations

import contextlib
import io
import json
from pathlib import Path

import pytest

from fakes import FakeSecClient as _FakeSecClient
from L0_ingest.sec_companyfacts import TICKERS_URL
from L0_ingest.sec_sector import FRAMES_URL, SecSectorAdapter, frame_plan, parse_sic_page, screen_year
from L1_detail.profile import classify_stage, load_rules
from L1_detail.sector import build_sector, parse_traits, quartiles
from pipeline import Paths, main, parse_sector_spec, run_sector

FIXTURES = Path(__file__).parent / "fixtures"
FX = json.loads((FIXTURES / "sec_frames_semis.json").read_text())
SEMIS = [2488, 1045810, 50863, 97476, 723125, 804328, 6281]
DEFUNCT = 1025881   # 3Dlabs: on EDGAR's SIC list, no longer files
TICKERS = [{"cik": str(t["cik_str"]).zfill(10), "ticker": t["ticker"], "name": t["title"]} for t in FX["_tickers"]]


def raw_screen():
    return {"year": 2025, "frames": {k: v for k, v in FX.items() if "/" in k and isinstance(v, list)}}


def sic_html(ciks, start=0):
    rows = "".join(f'<tr><td><a href="/cgi-bin/browse-edgar?action=getcompany&amp;CIK={str(c).zfill(10)}&amp;owner=include">'
                   f"{str(c).zfill(10)}</a></td><td>Co {c}</td></tr>" for c in ciks)
    return (f'<div class="companyInfo"><span class="companyName">SIC 3674 - SEMICONDUCTORS &amp; RELATED DEVICES</span>'
            f'</div><table class="tableFile2">{rows}</table>')


def _sec_route(url: str):
    """Frames, the ticker map, EDGAR SIC pages and two submissions files."""
    if url == TICKERS_URL:
        return json.dumps({str(i): t for i, t in enumerate(FX["_tickers"])})
    if "browse-edgar" in url:
        first = "start=0&" in url
        members = {"SIC=3674&": SEMIS + [DEFUNCT], "SIC=3571&": [320193]}
        return sic_html(next((m for k, m in members.items() if k in url and first), []))
    if "submissions/CIK0000320193" in url:
        return FIXTURES / "submissions_CIK0000320193.json"
    if "submissions/CIK0000002488" in url:
        return json.dumps({"sic": "3674", "sicDescription": "Semiconductors & Related Devices"})
    if "/frames/" in url:
        tag, period = url.split("/us-gaap/")[1].split("/USD/")
        rows = FX.get(f"{tag}/{period.removesuffix('.json')}")
        if isinstance(rows, list):
            return json.dumps({"data": [dict(zip(["cik", "entityName", "start", "end", "val"], r)) for r in rows]})
    return None


def FakeSecClient():
    return _FakeSecClient(fallback=_sec_route)


def sector_adapter():
    return SecSectorAdapter(client=FakeSecClient())


# ---------------------------------------------------------------- L1 screen

def sic_doc():
    return build_sector(raw_screen(), kind="sic", value="3674", as_of="2026-10-02", tickers=TICKERS,
                        members=[str(c).zfill(10) for c in SEMIS + [DEFUNCT]])


def test_sic_screen_keeps_filers_with_data_largest_first():
    d = sic_doc()
    assert [c["ticker"] for c in d["companies"]] == ["NVDA", "INTC", "QCOM", "MU", "AMD", "TXN", "ADI"]
    assert d["excluded"]["no_data"] == 1 and any("no 2025 or 2024 revenue" in n for n in d["notes"])
    assert d["id"] == "sic-3674" and d["year"] == 2025


def test_company_metrics_from_real_frames():
    c = {x["ticker"]: x for x in sic_doc()["companies"]}
    nv = c["NVDA"]
    assert nv["revenue"] == 215_938_000_000 and nv["revenue_growth"] == pytest.approx(215.938 / 130.497 - 1)
    assert nv["revenue_cagr"] == pytest.approx((215.938 / 26.974) ** (1 / 3) - 1) and nv["cagr_years"] == 3
    assert nv["capex"] == 6_042_000_000            # "productive assets" fallback tag
    assert nv["ebitda"] == 130_387_000_000 + 2_843_000_000
    # AMD: short-term borrowings equal the current portion of LTD -> counted once
    assert c["AMD"]["debt"] == 2_348_000_000 + 874_000_000
    # AMD reports no combined D&A tag -> depreciation + intangible amortization
    assert c["AMD"]["ebitda"] == 3_694_000_000 + 521_000_000 + 2_300_000_000
    assert "depreciation + amortization" in c["AMD"]["ebitda_basis"]
    # Intel: no total-liabilities tag -> assets - equity
    assert c["INTC"]["liabilities"] == 211_429_000_000 - 114_281_000_000


def test_traits_use_the_profile_rules():
    t = {x["ticker"]: x["traits"] for x in sic_doc()["companies"]}
    assert t["NVDA"] == {"stage": "high growth", "predictability": "high", "asset_intensity": "light",
                         "capital_structure": "low leverage"}
    assert t["INTC"]["stage"] == "declining"        # shrinking and loss-making: declining, not "high growth"
    assert t["MU"]["asset_intensity"] == "heavy"


def test_benchmarks_are_quartiles_across_the_sector():
    d = sic_doc()
    oms = sorted(c["operating_margin"] for c in d["companies"])
    b = d["benchmarks"]["operating_margin"]
    assert b["n"] == 7 and b["median"] == pytest.approx(oms[3])
    assert b["q1"] <= b["median"] <= b["q3"]
    assert quartiles([]) == {"q1": None, "median": None, "q3": None, "n": 0}


def test_trait_screen_filters_across_industries():
    d = build_sector(raw_screen(), kind="traits", value="asset_intensity=light;predictability=high",
                     as_of="2026-10-02", tickers=TICKERS)
    assert {c["ticker"] for c in d["companies"]} == {"NVDA", "QCOM"}
    assert d["id"] == "traits-asset-intensity-light-predictability-high"
    with pytest.raises(ValueError):
        parse_traits("colour=blue")


def test_late_filer_falls_back_a_year_and_is_flagged():
    raw = raw_screen()
    for k in list(raw["frames"]):
        if k.endswith("/CY2025") or k.endswith("CY2025Q4I"):
            raw["frames"][k] = [r for r in raw["frames"][k] if r[0] != 97476]
    d = build_sector(raw, kind="sic", value="3674", as_of="2026-10-02", tickers=TICKERS,
                     members=[str(c).zfill(10) for c in SEMIS])
    txn = next(c for c in d["companies"] if c["ticker"] == "TXN")
    assert txn["stale"] and txn["calendar_year"] == 2024 and txn["revenue"] == 15_641_000_000
    assert any("haven't reported 2025" in n for n in d["notes"])


def test_limit_keeps_largest():
    d = build_sector(raw_screen(), kind="sic", value="3674", as_of="2026-10-02", tickers=TICKERS,
                     members=[str(c).zfill(10) for c in SEMIS], limit=3)
    assert [c["ticker"] for c in d["companies"]] == ["NVDA", "INTC", "QCOM"] and d["excluded"]["over_limit"] == 4


def test_stage_rule_declining_before_losses():
    r = load_rules()
    assert classify_stage(-0.05, -0.04, r)[0] == "declining"
    assert classify_stage(0.30, -0.10, r)[0] == "high growth"


# ---------------------------------------------------------------- L0 adapter

def test_frame_plan_and_year():
    assert screen_year("2026-10-02") == 2025 and screen_year("2026-02-15") == 2024
    plan = frame_plan(2025)
    assert ("Assets", "CY2025Q4I") in plan and ("Revenues", "CY2022") in plan and len(plan) == len(set(plan))


def test_missing_frame_is_recorded_not_guessed():
    ad = sector_adapter()
    assert ad.frame("SalesRevenueNet", "CY2025") is None
    raw = ad.fetch_frames(2025)
    assert "SalesRevenueNet/CY2025" in raw["missing_frames"]
    assert raw["frames"]["Assets/CY2025Q4I"][0][0] == 2488
    assert raw["tags"]["capex"][1] == "PaymentsToAcquireProductiveAssets"


def test_sic_pages():
    ciks, desc = parse_sic_page(sic_html([2488, 6281]))
    assert ciks == ["0000002488", "0000006281"] and desc.startswith("SEMICONDUCTORS")
    lst = sector_adapter().sic_members("3674")
    assert len(lst["ciks"]) == 8 and lst["sic"] == "3674"
    with pytest.raises(ValueError):
        sector_adapter().sic_members("36")


# ---------------------------------------------------------------- pipeline

def test_parse_sector_spec():
    assert parse_sector_spec("sic:3674") == ("sic", "3674")
    assert parse_sector_spec("traits:stage=high growth") == ("traits", "stage=high growth")
    for bad in ("sic:36", "region:us", "list:../etc", "sic:"):
        with pytest.raises(ValueError):
            parse_sector_spec(bad)


def test_run_sector_sic_of_screens_the_whole_sector(tmp_path):
    paths = Paths(tmp_path / "data", tmp_path / "assumptions")
    clients = []

    def fac():
        c = FakeSecClient()
        clients.append(c)
        return SecSectorAdapter(client=c)

    out = run_sector("sic-of:AAPL", "2026-10-02", paths, fac)
    doc = json.loads(out.read_text())
    assert out == paths.sector("sector-technology", "2026-10-02")
    assert doc["kind"] == "sector" and doc["label"] == "Technology"
    assert doc["notes"][0].startswith("AAPL files under SIC 3571") and "Technology › Hardware & Equipment › Hardware & Peripherals" in doc["notes"][0]
    tick = {c["ticker"]: c for c in doc["companies"]}
    assert set(tick) == {"AAPL", "NVDA", "INTC", "QCOM", "MU", "AMD", "TXN", "ADI"}
    assert tick["AAPL"]["classification"] == {"sector": "technology", "group": "hardware_equipment", "industry": "hardware_peripherals"}
    assert tick["NVDA"]["classification"]["industry"] == "semiconductors" and tick["NVDA"]["sic"] == "3674"
    assert doc["levels"]["industries"]["semiconductors"]["count"] == 7 and doc["levels"]["groups"]["semiconductors"]["name"] == "Semiconductors"
    assert paths.sic_list("2026-10-02", "3674").exists() and doc["lineage"]["inputs"]
    run_sector("sic:3674", "2026-10-02", paths, fac)          # second run reads the saved raw screen
    assert not any("/frames/" in u for u in clients[1].calls)


def test_sector_spec_checks_taxonomy():
    assert parse_sector_spec("sector:technology") == ("sector", "technology")
    with pytest.raises(ValueError, match="unknown sector"):
        parse_sector_spec("sector:crypto")


def test_run_sector_list(tmp_path):
    lists = tmp_path / "sectors"
    lists.mkdir()
    (lists / "my_chips.json").write_text(json.dumps({"label": "My chips", "tickers": ["amd", "NVDA", "ZZZZ"]}))
    paths = Paths(tmp_path / "data", tmp_path / "assumptions")
    doc = json.loads(run_sector("list:my_chips", "2026-10-02", paths, sector_adapter, lists).read_text())
    assert doc["id"] == "list-my-chips" and doc["label"] == "My chips"
    assert [c["ticker"] for c in doc["companies"]] == ["NVDA", "AMD"]
    assert "not in the SEC ticker list: ZZZZ" in doc["notes"][0]
    with pytest.raises(FileNotFoundError):
        run_sector("list:nope", "2026-10-02", paths, sector_adapter, lists)


def test_cli_sector(tmp_path):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["sector", "traits:stage=high growth", "--as-of", "2026-10-02", "--data-dir", str(tmp_path / "d")],
                  adapter_factory=sector_adapter)
    assert rc == 0 and "High growth: 1 companies" in buf.getvalue()
    assert main(["sector", "sic:12", "--data-dir", str(tmp_path / "d")], adapter_factory=sector_adapter) == 2


def test_taxonomy_covers_every_sec_code_once():
    from L1_detail.taxonomy import load
    tax = load()
    codes = {c[0] for c in json.loads((Path(__file__).parent.parent / "inputs" / "sectors" / "sic_codes.json").read_text())["codes"]}
    assert codes - set(tax.by_sic) == tax.excluded            # all mapped except the non-operating codes
    assert set(tax.by_sic) <= codes                            # nothing invented
    assert tax.classify("7370")["sector"] == "communication_services"   # GICS: interactive media
    assert tax.classify(3571)["industry"] == "hardware_peripherals" and tax.classify("9995") is None
