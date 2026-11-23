"""Write sysco_fy2026.xlsx: every number after the Inputs sheet is an Excel formula.

    pip install openpyxl
    python studies/sysco-fy2026/build_workbook.py
    soffice --headless --convert-to xlsx --outdir /tmp/recalc studies/sysco-fy2026/sysco_fy2026.xlsx
    cp /tmp/recalc/sysco_fy2026.xlsx studies/sysco-fy2026/ && python studies/sysco-fy2026/case.py --check

openpyxl writes formulas without results; the LibreOffice pass calculates them
and stores the values, which `case.py --check` then compares with the script.
Yellow cells are assumptions to change; blue text is a filed number.
"""
from __future__ import annotations

import json
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HERE = Path(__file__).parent
inp = json.loads((HERE / "inputs.json").read_text())
FYS = ["FY2022", "FY2023", "FY2024", "FY2025"]
INPUT = Font(color="1F4E9E")
BOLD = Font(bold=True)
HEAD = Font(bold=True, color="FFFFFF")
HEAD_FILL = PatternFill("solid", fgColor="4F46E5")
EDIT = PatternFill("solid", fgColor="FFF2B3")
M = '#,##0;(#,##0)'
P = '0.00%'
D = '$#,##0.00'

wb = Workbook()


def header(ws, row, labels, widths=None):
    for c, lab in enumerate(labels, 1):
        cell = ws.cell(row, c, lab)
        cell.font, cell.fill = HEAD, HEAD_FILL
    for c, w in enumerate(widths or [], 1):
        ws.column_dimensions[get_column_letter(c)].width = w


# ---- Inputs: filed values, point in time ---------------------------------------------------
ws = wb.active
ws.title = "Inputs"
ws["A1"] = f"Sysco Corporation (SYY): filed values known on {inp['cutoff']} ({inp['cutoff_filing']}). $ millions."
ws["A1"].font = BOLD
ws["A2"] = "Source: SEC EDGAR company facts. First-filed value per period, so later restatements don't leak in."
header(ws, 4, ["Line", *FYS, "XBRL tag", "FY2025 accession", "Filed"], [30, 11, 11, 11, 11, 52, 24, 11])
REF: dict[str, dict[str, str]] = {}
r = 5
for line, x in inp["known"].items():
    if line == "shares_outstanding":
        continue
    ws.cell(r, 1, line.replace("_", " "))
    REF[line] = {}
    for c, fy in enumerate(FYS, 2):
        if x.get(fy):
            cell = ws.cell(r, c, x[fy]["value"])
            cell.number_format, cell.font = M, INPUT
            REF[line][fy] = f"Inputs!${get_column_letter(c)}${r}"
    ws.cell(r, 6, x["tag"])
    ws.cell(r, 7, x["FY2025"]["accn"])
    ws.cell(r, 8, x["FY2025"]["filed"])
    r += 1
sh = inp["known"]["shares_outstanding"]["cover"]
ws.cell(r, 1, "shares outstanding (cover, millions)")
c = ws.cell(r, 5, sh["value"])
c.number_format, c.font = '#,##0.0', INPUT
ws.cell(r, 6, "dei:EntityCommonStockSharesOutstanding"), ws.cell(r, 7, sh["accn"]), ws.cell(r, 8, sh["filed"])
REF["shares"] = {"FY2025": f"Inputs!$E${r}"}
r += 2
header(ws, r, ["Market input", "Value", "", "", "", "Source", "Known at cutoff?"])
r += 1
for k, x in inp["market"].items():
    ws.cell(r, 1, k.replace("_", " "))
    c = ws.cell(r, 2, x["value"])
    c.number_format, c.font = ('0.00%' if x["value"] < 0.2 else '0.00'), INPUT
    ws.cell(r, 6, x["source"]), ws.cell(r, 7, "yes" if x["available_at_cutoff"] else "NO: later vintage")
    REF[k] = {"v": f"Inputs!$B${r}"}
    r += 1
