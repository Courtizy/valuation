from pathlib import Path

import pytest

from valuation._core.cost_of_capital import discount_rates, relever_beta
from valuation.L0_ingest.damodaran import parse_betas, parse_erp
from valuation.L1_detail.taxonomy import load

FIXTURES = Path(__file__).parent / "fixtures"


def betas():
    return parse_betas((FIXTURES / "damodaran_betas.html").read_text())


def test_parse_betas_by_column_name():
    doc = betas()
    assert doc["updated"] == "January 2026"
    soft = doc["industries"]["Beverage (Soft)"]            # double space in the source collapsed
    assert soft["firms"] == 27 and soft["beta"] == 0.64
    assert soft["debt_to_equity"] == pytest.approx(0.2059)
    assert soft["beta_unlevered"] == 0.56 and soft["beta_unlevered_cash_corrected"] == 0.58
    assert "Total Market" in doc["industries"]


def test_parse_erp_takes_latest_year():
    erp = parse_erp((FIXTURES / "damodaran_erp.html").read_text())
    assert erp["year"] == 2025 and erp["value"] == pytest.approx(0.0423) and erp["tbond_rate"] == pytest.approx(0.0418)


def test_parse_rejects_a_page_without_the_table():
    with pytest.raises(ValueError):
        parse_betas("<html><table><tr><td>nothing</td></tr></table></html>")


def test_industry_beta_maps_sic_to_damodaran_row():
    tax = load()
    ko = tax.industry_beta("2086", {"betas": betas()})       # soft drinks -> Beverages -> Beverage (Soft)
    assert ko["unlevered"] and ko["value"] == 0.58 and ko["industry"] == "Beverage (Soft)"
    assert "Damodaran" in ko["basis"] and "January 2026" in ko["basis"]
    other = tax.industry_beta("3711", {"betas": betas()})    # Auto & Truck isn't in the fixture -> market row
    assert other["industry"] == "Total Market" and other["value"] == 0.76
    assert tax.industry_beta("2086", None) == tax.typical_beta("2086")   # no data -> illustrative fallback


def test_discount_rates_accept_an_unlevered_beta():
    kw = dict(risk_free=0.04, pre_tax_cost_of_debt=0.05, equity_risk_premium=0.0423, tax_rate=0.21,
              current_debt_to_equity=0.3)
    via_u = discount_rates(beta=None, beta_unlevered=0.58, **kw)
    via_levered = discount_rates(beta=relever_beta(0.58, 0.3, 0.21), **kw)
    assert via_u["beta_unlevered"] == pytest.approx(0.58)
    assert via_u["wacc"] == pytest.approx(via_levered["wacc"])
    with pytest.raises(ValueError):
        discount_rates(beta=None, **kw)
