"""Synthetic demo company for previewing the site. Not real data.

  python -m L3_app.demo --site-dir site

Writes site/data/DEMO/{as_of}/company_detail.json (built by the real L1 build
from synthetic canonical records, in the usual 10-Q/10-K pattern: income
statement by quarter and full year, cash flow year-to-date only) plus two
synthetic model results and their comparison, so every tab has something to
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


def synthetic_records() -> list[dict]:
    recs = []
    revenue_fy = 4.0e9
    for fy in range(2021, 2027):
        start = f"{fy - 1}-10-01"
        ends = [f"{fy - 1}-12-31", f"{fy}-03-31", f"{fy}-06-30", f"{fy}-09-30"]
        n_q = 3 if fy == 2026 else 4                     # FY2026 10-K not filed by as_of
        rev_q = [revenue_fy * s for s in SEASON]
        flows = {
            "revenue": rev_q,
            "cost_of_goods_and_services_sold": [r * 0.58 for r in rev_q],
            "selling_general_and_admin_expenses": [r * 0.18 for r in rev_q],
            "research_and_development_expenses": [r * 0.06 for r in rev_q],
            "interest_expense": [15e6] * 4, "interest_income": [4e6] * 4,
        }
        flows["gross_profit"] = [r - c for r, c in zip(rev_q, flows["cost_of_goods_and_services_sold"])]
        flows["operating_income_loss"] = [r * 0.18 for r in rev_q]
        flows["pretax_income_loss"] = [o - 11e6 for o in flows["operating_income_loss"]]
        flows["income_taxes"] = [p * 0.21 for p in flows["pretax_income_loss"]]
        flows["net_income"] = [p * 0.79 for p in flows["pretax_income_loss"]]
        cf = {
            "depreciation_amortization_cf": [r * 0.04 for r in rev_q],
            "operating_cash_flow": [n + r * 0.04 - r * 0.02 for n, r in zip(flows["net_income"], rev_q)],
            "capital_expenses": [r * 0.05 for r in rev_q],
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
            # balance sheet at each quarter end
            ann = revenue_fy * (1 + 0.02 * i)
            cash, ar, inv, other_ca = ann * 0.10, ann * 0.12, ann * 0.09, ann * 0.02
            ca = cash + ar + inv + other_ca
            nca = ann * 0.55
            ap, std, other_cl = ann * 0.07, 0.15e9, ann * 0.05
            cl = ap + std + other_cl
            ltd, other_ltl = 0.9e9, ann * 0.04
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
        revenue_fy *= 1.08
    return recs


def _model_result(model, p10, p50, p90, assumptions):
    return {"schema_version": "0.1.0", "model": model, "ticker": "DEMO", "as_of": AS_OF,
            "value_per_share": {"p10": p10, "p50": p50, "p90": p90, "mean": (p10 + p50 + p90) / 3},
            "assumptions_used": assumptions, "lineage": {"as_of": AS_OF, "inputs": []},
            "samples_ref": None, "notes": ["synthetic demo result, not a valuation"], "demo": True}


def write_demo(site_dir: Path) -> Path:
    out = site_dir / "data" / "DEMO" / AS_OF
    (out / "model_results").mkdir(parents=True, exist_ok=True)
    canonical = {"stage": "L1.normalize", "as_of": AS_OF,
                 "entity": {"ticker": "DEMO", "name": "Demo Manufacturing Co. (synthetic)", "cik": None},
                 "records": synthetic_records()}
    detail = build_detail(canonical, AS_OF)
    detail["demo"] = True
    (out / "company_detail.json").write_text(json.dumps(detail, indent=2))
    results = {
        "dcf": _model_result("dcf", 41.0, 48.5, 57.0, {"forecast": {"tax_rate": 0.21},
                                                       "terminal": {"method": "gordon", "growth": 0.03}}),
        "comps": _model_result("comps", 38.0, 45.0, 52.5, {"forecast": {"tax_rate": 0.21}}),
        "precedents": _model_result("precedents", 46.0, 55.0, 63.0, {}),
    }
    paths = []
    for m, r in results.items():
        p = out / "model_results" / f"{m}.json"
        p.write_text(json.dumps(r, indent=2))
        paths.append(p)
    comparison = build_comparison(paths)
    comparison["demo"] = True
    (out / "comparison.json").write_text(json.dumps(comparison, indent=2))
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="L3_app.demo")
    p.add_argument("--site-dir", type=Path, default=Path("site"))
    args = p.parse_args(argv)
    print(f"wrote demo data -> {write_demo(args.site_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
