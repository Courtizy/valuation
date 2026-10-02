"""Registry integrity tests. Run: pytest tests/test_L1_registry.py"""
from __future__ import annotations

import json

import pytest

from L1_detail.registry import DEFAULT_PATH, load_registry, validate_registry

EDGARTOOLS_SPOT_CHECK = [
    "CashAndMarketableSecurities", "Assets", "LiabilitiesAndEquity", "Revenue",
    "OperatingIncomeLoss", "NetIncome", "CapitalExpenses", "SharesFullyDilutedAverage",
    "OngoingOperatingProvisions(WarrantiesEtc)", "EquityExpenseIncome(BuybackIssued)",
    "ForecastedIntangibleAmortizationAfterYear5",
]


@pytest.fixture(scope="module")
def reg():
    return load_registry()


def test_registry_is_valid(reg):
    assert validate_registry(reg) == []


def test_has_all_95_edgartools_concepts(reg):
    reported = reg.of_kind("reported")
    assert len(reported) == 95
    names = {c.edgartools_concept for c in reported}
    assert len(names) == 95
    for n in EDGARTOOLS_SPOT_CHECK:
        assert n in names


def test_valuation_additions_present(reg):
    for cid in ["operating_cash_flow", "share_based_compensation", "depreciation_amortization_cf",
                "change_in_working_capital", "ebitda", "free_cash_flow", "net_debt"]:
        assert cid in reg.concepts


def test_parenthesised_names_become_snake_case(reg):
    assert reg["ongoing_operating_provisions_warranties_etc"].edgartools_concept == \
        "OngoingOperatingProvisions(WarrantiesEtc)"


def test_tag_priority_order(reg):
    idx = reg.tag_index()
    assert idx["us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"] == [("revenue", 0)]
    assert idx["us-gaap:Revenues"] == [("revenue", 1)]
    assert idx["dei:EntityCommonStockSharesOutstanding"] == [("shares_year_end", 1)]


def test_derived_inputs_resolve(reg):
    assert reg["net_debt"].formula_inputs() == ["total_debt", "cash_and_marketable_securities"]


def test_unmapped_list_is_reported(reg):
    gaps = reg.unmapped()
    assert "short_term_debt" not in gaps  # mapped via sum rule since registry 0.2.0
    assert "revenue" not in gaps
    assert "other_operating_expense" in gaps  # presentation-mode only


def _broken(tmp_path, mutate):
    doc = json.loads(DEFAULT_PATH.read_text())
    mutate(doc["concepts"])
    p = tmp_path / "concepts.json"
    p.write_text(json.dumps(doc))
    return validate_registry(load_registry(p))


def test_validator_catches_double_claimed_tag(tmp_path):
    def m(cs):
        next(c for c in cs if c["id"] == "gross_profit")["primary_tags"].append("us-gaap:Revenues")
    assert any("claimed by multiple" in e for e in _broken(tmp_path, m))


def test_validator_catches_bad_formula_ref(tmp_path):
    def m(cs):
        next(c for c in cs if c["id"] == "ebitda")["formula"] = "operating_income_loss + nope"
    assert any("unknown 'nope'" in e for e in _broken(tmp_path, m))


def test_validator_catches_wrong_period_type(tmp_path):
    def m(cs):
        next(c for c in cs if c["id"] == "assets")["period_type"] = "duration"
    assert any("must be instant" in e for e in _broken(tmp_path, m))


def test_duplicate_id_rejected(tmp_path):
    doc = json.loads(DEFAULT_PATH.read_text())
    doc["concepts"].append(doc["concepts"][0])
    p = tmp_path / "concepts.json"
    p.write_text(json.dumps(doc))
    with pytest.raises(ValueError):
        load_registry(p)


def test_sum_concepts_have_components(reg):
    for cid in ("short_term_debt", "cash_and_marketable_securities"):
        c = reg[cid]
        assert c.aggregation == "sum" and c.components


def test_validator_rejects_components_without_sum(tmp_path):
    def m(cs):
        next(c for c in cs if c["id"] == "revenue")["components"] = [["us-gaap:Foo"]]
    assert any("components only allowed" in e for e in _broken(tmp_path, m))


def test_derived_order_puts_inputs_first(reg):
    order = [c.id for c in reg.derived_order()]
    assert order.index("total_debt") < order.index("net_debt")