r += 1
header(ws, r, ["FY2026 outcome (scoring only)", "FY2026", "", "", "", "XBRL tag", "Accession", "Filed"])
r += 1
for line, x in inp["outcome"].items():
    ws.cell(r, 1, line.replace("_", " "))
    c = ws.cell(r, 2, x["FY2026"]["value"])
    c.number_format, c.font = M, INPUT
    ws.cell(r, 6, x["tag"]), ws.cell(r, 7, x["FY2026"]["accn"]), ws.cell(r, 8, x["FY2026"]["filed"])
    REF.setdefault("out", {})[line] = f"Inputs!$B${r}"
    r += 1
ws.freeze_panes = "B5"


def I(line, fy="FY2025"):  # noqa: E743
    return REF[line][fy]


def nwc(fy):
    return f"({I('receivables', fy)}+{I('inventory', fy)}-{I('payables', fy)})"


def cfnwc(fy):
    return f"({I('chg_receivables', fy)}+{I('chg_inventory', fy)}-{I('chg_payables', fy)})"


# ---- Drivers ---------------------------------------------------------------------------------
dr = wb.create_sheet("Drivers")
header(dr, 1, ["Driver", "Value", "How it's computed"], [40, 12, 90])
DRV = {}
rows = [
    ("growth", "FY2026 revenue growth", f"={I('revenue')}/{I('revenue','FY2024')}-1", P, "FY2025 growth repeated, fading to terminal by FY2030", True),
    ("margin", "EBIT margin", f"={I('operating_income')}/{I('revenue')}", P, "FY2025 operating income / revenue, held flat", True),
    ("da", "D&A, % of revenue", f"={I('depreciation_amortization')}/{I('revenue')}", P, "FY2025", False),
    ("sbc", "Stock comp, % of revenue", f"={I('share_based_comp')}/{I('revenue')}", P, "FY2025; a real cost in FCFF, added back in CFO", False),
    ("capex", "Capex, % of revenue", "=AVERAGE(" + ",".join(f"{I('capex',fy)}/{I('revenue',fy)}" for fy in FYS[1:]) + ")", P, "average FY2023-FY2025 (PaymentsToAcquireProductiveAssets)", True),
    ("tax", "Tax rate", f"={I('income_tax')}/{I('pretax_income')}", P, "FY2025 effective rate", True),
    ("interest", "Net interest expense", f"=-{I('net_interest_expense')}", M, "FY2025, held flat", False),
    ("nwc_ratio", "Trade NWC / revenue, FY2025", f"={nwc('FY2025')}/{I('revenue')}", P, "(receivables + inventory - payables) / revenue", False),
    ("nwc_m1", "NWC per $ of new sales, FY2025", f"={cfnwc('FY2025')}/({I('revenue')}-{I('revenue','FY2024')})", P, "cash-flow statement changes / revenue change", False),
    ("nwc_m3", "NWC per $ of new sales, FY2023-25", "=(" + "+".join(cfnwc(fy) for fy in FYS[1:]) + f")/({I('revenue')}-{I('revenue','FY2022')})", P, "three-year evidence for the judgment", False),
    ("rate_A", "Option A: NWC per $ of new sales", "=B9", P, "JUDGMENT A: working capital stays at FY2025's share of sales", True),
    ("rate_B", "Option B: NWC per $ of new sales", "=B10", P, "JUDGMENT B: FY2025's step-up in inventory and receivables repeats", True),
    ("g", "Terminal growth", 0.025, P, "after FY2030", True),
    ("beta_u", "Unlevered beta", f"={REF['unlevered_beta_food_wholesalers']['v']}", '0.00', "Food Wholesalers; type the Retail (Grocery and Food) 0.85 to see the engine's choice", True),
    ("de", "Target debt / equity", f"={REF['industry_debt_to_equity']['v']}", '0.00', "industry market D/E", True),
    ("beta_l", "Levered beta", "=B15*(1+(1-B7)*B16)", '0.00', "Hamada", False),
    ("ke", "Cost of equity", f"={REF['risk_free']['v']}+B17*{REF['equity_risk_premium']['v']}", P, "risk-free + beta x ERP", False),
    ("kd", "After-tax cost of debt", f"=-{I('net_interest_expense')}/AVERAGE({I('debt_total','FY2024')},{I('debt_total')})*(1-B7)", P, "net interest / average debt, after tax", False),
    ("wd", "Debt weight", "=B16/(1+B16)", P, "", False),
    ("wacc", "WACC", "=(1-B20)*B18+B20*B19", P, "", False),
    ("debt", "Debt (incl. finance leases)", f"={I('debt_total')}", M, "DebtAndCapitalLeaseObligations; operating leases left out, their cost stays in EBIT", False),
    ("cash", "Cash", f"={I('cash')}", M, "all treated as excess", False),
    ("shares", "Shares outstanding", f"={REF['shares']['FY2025']}", '#,##0.0', "10-K cover", False),
]
for i, (key, lab, f, fmt, note, edit) in enumerate(rows, 2):
    dr.cell(i, 1, lab)
    c = dr.cell(i, 2, f)
    c.number_format = fmt
    if edit:
        c.fill = EDIT
    dr.cell(i, 3, note)
    DRV[key] = f"Drivers!$B${i}"
