"""Synthetic demo company for previewing the site. Not real data.

  python -m L3_app.demo --site-dir site

Writes site/data/DEMO/{as_of}/company_detail.json (built by the real L1 build
from synthetic canonical records, in the usual 10-Q/10-K pattern: income
statement by quarter and full year, cash flow year-to-date only) plus a real DCF run on made-up
market inputs and two synthetic model results and their comparison, so every tab has something to
show before the first real pipeline run. Every file is flagged demo: true.
"""
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

from L1_detail.build import build_detail
from L1_detail.normalize import _months
from L2_models.reconcile import build_comparison

AS_OF = "2026-09-30"
SEASON = (0.23, 0.24, 0.25, 0.28)


def _rec(concept, start, end, value, fy, fp):
    return {"concept": concept, "start": start, "end": end, "value": round(value, 2),
            "months": _months(start, end) if start else None, "fiscal_year": fy, "fiscal_period": fp,
            "restated": False, "method": "reported", "value_as_filed": round(value, 2),
            "statement": "", "period_type": "duration" if start else "instant", "unit": "USD", "source": {}}


def _nd(s):
    return (date.fromisoformat(s) + timedelta(days=1)).isoformat()


SPECS = {
    # ticker: name, first-year revenue, growth, margins (share of revenue), balance sheet scale
    "DEMO": dict(name="Demo Manufacturing Co. (synthetic)", rev0=4.0e9, growth=0.08, cogs=0.58, sga=0.18,
                 rnd=0.06, da=0.04, capex=0.05, wc=0.02, nca=0.55, ltd=0.9e9, std=0.15e9, noise=0.0),
    "DEMOG": dict(name="Demo Cloud Software (synthetic)", rev0=0.8e9, growth=0.32, cogs=0.30, sga=0.45,
                  rnd=0.22, da=0.02, capex=0.02, wc=-0.03, nca=0.25, ltd=0.0, std=0.0, noise=0.06),
    "DEMOU": dict(name="Demo Regional Utility (synthetic)", rev0=6.0e9, growth=0.02, cogs=0.52, sga=0.10,
                  rnd=0.0, da=0.10, capex=0.17, wc=0.01, nca=3.0, ltd=14e9, std=1.0e9, noise=0.01),
}


def synthetic_records(spec: dict | None = None) -> list[dict]:
    sp = spec or SPECS["DEMO"]
    recs = []
    revenue_fy = sp["rev0"]
    opm = 1 - sp["cogs"] - sp["sga"] - sp["rnd"]
    for k, fy in enumerate(range(2021, 2027)):
        start = f"{fy - 1}-10-01"
        ends = [f"{fy - 1}-12-31", f"{fy}-03-31", f"{fy}-06-30", f"{fy}-09-30"]
        n_q = 3 if fy == 2026 else 4                     # FY2026 10-K not filed by as_of
        rev_q = [revenue_fy * s for s in SEASON]
        wobble = sp["noise"] * (1 if k % 2 else -1)     # makes cash flow less predictable
        interest = sp["ltd"] * 0.05 / 4
        flows = {
            "revenue": rev_q,
            "cost_of_goods_and_services_sold": [r * sp["cogs"] for r in rev_q],
            "selling_general_and_admin_expenses": [r * sp["sga"] for r in rev_q],
            "research_and_development_expenses": [r * sp["rnd"] for r in rev_q],
            "interest_expense": [interest + 1e6] * 4, "interest_income": [1e6] * 4,
        }
        flows["gross_profit"] = [r - c for r, c in zip(rev_q, flows["cost_of_goods_and_services_sold"])]
        flows["operating_income_loss"] = [r * opm for r in rev_q]
        flows["pretax_income_loss"] = [o - interest for o in flows["operating_income_loss"]]
        flows["income_taxes"] = [max(p, 0) * 0.21 for p in flows["pretax_income_loss"]]
        flows["net_income"] = [p - t for p, t in zip(flows["pretax_income_loss"], flows["income_taxes"])]
        cf = {
            "depreciation_amortization_cf": [r * sp["da"] for r in rev_q],
            "operating_cash_flow": [n + r * (sp["da"] - sp["wc"] + wobble) for n, r in zip(flows["net_income"], rev_q)],
            "capital_expenses": [r * sp["capex"] for r in rev_q],
        }
        q_starts = [start] + [_nd(e) for e in ends[:3]]
        for i in range(n_q):
            fp = f"Q{i + 1}"
            if i < 3:
                for c, vals in flows.items():
                    recs.append(_rec(c, q_starts[i], ends[i], vals[i], fy, fp))
                    if i > 0:
                        recs.append(_rec(c, start, ends[i], sum(vals[:i + 1]), fy, fp))
            for c, vals in cf.items():                    # cash flow: YTD only
                if i < 3 or n_q == 4:
                    recs.append(_rec(c, start, ends[i], sum(vals[:i + 1]), fy, fp if i < 3 else "FY"))
            ann = revenue_fy * (1 + 0.02 * i)
            cash, ar, inv, other_ca = ann * 0.10, ann * 0.12, ann * 0.09, ann * 0.02
            ca = cash + ar + inv + other_ca
            nca = ann * sp["nca"]
            ap, std, other_cl = ann * 0.07, sp["std"], ann * 0.05
            cl = ap + std + other_cl
            ltd, other_ltl = sp["ltd"], ann * 0.04
            liab = cl + ltd + other_ltl
            assets = ca + nca
            bs = {"cash_and_marketable_securities": cash, "trade_receivables": ar, "inventories": inv,
                  "current_assets_total": ca, "assets": assets, "trade_payables": ap, "short_term_debt": std,
                  "current_liabilities_total": cl, "long_term_debt": ltd, "liabilities": liab,
                  "all_equity_balance": assets - liab, "liabilities_and_equity": assets,
                  "retained_earnings": (assets - liab) * 0.6}
            for c, v in bs.items():
                recs.append(_rec(c, None, ends[i], v, fy, fp))
        if n_q == 4:
            for c, vals in flows.items():
                recs.append(_rec(c, start, ends[3], sum(vals), fy, "FY"))
        revenue_fy *= 1 + sp["growth"]
    return recs


