"""Sysco, FY2026 cash flow and standalone value as of the FY2025 10-K (2025-08-22).

    python studies/sysco-fy2026/case.py            # prints the case, writes results.json
    python studies/sysco-fy2026/case.py --check    # also checks the workbook's cached values

Standard library only. Reads the frozen inputs.json, never the network. Every
driver below is computed from a filed number, so changing a line here (or the
yellow cells in the workbook) is how you challenge the answer.

Cash-flow measures, $ millions:
  CFO   cash from operations as Sysco reports it
        = net income + D&A + stock comp - increase in trade working capital + other items
  FCFF  free cash flow to the firm, the DCF's measure
        = EBIT x (1 - tax rate) + D&A - capex - increase in trade working capital
  Bridge, both directions: FCFF = CFO - stock comp + net interest x (1 - t) - capex - other items
  Stock comp is treated as a real operating cost, so it is not added back in FCFF.
  "Trade working capital" = receivables + inventory - payables.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HERE = Path(__file__).parent
YEARS = 5                       # explicit forecast, FY2026-FY2030
TERMINAL_GROWTH = 0.025


def load(path: Path = HERE / "inputs.json") -> dict:
    return json.loads(path.read_text())


def v(inp: dict, line: str, fy: str = "FY2025") -> float:
    return inp["known"][line][fy]["value"]


def drivers(inp: dict) -> dict:
    rev = {fy: v(inp, "revenue", fy) for fy in ("FY2022", "FY2023", "FY2024", "FY2025")}
    nwc = lambda fy: v(inp, "receivables", fy) + v(inp, "inventory", fy) - v(inp, "payables", fy)  # noqa: E731
    cf_nwc = lambda fy: v(inp, "chg_receivables", fy) + v(inp, "chg_inventory", fy) - v(inp, "chg_payables", fy)  # noqa: E731
    d_rev = lambda fy, prev: rev[fy] - rev[prev]  # noqa: E731
    tax = v(inp, "income_tax") / v(inp, "pretax_income")
    avg_debt = (v(inp, "debt_total", "FY2024") + v(inp, "debt_total")) / 2
    return {
        "revenue_fy2025": rev["FY2025"],
        "growth_fy2026": rev["FY2025"] / rev["FY2024"] - 1,
        "ebit_margin": v(inp, "operating_income") / rev["FY2025"],
        "da_pct": v(inp, "depreciation_amortization") / rev["FY2025"],
        "sbc_pct": v(inp, "share_based_comp") / rev["FY2025"],
        "capex_pct": sum(v(inp, "capex", fy) / rev[fy] for fy in ("FY2023", "FY2024", "FY2025")) / 3,
        "tax_rate": tax,
        "net_interest": -v(inp, "net_interest_expense"),
        "nwc_fy2025": nwc("FY2025"),
        "nwc_to_sales": nwc("FY2025") / rev["FY2025"],
        # the judgment: how much working capital each new dollar of sales ties up
        "nwc_marginal_fy2025": cf_nwc("FY2025") / d_rev("FY2025", "FY2024"),
        "nwc_marginal_3yr": sum(cf_nwc(fy) for fy in ("FY2023", "FY2024", "FY2025"))
                            / (rev["FY2025"] - rev["FY2022"]),
        "pre_tax_cost_of_debt": -v(inp, "net_interest_expense") / avg_debt,
        "debt": v(inp, "debt_total"),
        "cash": v(inp, "cash"),
        "shares": inp["known"]["shares_outstanding"]["cover"]["value"],
        "cfo_fy2025": v(inp, "operating_cash_flow"),
        "cfo_other_fy2025": v(inp, "operating_cash_flow") - (v(inp, "net_income") + v(inp, "depreciation_amortization")
                                                             + v(inp, "share_based_comp") - cf_nwc("FY2025")),
    }


def wacc(d: dict, m: dict, beta_u: float) -> dict:
    de = m["industry_debt_to_equity"]["value"]
    beta = beta_u * (1 + (1 - d["tax_rate"]) * de)
    ke = m["risk_free"]["value"] + beta * m["equity_risk_premium"]["value"]
    kd = d["pre_tax_cost_of_debt"] * (1 - d["tax_rate"])
    wd = de / (1 + de)
    return {"beta_unlevered": beta_u, "beta_levered": beta, "cost_of_equity": ke, "after_tax_cost_of_debt": kd,
            "debt_weight": wd, "wacc": (1 - wd) * ke + wd * kd}


def forecast(d: dict, nwc_rate: float) -> list[dict]:
    """FY2026..FY2030 plus the terminal year. Growth fades linearly from FY2025's rate to terminal."""
    rows, rev = [], d["revenue_fy2025"]
    for i in range(1, YEARS + 2):
        g = TERMINAL_GROWTH if i > YEARS else d["growth_fy2026"] + (TERMINAL_GROWTH - d["growth_fy2026"]) * (i - 1) / (YEARS - 1)
        new = rev * (1 + g)
        ebit = new * d["ebit_margin"]
        da, capex, sbc = new * d["da_pct"], new * d["capex_pct"], new * d["sbc_pct"]
        d_nwc = (new - rev) * nwc_rate
        ni = (ebit - d["net_interest"]) * (1 - d["tax_rate"])
        cfo = ni + da + sbc - d_nwc
        fcff = ebit * (1 - d["tax_rate"]) + da - capex - d_nwc
        bridge = cfo - sbc + d["net_interest"] * (1 - d["tax_rate"]) - capex
        assert abs(bridge - fcff) < 1e-6, "CFO-to-FCFF bridge must tie"
        rows.append({"year": f"FY{2025 + i}" if i <= YEARS else "terminal", "growth": g, "revenue": new, "ebit": ebit,
                     "net_income": ni, "da": da, "sbc": sbc, "capex": capex, "change_nwc": d_nwc, "cfo": cfo, "fcff": fcff})
        rev = new
    return rows


