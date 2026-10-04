"""Synthetic companies for the demo: canonical records in the usual 10-Q/10-K pattern
(income statement by quarter and full year, cash flow year-to-date only), from a few
parameters per company. Not real data; every name says "(synthetic)" and every ticker
starting ZZ is made up."""
from __future__ import annotations

from datetime import date, timedelta

from L1_detail.normalize import _months

AS_OF = "2026-09-30"
SEASON = (0.23, 0.24, 0.25, 0.28)


def _rec(concept, start, end, value, fy, fp):
    return {"concept": concept, "start": start, "end": end, "value": round(value, 2),
            "months": _months(start, end) if start else None, "fiscal_year": fy, "fiscal_period": fp,
            "restated": False, "method": "reported", "value_as_filed": round(value, 2),
            "statement": "", "period_type": "duration" if start else "instant", "unit": "USD", "source": {}}


def _nd(s):
    return (date.fromisoformat(s) + timedelta(days=1)).isoformat()


DEMO_SIC = {"DEMO": "3569", "DEMOG": "7372", "DEMOU": "4911",
            # peers with full company detail: machinery, electrical equipment, trucking
            "ZZA": "3560", "ZZB": "3561", "ZZC": "3564", "ZZD": "3612", "ZZE": "3620", "ZZF": "4213"}

SPECS = {
    # ticker: name, first-year revenue, growth, margins (share of revenue), balance sheet scale
    "DEMO": dict(name="Demo Manufacturing Co. (synthetic)", rev0=4.0e9, growth=0.08, cogs=0.58, sga=0.18,
                 rnd=0.06, da=0.04, capex=0.05, wc=0.02, nca=0.55, ltd=0.9e9, std=0.15e9, noise=0.0),
    "DEMOG": dict(name="Demo Cloud Software (synthetic)", rev0=0.8e9, growth=0.32, cogs=0.30, sga=0.45,
                  rnd=0.22, da=0.02, capex=0.02, wc=-0.03, nca=0.25, ltd=0.0, std=0.0, noise=0.06),
    "DEMOU": dict(name="Demo Regional Utility (synthetic)", rev0=6.0e9, growth=0.02, cogs=0.52, sga=0.10,
                  rnd=0.0, da=0.10, capex=0.17, wc=0.01, nca=3.0, ltd=14e9, std=1.0e9, noise=0.01),
    # comps peers for DEMO, with full company detail
    "ZZA": dict(name="Synthetic Pumps Inc. (synthetic)", rev0=6.5e9, growth=0.06, cogs=0.60, sga=0.17,
                rnd=0.04, da=0.045, capex=0.05, wc=0.02, nca=0.60, ltd=1.6e9, std=0.2e9, noise=0.01),
    "ZZB": dict(name="Synthetic Flow Controls (synthetic)", rev0=5.2e9, growth=0.10, cogs=0.53, sga=0.19,
                rnd=0.05, da=0.04, capex=0.04, wc=0.02, nca=0.50, ltd=0.8e9, std=0.1e9, noise=0.02),
    "ZZC": dict(name="Synthetic Air Systems (synthetic)", rev0=3.6e9, growth=0.04, cogs=0.64, sga=0.16,
                rnd=0.03, da=0.05, capex=0.06, wc=0.03, nca=0.70, ltd=1.4e9, std=0.3e9, noise=0.02),
    "ZZD": dict(name="Synthetic Grid Equipment (synthetic)", rev0=4.4e9, growth=0.12, cogs=0.57, sga=0.15,
                rnd=0.07, da=0.035, capex=0.05, wc=0.03, nca=0.45, ltd=1.0e9, std=0.1e9, noise=0.03),
    "ZZE": dict(name="Synthetic Motors & Drives (synthetic)", rev0=2.3e9, growth=0.07, cogs=0.62, sga=0.17,
                rnd=0.05, da=0.04, capex=0.05, wc=0.02, nca=0.55, ltd=0.5e9, std=0.05e9, noise=0.02),
    "ZZF": dict(name="Synthetic Freight Lines (synthetic)", rev0=5.8e9, growth=0.03, cogs=0.78, sga=0.09,
                rnd=0.0, da=0.08, capex=0.11, wc=0.01, nca=1.10, ltd=2.6e9, std=0.3e9, noise=0.03),
}
FEATURED = ("DEMO", "DEMOG", "DEMOU")          # the three companies the tour walks through
PEERS = ("ZZA", "ZZB", "ZZC", "ZZD", "ZZE", "ZZF")


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



# price, shares, "true" beta used to generate the synthetic monthly returns
DEMO_PRICES = {"DEMO": (45.0, 330e6), "DEMOG": (18.0, 100e6), "DEMOU": (130.0, 250e6)}
MARKET = {
    "DEMO": (45.0, 330e6, 1.05), "DEMOG": (18.0, 100e6, 1.45), "DEMOU": (130.0, 250e6, 0.55),
    # peer prices set so EV/EBITDA lands at 8.5x-14x, a realistic spread around DEMO's 12x
    "ZZA": (85.5, 260e6, 1.10), "ZZB": (159.0, 180e6, 1.20), "ZZC": (34.5, 240e6, 1.00),
    "ZZD": (212.5, 120e6, 1.30), "ZZE": (61.4, 110e6, 1.15), "ZZF": (32.3, 300e6, 0.95),
}
# One made-up peer without SEC data, to show manual figures alongside filed ones.
MANUAL_PEER = {"ticker": "MANUALCO", "sec": False, "name": "Manual peer (synthetic)", "price": 30.0, "shares": 2.0e8,
               "debt": 4.0e8, "cash": 2.0e8, "sales": 2.4e9, "ebitda": 4.4e8, "net_income": 2.4e8}
