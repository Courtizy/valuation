"""L1 stage 1 normalizer tests (offline). Run: pytest tests/test_L1_normalize.py"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from L1_detail.normalize import apply_pack, normalize, run
from L1_detail.registry import load_registry
from L1_detail.schema import validate_canonical
from lineage import sha256_file

FY23 = ("2022-10-01", "2023-09-30")
FY22 = ("2021-10-01", "2022-09-30")
Q1 = ("2022-10-01", "2022-12-31")
END23 = (None, "2023-09-30")
K23 = ("0000000001-23-000010", "2023-11-01", "10-K", 2023, "FY")
K24 = ("0000000001-24-000010", "2024-11-01", "10-K", 2024, "FY")
Q124 = ("0000000001-23-000020", "2023-02-01", "10-Q", 2023, "Q1")


def fact(tag, period, value, filing, unit="USD", taxonomy="us-gaap"):
    accn, filed, form, fy, fp = filing
    return {"taxonomy": taxonomy, "tag": tag, "label": None, "description": None, "unit": unit,
            "value": value, "start": period[0], "end": period[1], "fy": fy, "fp": fp,
            "form": form, "filed": filed, "accn": accn, "frame": None}


def raw(*facts):
    return {"schema_version": "0.2.0", "source": "sec_companyfacts", "source_url": "x",
            "retrieved_at": "2026-10-01T00:00:00+00:00", "from_cache": False, "content_sha256": "0" * 64,
            "entity": {"cik": "0000000001", "name": "TestCo", "ticker": "TST"}, "facts": list(facts)}


def recs(doc, concept):
    return {(r["start"], r["end"]): r for r in doc["records"] if r["concept"] == concept}


@pytest.fixture(scope="module")
def reg():
    return load_registry()


# --- picking a value -----------------------------------------------------

def test_priority_tag_wins_and_fallback_fills_gaps(reg):
    doc = normalize(raw(
        fact("RevenueFromContractWithCustomerExcludingAssessedTax", FY23, 100, K23),
        fact("Revenues", FY23, 999, K23),          # lower priority, same period: ignored
        fact("Revenues", FY22, 90, K23),           # only tag for FY22: used
    ), "2026-09-30", reg)
    r = recs(doc, "revenue")
    assert r[FY23]["value"] == 100
    assert r[FY23]["source"]["tags"] == ["us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"]
    assert r[FY22]["value"] == 90


def test_instant_and_duration_are_not_mixed(reg):
    doc = normalize(raw(
        fact("Assets", FY23, 5, K23),              # duration fact for an instant concept: ignored
        fact("Revenues", END23, 7, K23),           # instant fact for a duration concept: ignored
    ), "2026-09-30", reg)
    assert recs(doc, "assets") == {} and recs(doc, "revenue") == {}


def test_months_computed(reg):
    doc = normalize(raw(fact("Revenues", FY23, 100, K23), fact("Revenues", Q1, 25, Q124)), "2026-09-30", reg)
    r = recs(doc, "revenue")
    assert r[FY23]["months"] == 12 and r[Q1]["months"] == 3


def test_wrong_unit_warns(reg):
    doc = normalize(raw(fact("Revenues", FY23, 100, K23, unit="EUR")), "2026-09-30", reg)
    assert recs(doc, "revenue") == {}
    assert any("revenue" in w and "EUR" in w for w in doc["warnings"])


# --- restatements and point-in-time --------------------------------------

def test_restatement_tracked(reg):
    doc = normalize(raw(fact("Revenues", FY23, 100, K23), fact("Revenues", FY23, 104, K24)), "2026-09-30", reg)
    r = recs(doc, "revenue")[FY23]
    assert (r["value"], r["value_as_filed"], r["restated"]) == (104, 100, True)
    assert r["source"]["accn"] == K24[0]
    # fiscal labels come from the period's own (earliest) filing, not the later 10-K
    assert (r["fiscal_year"], r["fiscal_period"]) == (2023, "FY")


def test_as_filed_spans_tag_changes(reg):
    # Company switched tags; the later filing re-reports FY23 under the new tag.
    doc = normalize(raw(
        fact("SalesRevenueNet", FY23, 100, K23),
        fact("RevenueFromContractWithCustomerExcludingAssessedTax", FY23, 101, K24),
    ), "2026-09-30", reg)
    r = recs(doc, "revenue")[FY23]
    assert r["value"] == 101 and r["value_as_filed"] == 100


def test_point_in_time_hides_later_filings(reg):
    facts = (fact("Revenues", FY23, 100, K23), fact("Revenues", FY23, 104, K24))
    early = normalize(raw(*facts), "2024-01-31", reg)
    r = recs(early, "revenue")[FY23]
    assert (r["value"], r["restated"]) == (100, False)
    assert early["facts_excluded_after_as_of"] == 1
    assert normalize(raw(*facts), "2023-10-15", reg)["records"] == []


def test_conflicting_values_in_one_filing_warn(reg):
    doc = normalize(raw(fact("Revenues", FY23, 100, K23), fact("Revenues", FY23, 101, K23)), "2026-09-30", reg)
    assert any("conflicting values" in w for w in doc["warnings"])


# --- sum rule --------------------------------------------------------------

def test_short_term_debt_sums_components(reg):
    doc = normalize(raw(
        fact("CommercialPaper", END23, 6, K23),
        fact("LongTermDebtCurrent", END23, 10, K23),
    ), "2026-09-30", reg)
    r = recs(doc, "short_term_debt")[END23]
    assert r["value"] == 16 and r["method"] == "summed"
    assert r["components_missing"] == 0
    assert {c["tag"] for c in r["components"]} == {"us-gaap:CommercialPaper", "us-gaap:LongTermDebtCurrent"}


def test_total_tag_beats_components(reg):
    doc = normalize(raw(
        fact("DebtCurrent", END23, 15, K23),
        fact("LongTermDebtCurrent", END23, 10, K23),
    ), "2026-09-30", reg)
    r = recs(doc, "short_term_debt")[END23]
    assert r["value"] == 15 and r["method"] == "reported"


def test_component_alternatives_are_priority_picked(reg):
    # ShortTermBorrowings and CommercialPaper are alternatives in one component: no double count.
    doc = normalize(raw(
        fact("ShortTermBorrowings", END23, 6, K23),
        fact("CommercialPaper", END23, 6, K23),
        fact("LongTermDebtCurrent", END23, 10, K23),
    ), "2026-09-30", reg)
    assert recs(doc, "short_term_debt")[END23]["value"] == 16


def test_cash_includes_marketable_securities_and_records_gaps(reg):
    doc = normalize(raw(
        fact("CashAndCashEquivalentsAtCarryingValue", END23, 30, K23),
        fact("MarketableSecuritiesCurrent", END23, 31, K23),
        fact("CashAndCashEquivalentsAtCarryingValue", (None, "2022-09-30"), 20, K23),
    ), "2026-09-30", reg)
    r = recs(doc, "cash_and_marketable_securities")
    assert r[END23]["value"] == 61
    assert r[(None, "2022-09-30")]["value"] == 20
    assert r[(None, "2022-09-30")]["components_missing"] == 1


# --- derived ---------------------------------------------------------------

def test_derived_chain_and_missing_inputs(reg):
    doc = normalize(raw(
        fact("DebtCurrent", END23, 15, K23),
        fact("LongTermDebtNoncurrent", END23, 85, K23),
        fact("CashAndCashEquivalentsAtCarryingValue", END23, 30, K23),
        fact("OperatingIncomeLoss", FY23, 50, K23),
        fact("DepreciationDepletionAndAmortization", FY23, 10, K23),
        fact("NetCashProvidedByUsedInOperatingActivities", FY23, 45, K23),
    ), "2026-09-30", reg)
    assert recs(doc, "total_debt")[END23]["value"] == 100
    assert recs(doc, "net_debt")[END23]["value"] == 70        # derived from a derived
    assert recs(doc, "ebitda")[FY23]["value"] == 60
    assert recs(doc, "ebitda")[FY23]["method"] == "derived"
    assert recs(doc, "free_cash_flow") == {}                  # capex missing -> no record


def test_derived_ratio_and_divide_by_zero(reg):
    doc = normalize(raw(
        fact("IncomeTaxExpenseBenefit", FY23, 21, K23),
        fact("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", FY23, 100, K23),
        fact("IncomeTaxExpenseBenefit", FY22, 5, K23),
        fact("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest", FY22, 0, K23),
    ), "2026-09-30", reg)
    r = recs(doc, "effective_tax_rate")
    assert r[FY23]["value"] == pytest.approx(0.21) and r[FY23]["unit"] == "pure"
    assert FY22 not in r


# --- checks, coverage, schema, packs -----------------------------------------

def test_identity_checks(reg):
    doc = normalize(raw(
        fact("Assets", END23, 100, K23), fact("LiabilitiesAndStockholdersEquity", END23, 100, K23),
        fact("Revenues", FY23, 100, K23), fact("CostOfRevenue", FY23, 60, K23),
        fact("GrossProfit", FY23, 45, K23),   # should be 40
    ), "2026-09-30", reg)
    checks = {c["name"]: c for c in doc["checks"]}
    assert checks["balance_sheet_balances"]["evaluated"] == 1 and not checks["balance_sheet_balances"]["failed"]
    assert checks["gross_profit_ties"]["failed"][0]["left"] == 45
    assert checks["net_income_split_ties"]["evaluated"] == 0


def test_output_validates_and_reports_coverage(reg):
    doc = normalize(raw(fact("Revenues", FY23, 100, K23)), "2026-09-30", reg)
    assert validate_canonical(doc) == []
    assert doc["coverage"]["concepts_with_data"] == 1
    assert "net_income" in doc["coverage"]["missing"]


def test_validator_catches_problems(reg):
    doc = normalize(raw(fact("Revenues", FY23, 100, K23)), "2026-09-30", reg)
    doc["records"].append(dict(doc["records"][0]))
    doc["records"][0]["value"] = "lots"
    errors = validate_canonical(doc)
    assert any("value missing or not numeric" in e for e in errors)
    assert any("duplicate" in e for e in errors)


def test_pack_override(reg):
    pack = {"l1": {"tag_overrides": {"revenue": ["us-gaap:InterestAndDividendIncomeOperating"]}}}
    doc = normalize(raw(fact("InterestAndDividendIncomeOperating", FY23, 70, K23),
                        fact("Revenues", FY23, 999, K23)), "2026-09-30", apply_pack(reg, pack))
    assert recs(doc, "revenue")[FY23]["value"] == 70
    with pytest.raises(KeyError):
        apply_pack(reg, {"l1": {"tag_overrides": {"nope": []}}})


def test_bad_as_of_rejected(reg):
    with pytest.raises(ValueError):
        normalize(raw(), "30/09/2026", reg)


def test_run_writes_file_with_lineage(tmp_path):
    src = tmp_path / "raw_filing.json"
    src.write_text(json.dumps(raw(fact("Revenues", FY23, 100, K23))))
    out = run(src, "2026-09-30", tmp_path / "out" / "canonical_statements.json")
    doc = json.loads(out.read_text())
    assert doc["lineage"]["inputs"] == [{"file": "raw_filing.json", "sha256": sha256_file(src)}]
    assert validate_canonical(doc) == []


def test_run_rejects_non_raw_file(tmp_path):
    p = tmp_path / "x.json"
    p.write_text("{}")
    with pytest.raises(ValueError):
        run(p, "2026-09-30", tmp_path / "o.json")