def value(d: dict, rows: list[dict], w: float) -> dict:
    pv = sum(r["fcff"] / (1 + w) ** (i + 1) for i, r in enumerate(rows[:YEARS]))
    tv = rows[YEARS]["fcff"] / (w - TERMINAL_GROWTH)
    pv_tv = tv / (1 + w) ** YEARS
    ev = pv + pv_tv
    eq = ev - d["debt"] + d["cash"]
    return {"pv_fcff": pv, "pv_terminal": pv_tv, "terminal_share": pv_tv / ev, "enterprise_value": ev,
            "equity_value": eq, "per_share": eq / d["shares"]}


def outcome(inp: dict) -> dict:
    o = {k: x["FY2026"]["value"] for k, x in inp["outcome"].items()}
    t = o["income_tax"] / o["pretax_income"]
    d_nwc = o["chg_receivables"] + o["chg_inventory"] - o["chg_payables"]
    fcff = o["operating_income"] * (1 - t) + o["depreciation_amortization"] - o["capex"] - d_nwc
    other = o["operating_cash_flow"] - (o["net_income"] + o["depreciation_amortization"] + o["share_based_comp"] - d_nwc)
    return {"revenue": o["revenue"], "ebit": o["operating_income"], "net_income": o["net_income"],
            "change_nwc": d_nwc, "capex": o["capex"], "cfo": o["operating_cash_flow"], "fcff": fcff, "cfo_other_items": other}


def run(inp: dict) -> dict:
    d, m = drivers(inp), inp["market"]
    options = {"A_hold_ratio": d["nwc_to_sales"], "B_repeat_fy2025": d["nwc_marginal_fy2025"]}
    betas = {"food_wholesalers": m["unlevered_beta_food_wholesalers"]["value"],
             "retail_grocery_engine": m["unlevered_beta_retail_grocery"]["value"]}
    caps = {b: wacc(d, m, bu) for b, bu in betas.items()}
    cases = {}
    for o, rate in options.items():
        rows = forecast(d, rate)
        cases[o] = {"nwc_rate": rate, "fy2026": rows[0], "rows": rows,
                    "value": {b: value(d, rows, c["wacc"]) for b, c in caps.items()}}
    act = outcome(inp)
    base = {"cfo": d["cfo_fy2025"]}
    score = {name: {"cfo_error": c["fy2026"]["cfo"] - act["cfo"], "cfo_error_pct": c["fy2026"]["cfo"] / act["cfo"] - 1}
             for name, c in cases.items()}
    score["naive_repeat_fy2025"] = {"cfo_error": base["cfo"] - act["cfo"], "cfo_error_pct": base["cfo"] / act["cfo"] - 1}
    return {"cutoff": inp["cutoff"], "drivers": d, "cost_of_capital": caps, "cases": cases, "actual_fy2026": act,
            "score": score}