assert DRV["nwc_ratio"] == "Drivers!$B$9" and DRV["nwc_m1"] == "Drivers!$B$10" and DRV["beta_u"] == "Drivers!$B$15"


# ---- Forecast: one block per working-capital option -------------------------------------------
fc = wb.create_sheet("Forecast")
fc.column_dimensions["A"].width = 34
for col in "BCDEFG":
    fc.column_dimensions[col].width = 12
BLOCK = {}


def block(top: int, opt: str, rate: str) -> int:
    fc.cell(top, 1, f"Option {opt}").font = BOLD
    years = ["FY2026", "FY2027", "FY2028", "FY2029", "FY2030", "Terminal"]
    header(fc, top + 1, ["$ millions", *years])
    L = ["growth", "revenue", "ebit", "net_income", "da", "sbc", "capex", "change_nwc", "cfo", "fcff", "bridge_check", "discount", "pv"]
    labels = ["Revenue growth", "Revenue", "EBIT", "Net income", "D&A", "Stock comp", "Capex",
              "Increase in trade NWC", "Operating cash flow (CFO)", "FCFF", "Bridge check: CFO - SBC + int(1-t) - capex - FCFF",
              "Discount factor", "PV of FCFF"]
    R = {k: top + 2 + i for i, k in enumerate(L)}
    for k, lab in zip(L, labels):
        fc.cell(R[k], 1, lab)
    for j in range(6):
        col = get_column_letter(j + 2)
        prev_rev = I("revenue") if j == 0 else f"{get_column_letter(j + 1)}{R['revenue']}"
        cell = lambda k: f"{col}{R[k]}"  # noqa: E731
        g = f"={DRV['g']}" if j == 5 else f"={DRV['growth']}+({DRV['g']}-{DRV['growth']})*{j}/4"
        f = {"growth": g, "revenue": f"={prev_rev}*(1+{cell('growth')})", "ebit": f"={cell('revenue')}*{DRV['margin']}",
             "net_income": f"=({cell('ebit')}-{DRV['interest']})*(1-{DRV['tax']})", "da": f"={cell('revenue')}*{DRV['da']}",
             "sbc": f"={cell('revenue')}*{DRV['sbc']}", "capex": f"={cell('revenue')}*{DRV['capex']}",
             "change_nwc": f"=({cell('revenue')}-{prev_rev})*{rate}",
             "cfo": f"={cell('net_income')}+{cell('da')}+{cell('sbc')}-{cell('change_nwc')}",
             "fcff": f"={cell('ebit')}*(1-{DRV['tax']})+{cell('da')}-{cell('capex')}-{cell('change_nwc')}",
             "bridge_check": f"={cell('cfo')}-{cell('sbc')}+{DRV['interest']}*(1-{DRV['tax']})-{cell('capex')}-{cell('fcff')}",
             "discount": f"=1/(1+{DRV['wacc']})^{j + 1}" if j < 5 else None,
             "pv": f"={cell('fcff')}*{cell('discount')}" if j < 5 else None}
        for k in L:
            if f[k] is None:
                continue
            c = fc[cell(k)]
            c.value = f[k]
            c.number_format = P if k == "growth" else ('0.0000' if k == "discount" else M)
    s = top + 2 + len(L) + 1
    out = [("Terminal value at FY2030", f"=G{R['fcff']}/({DRV['wacc']}-{DRV['g']})", M),
           ("PV of terminal value", f"=B{s}*F{R['discount']}", M),
           ("Enterprise value", f"=SUM(B{R['pv']}:F{R['pv']})+B{s + 1}", M),
           ("Terminal share of value", f"=B{s + 1}/B{s + 2}", P),
           ("Less debt", f"=-{DRV['debt']}", M), ("Plus cash", f"={DRV['cash']}", M),
           ("Equity value", f"=B{s + 2}+B{s + 4}+B{s + 5}", M),
           ("Value per share", f"=B{s + 6}/{DRV['shares']}", D)]
    for i, (lab, f, fmt) in enumerate(out):
        fc.cell(s + i, 1, lab)
        c = fc.cell(s + i, 2, f)
        c.number_format = fmt
    fc.cell(s + 7, 1).font = BOLD
    BLOCK[opt] = {"cfo": f"Forecast!$B${R['cfo']}", "fcff": f"Forecast!$B${R['fcff']}", "nwc": f"Forecast!$B${R['change_nwc']}",
                  "fcff_row": R["fcff"], "ps": f"Forecast!$B${s + 7}"}
    return s + len(out) + 2