# Made-up market inputs for the synthetic companies (the real DCF model runs on them).
DEMO_DCF_ASSUMPTIONS = {
    "mode": "forecast",
    "market": {"price": 45.0, "price_date": AS_OF, "basic_shares": 330e6},
    "forecast": {"years_to_terminal": 10, "revenue_growth": 0.08, "terminal_growth": 0.03, "tax_rate": 0.21},
    "cost_of_capital": {"risk_free": 0.042, "risk_free_terminal": 0.05, "equity_risk_premium": 0.05,
                        "beta": 1.1, "pre_tax_cost_of_debt": 0.06},
    "sources": {"all": "synthetic demo values"},
}
OTHER_ASSUMPTIONS = {
    "DEMOG": {"market": {"price": 18.0, "price_date": AS_OF, "basic_shares": 100e6},
              "forecast": {"revenue_growth": 0.25, "terminal_growth": 0.03, "tax_rate": 0.21},
              "cost_of_capital": {"beta": 1.4}},
    "DEMOU": {"market": {"price": 98.0, "price_date": AS_OF, "basic_shares": 250e6},
              "forecast": {"revenue_growth": 0.02, "terminal_growth": 0.02, "tax_rate": 0.21},
              "cost_of_capital": {"beta": 0.6}},
}


def _assumptions(ticker: str) -> dict:
    a = json.loads(json.dumps(DEMO_DCF_ASSUMPTIONS))
    for k, v in OTHER_ASSUMPTIONS.get(ticker, {}).items():
        a[k] = {**a[k], **v}
    return a


def _model_result(model, ticker, p10, p50, p90, assumptions):
    return {"schema_version": "0.1.0", "model": model, "ticker": ticker, "as_of": AS_OF,
            "value_per_share": {"p10": p10, "p50": p50, "p90": p90, "mean": (p10 + p50 + p90) / 3},
            "assumptions_used": assumptions, "lineage": {"as_of": AS_OF, "inputs": []},
            "samples_ref": None, "notes": ["synthetic demo result, not a valuation"], "demo": True}


def write_company(site_dir: Path, ticker: str) -> Path:
    from L2_models.base import get_model
    spec = SPECS[ticker]
    out = site_dir / "data" / ticker / AS_OF
    (out / "model_results").mkdir(parents=True, exist_ok=True)
    canonical = {"stage": "L1.normalize", "as_of": AS_OF,
                 "entity": {"ticker": ticker, "name": spec["name"], "cik": None},
                 "records": synthetic_records(spec)}
    detail = build_detail(canonical, AS_OF)
    detail["demo"] = True
    (out / "company_detail.json").write_text(json.dumps(detail, indent=2))
    dcf = get_model("dcf").run(detail, _assumptions(ticker)).to_dict()
    dcf["lineage"] = {"as_of": AS_OF, "inputs": []}
    dcf["demo"] = True
    dcf["notes"].insert(0, "synthetic demo company; market inputs are made up")
    mid = dcf["value_per_share"]["p50"]
    results = {
        "dcf": dcf,
        "comps": _model_result("comps", ticker, mid * 0.86, mid * 1.02, mid * 1.18, {"forecast": {"tax_rate": 0.21}}),
        "precedents": _model_result("precedents", ticker, mid * 1.04, mid * 1.24, mid * 1.42, {}),
    }
    paths = []
    for m, r in results.items():
        p = out / "model_results" / f"{m}.json"
        p.write_text(json.dumps(r, indent=2))
        paths.append(p)
    comparison = build_comparison(paths, detail)
    comparison["demo"] = True
    (out / "comparison.json").write_text(json.dumps(comparison, indent=2))
    return out


def write_demo(site_dir: Path) -> Path:
    """All synthetic companies; returns the main DEMO folder."""
    for t in SPECS:
        write_company(site_dir, t)
    return site_dir / "data" / "DEMO" / AS_OF


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="L3_app.demo")
    p.add_argument("--site-dir", type=Path, default=Path("site"))
    args = p.parse_args(argv)
    print(f"wrote demo data -> {write_demo(args.site_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