def check_workbook(res: dict, path: Path = HERE / "sysco_fy2026.xlsx", tol: float = 0.5) -> list[str]:
    """Compare the workbook's recalculated values with this script ($0.5M / $0.01 a share)."""
    from openpyxl import load_workbook                                 # dev-only dependency
    ws = load_workbook(path, data_only=True)["Summary"]
    got = {ws.cell(r, 1).value: ws.cell(r, 3).value for r in range(1, ws.max_row + 1) if ws.cell(r, 1).value}
    want = expected_summary(res)
    bad = []
    for k, x in want.items():
        y = got.get(k)
        t = 0.01 if "share" in k else tol
        if y is None or abs(y - x) > t:
            bad.append(f"{k}: workbook {y} vs script {x:.4f}")
    return bad


def expected_summary(res: dict) -> dict:
    a, b = res["cases"]["A_hold_ratio"], res["cases"]["B_repeat_fy2025"]
    return {"FY2026 CFO, option A": a["fy2026"]["cfo"], "FY2026 CFO, option B": b["fy2026"]["cfo"],
            "FY2026 FCFF, option A": a["fy2026"]["fcff"], "FY2026 FCFF, option B": b["fy2026"]["fcff"],
            "WACC": res["cost_of_capital"]["food_wholesalers"]["wacc"],
            "Value per share, option A": a["value"]["food_wholesalers"]["per_share"],
            "Value per share, option B": b["value"]["food_wholesalers"]["per_share"]}


def report(res: dict) -> str:
    d, act = res["drivers"], res["actual_fy2026"]
    L = [f"Sysco as of {res['cutoff']} ($M)", "",
         f"Drivers: growth {d['growth_fy2026']:.2%}, EBIT margin {d['ebit_margin']:.2%}, tax {d['tax_rate']:.2%}, "
         f"capex {d['capex_pct']:.2%} of sales", f"Trade NWC {d['nwc_to_sales']:.2%} of sales; marginal FY2025 "
         f"{d['nwc_marginal_fy2025']:.1%}, 3-yr {d['nwc_marginal_3yr']:.1%}", "",
         f"{'':28}{'Option A':>10}{'Option B':>10}{'Actual':>10}"]
    a, b = res["cases"]["A_hold_ratio"]["fy2026"], res["cases"]["B_repeat_fy2025"]["fy2026"]
    for k, lab in (("change_nwc", "Increase in trade NWC"), ("cfo", "Operating cash flow"), ("fcff", "FCFF")):
        L.append(f"{lab:28}{a[k]:>10,.0f}{b[k]:>10,.0f}{act[k]:>10,.0f}")
    L.append(f"{'Naive baseline CFO (FY2025)':28}{d['cfo_fy2025']:>30,.0f}")
    L.append("")
    for bname, c in res["cost_of_capital"].items():
        va = res["cases"]["A_hold_ratio"]["value"][bname]["per_share"]
        vb = res["cases"]["B_repeat_fy2025"]["value"][bname]["per_share"]
        L.append(f"WACC {c['wacc']:.2%} ({bname}): value/share A ${va:,.2f}, B ${vb:,.2f}")
    return "\n".join(L)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="compare with the workbook's cached values")
    args = ap.parse_args()
    res = run(load())
    (HERE / "results.json").write_text(json.dumps(res, indent=1) + "\n")
    print(report(res))
    if args.check:
        bad = check_workbook(res)
        print("workbook agrees" if not bad else "\n".join(["WORKBOOK MISMATCH"] + bad))
        raise SystemExit(1 if bad else 0)