nxt = block(1, "A", DRV["rate_A"])
block(nxt, "B", DRV["rate_B"])

# ---- Bridge: reported CFO to FCFF, on actuals ----------------------------------------------------
br = wb.create_sheet("Bridge")
header(br, 1, ["Reported cash flow to FCFF, $ millions", "FY2025", "FY2026", "Note"], [46, 12, 12, 60])
O = REF["out"]
A25 = {k: I(k) for k in ("operating_cash_flow", "share_based_comp", "net_interest_expense", "capex", "operating_income",
                         "depreciation_amortization", "income_tax", "pretax_income")}
lines = [
    ("Operating cash flow, as reported", lambda s: f"={s['operating_cash_flow']}", "cash-flow statement"),
    ("Less stock comp", lambda s: f"=-{s['share_based_comp']}", "treated as a cost"),
    ("Plus net interest x (1 - tax rate)", lambda s: f"=-{s['net_interest_expense']}*(1-{s['income_tax']}/{s['pretax_income']})", "FCFF is before financing"),
    ("Less capex", lambda s: f"=-{s['capex']}", ""),
    ("Less other items in CFO (plug)", lambda s: None, "deferred taxes, accruals, other income: zero in the forecast by construction"),
    ("FCFF", lambda s: None, "computed directly: EBIT(1-t) + D&A - capex - increase in trade NWC"),
]
O26 = {k: O[k] for k in A25}
for i, (lab, fn, note) in enumerate(lines, 2):
    br.cell(i, 1, lab)
    br.cell(i, 4, note)
    for col, src, fy in (("B", A25, "FY2025"), ("C", O26, "FY2026")):
        if lab == "FCFF":
            nwc_ch = cfnwc("FY2025") if fy == "FY2025" else f"({O['chg_receivables']}+{O['chg_inventory']}-{O['chg_payables']})"
            f = f"={src['operating_income']}*(1-{src['income_tax']}/{src['pretax_income']})+{src['depreciation_amortization']}-{src['capex']}-{nwc_ch}"
        elif "plug" in lab:
            f = f"={col}7-SUM({col}2:{col}5)"
        else:
            f = fn(src)
        br[f"{col}{i}"] = f
        br[f"{col}{i}"].number_format = M
br["A7"].font = BOLD

# ---- Score: the forecast against what Sysco later filed -------------------------------------------
sc = wb.create_sheet("Score")
header(sc, 1, ["FY2026, $ millions", "Option A", "Option B", "Naive: FY2025 repeats", "Actual (10-K, Aug 2026)"], [30, 12, 12, 22, 24])
items = [("Increase in trade NWC", "nwc", f"({O['chg_receivables']}+{O['chg_inventory']}-{O['chg_payables']})", cfnwc("FY2025")),
         ("Operating cash flow", "cfo", O["operating_cash_flow"], I("operating_cash_flow")),
         ("FCFF", "fcff", "Bridge!$C$7", "Bridge!$B$7")]
for i, (lab, k, act, naive) in enumerate(items, 2):
    sc.cell(i, 1, lab)
    for col, f in (("B", f"={BLOCK['A'][k]}"), ("C", f"={BLOCK['B'][k]}"), ("D", f"={naive}"), ("E", f"={act}")):
        sc[f"{col}{i}"] = f
        sc[f"{col}{i}"].number_format = M
sc.cell(6, 1, "CFO error vs actual")
for col in "BCD":
    sc[f"{col}6"] = f"={col}3-$E$3"
    sc[f"{col}6"].number_format = M
    sc[f"{col}7"] = f"={col}3/$E$3-1"
    sc[f"{col}7"].number_format = P
sc.cell(7, 1, "CFO error, %")

# ---- Sensitivity: value per share by option and beta (closed form, recalculates) ---------------------
se = wb.create_sheet("Sensitivity")
se.column_dimensions["A"].width = 30
se["A1"] = "Value per share by working-capital option and unlevered beta (other drivers as on Drivers)"
se["A1"].font = BOLD
betas = [0.55, 0.65, 0.75, 0.85]
header(se, 3, ["Unlevered beta", *[f"{b:.2f}" for b in betas]])
se.cell(4, 1, "WACC")
for j, b in enumerate(betas):
    col = get_column_letter(j + 2)
    se[f"{col}2"] = b
    lev = f"{col}$2*(1+(1-{DRV['tax']})*{DRV['de']})"
    se[f"{col}4"] = f"=(1-{DRV['wd']})*({REF['risk_free']['v']}+{lev}*{REF['equity_risk_premium']['v']})+{DRV['wd']}*{DRV['kd']}"
    se[f"{col}4"].number_format = P
for i, opt in enumerate("AB"):
    r = 5 + i
    se.cell(r, 1, f"Option {opt}")
    fr = BLOCK[opt]["fcff_row"]
    for j in range(len(betas)):
        col = get_column_letter(j + 2)
        w = f"{col}$4"
        f = (f"=(NPV({w},Forecast!$B${fr}:$F${fr})+Forecast!$G${fr}/({w}-{DRV['g']})/(1+{w})^5"
             f"-{DRV['debt']}+{DRV['cash']})/{DRV['shares']}")
        se[f"{col}{r}"] = f
        se[f"{col}{r}"].number_format = D
se["A8"] = "0.65 = Food Wholesalers (this case). 0.85 = Retail (Grocery and Food), the industry the engine maps Sysco to."
se["A2"] = "beta values (edit)"
for j in range(len(betas)):
    se.cell(2, j + 2).fill = EDIT

# ---- Summary: read by case.py --check -------------------------------------------------------------
su = wb.create_sheet("Summary", 0)
su.column_dimensions["A"].width = 34
su.column_dimensions["B"].width = 60
su.column_dimensions["C"].width = 14
su["A1"] = "Sysco FY2026: cash flow and standalone value as of the FY2025 10-K (2025-08-22)"
su["A1"].font = BOLD
su["A2"] = "Analysis of method, not investment advice. Public SEC filings; see Inputs for every source."
summary = [("FY2026 CFO, option A", "Working capital holds at FY2025's share of sales", f"={BLOCK['A']['cfo']}", M),
           ("FY2026 CFO, option B", "FY2025's working-capital step-up repeats", f"={BLOCK['B']['cfo']}", M),
           ("FY2026 FCFF, option A", "", f"={BLOCK['A']['fcff']}", M),
           ("FY2026 FCFF, option B", "", f"={BLOCK['B']['fcff']}", M),
           ("Actual FY2026 CFO", "10-K filed 2026-08-21, for scoring only", f"={O['operating_cash_flow']}", M),
           ("WACC", "change beta or D/E on Drivers", f"={DRV['wacc']}", P),
           ("Value per share, option A", "standalone, before any control premium or synergies", f"={BLOCK['A']['ps']}", D),
           ("Value per share, option B", "", f"={BLOCK['B']['ps']}", D)]
header(su, 4, ["Result", "Meaning", "Value"])
for i, (k, note, f, fmt) in enumerate(summary, 5):
    su.cell(i, 1, k)
    su.cell(i, 2, note)
    c = su.cell(i, 3, f)
    c.number_format = fmt
for ws_ in wb.worksheets:
    for row in ws_.iter_rows():
        for c in row:
            c.alignment = Alignment(vertical="top")
wb.save(HERE / "sysco_fy2026.xlsx")
print("wrote", HERE / "sysco_fy2026.xlsx")
