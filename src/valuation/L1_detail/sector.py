"""Sector screen: a few comparable figures for every company in a sector.

A sector is one of
  sector  a sector of configs/public/sectors/taxonomy.json (e.g. Technology): every SIC code under it
  sic     an SEC industry code (EDGAR's company list for that code)
  traits  companies whose profile traits match, across all industries
          (e.g. stage = high growth, asset intensity = light)
  list    a ticker list kept in the repo, configs/public/sectors/{name}.json

Figures come from SEC frames (one line item for all filers per call), not from
each company's full filing history, so the screen is cheap and covers hundreds
of companies. Full company detail is built later, for the companies you open.

Per company (latest calendar year with revenue; one year earlier if the filer
is late, flagged "stale"):
  revenue              largest of the revenue tags reported
  growth, 3-yr CAGR    from the same tags in earlier years
  margins              gross, operating, net
  EBITDA               operating income + D&A; D&A from a combined tag, else
                       depreciation + intangible amortization (EBIT alone if neither)
  capex                PP&E purchases, else "productive assets" purchases
  FCF                  operating cash flow - capex; margin and its stability
  balance sheet        assets, equity, liabilities (assets - equity if untagged),
                       cash, debt = long-term debt incl. current portion, plus
                       short-term borrowings when they aren't that same current portion
Traits use the same rules as the full company profile (profile.py); asset
intensity uses capex / sales only, since NOA turnover needs the full balance sheet.

Benchmarks: Q1 / median / Q3 of each metric across the sector's companies.
"""
from __future__ import annotations

from valuation._core.num import div as _div

import re
import statistics

from valuation.L1_detail.profile import (classify_capital, classify_intensity, classify_predictability,
                               classify_stage, load_rules)

SCHEMA_VERSION = "0.1.0"
BENCHMARK_METRICS = ["revenue_growth", "revenue_cagr", "gross_margin", "operating_margin", "net_margin",
                     "ebitda_margin", "fcf_margin", "capex_to_sales", "roa", "roe", "debt_to_ebitda",
                     "liabilities_to_assets"]
TRAITS = ("stage", "predictability", "asset_intensity", "capital_structure")
DEFAULT_LIMIT = 100
SECTOR_LIMIT = 300   # a whole sector (all of Technology) keeps more companies
# The raw screen carries the tags it fetched; these match L0's lists for older files.
DEFAULT_TAGS = {
    "revenue": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                "RevenueFromContractWithCustomerIncludingAssessedTax"],
    "depreciation": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
                     "DepreciationAmortizationAndAccretionNet"],
    "depreciation_parts": ["Depreciation", "AmortizationOfIntangibleAssets"],
    "cfo": "NetCashProvidedByUsedInOperatingActivities",
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
}




class Frames:
    """Lookup over a raw_screen document: value(tag, period, cik)."""

    def __init__(self, raw: dict):
        t = raw.get("tags") or {}
        self.revenue_tags = t.get("revenue") or DEFAULT_TAGS["revenue"]
        self.da_tags = t.get("depreciation") or DEFAULT_TAGS["depreciation"]
        self.da_parts = t.get("depreciation_parts") or DEFAULT_TAGS["depreciation_parts"]
        self.cfo_tag = t.get("cfo") or DEFAULT_TAGS["cfo"]
        self.capex_tags = t.get("capex") or DEFAULT_TAGS["capex"]
        self.by_key: dict[str, dict[int, list]] = {
            k: {int(r[0]): r for r in rows if r and r[0] is not None and r[4] is not None}
            for k, rows in (raw.get("frames") or {}).items() if isinstance(rows, list)}

    def row(self, tag: str, period: str, cik: int):
        return self.by_key.get(f"{tag}/{period}", {}).get(cik)

    def value(self, tag: str, period: str, cik: int):
        r = self.row(tag, period, cik)
        return r[4] if r else None

    def first(self, tags, period, cik):
        for t in tags:
            v = self.value(t, period, cik)
            if v is not None:
                return v
        return None

    def capex(self, period: str, cik: int):
        return self.first(self.capex_tags, period, cik)

    def da(self, period: str, cik: int):
        """(D&A, basis): a combined tag, else depreciation + intangible amortization."""
        v = self.first(self.da_tags, period, cik)
        if v is not None:
            return v, "reported"
        dep = self.value(self.da_parts[0], period, cik)
        if dep is None:
            return None, None
        amort = self.value(self.da_parts[1], period, cik)
        return dep + (amort or 0), "depreciation + amortization"

    def revenue(self, year: int, cik: int):
        vals = [self.value(t, f"CY{year}", cik) for t in self.revenue_tags]
        vals = [v for v in vals if v is not None]
        return max(vals) if vals else None

    def ciks_with_revenue(self, year: int) -> set[int]:
        out = set()
        for t in self.revenue_tags:
            out |= set(self.by_key.get(f"{t}/CY{year}", {}))
        return out


def company_metrics(fr: Frames, cik: int, year: int, rules: dict) -> dict | None:
    base = year if fr.revenue(year, cik) is not None else year - 1
    rev = fr.revenue(base, cik)
    if rev is None or rev <= 0:
        return None
    rev_row = next((fr.row(t, f"CY{base}", cik) for t in fr.revenue_tags if fr.row(t, f"CY{base}", cik)), None)
    prior = fr.revenue(base - 1, cik)
    cagr, cagr_years = None, None
    for back in (3, 2):
        old = fr.revenue(base - back, cik)
        if old and old > 0:
            cagr, cagr_years = (rev / old) ** (1 / back) - 1, back
            break

    P = f"CY{base}"
    v = lambda tag, p=P: fr.value(tag, p, cik)  # noqa: E731
    gp, oi, ni = v("GrossProfit"), v("OperatingIncomeLoss"), v("NetIncomeLoss")
    da, da_basis = fr.da(P, cik)
    ebitda = oi + da if oi is not None and da is not None else oi
    cfo, capex = v(fr.cfo_tag), fr.capex(P, cik)
    fcf = cfo - capex if cfo is not None and capex is not None else None
    fcf_margins = []
    for y in (base - 2, base - 1, base):
        c, k, r = fr.value(fr.cfo_tag, f"CY{y}", cik), fr.capex(f"CY{y}", cik), fr.revenue(y, cik)
        if c is not None and k is not None and r:
            fcf_margins.append((c - k) / r)

    I = f"CY{base}Q4I"
    assets, equity, cash = v("Assets", I), v("StockholdersEquity", I), v("CashAndCashEquivalentsAtCarryingValue", I)
    liab = v("Liabilities", I)
    if liab is None and assets is not None and equity is not None:
        liab = assets - equity
    ltd = v("LongTermDebt", I)
    if ltd is None and (v("LongTermDebtNoncurrent", I) is not None or v("LongTermDebtCurrent", I) is not None):
        ltd = (v("LongTermDebtNoncurrent", I) or 0) + (v("LongTermDebtCurrent", I) or 0)
    stb = v("ShortTermBorrowings", I)
    if stb is not None and stb == v("LongTermDebtCurrent", I):
        stb = None   # same amount tagged twice
    debt = (ltd or 0) + (stb or 0)
    has_bs = assets is not None or ltd is not None
    l_a = _div(liab, assets)
    margin = _div(oi, rev)
    capex_s = _div(capex, rev)

    stage, stage_rule = classify_stage(cagr, margin, rules)
    pred, pred_rule, _, sd = classify_predictability(fcf_margins, rules)
    intensity, int_rule = classify_intensity(capex_s, None, rules)
    cap, cap_rule = classify_capital(debt, ebitda, l_a, has_bs, rules)
    return {
        "cik": str(cik).zfill(10), "name": rev_row[1] if rev_row else None,
        "period_start": rev_row[2] if rev_row else None, "period_end": rev_row[3] if rev_row else None,
        "calendar_year": base, "stale": base != year,
        "revenue": rev, "revenue_prior": prior, "revenue_growth": _div(rev, prior) - 1 if prior else None,
        "revenue_cagr": cagr, "cagr_years": cagr_years,
        "gross_profit": gp, "operating_income": oi, "net_income": ni, "ebitda": ebitda,
        "ebitda_basis": (f"EBIT + D&A ({da_basis})" if da is not None and oi is not None
                         else ("EBIT (no D&A tagged)" if oi is not None else None)),
        "gross_margin": _div(gp, rev), "operating_margin": margin, "net_margin": _div(ni, rev),
        "ebitda_margin": _div(ebitda, rev),
        "cfo": cfo, "capex": capex, "fcf": fcf, "fcf_margin": _div(fcf, rev), "fcf_margin_stdev": sd,
        "capex_to_sales": capex_s,
        "assets": assets, "equity": equity, "liabilities": liab, "cash": cash, "debt": debt if has_bs else None,
        "net_debt": debt - (cash or 0) if has_bs else None,
        "roa": _div(ni, assets), "roe": _div(ni, equity) if equity and equity > 0 else None,
        "debt_to_ebitda": _div(debt, ebitda) if ebitda and ebitda > 0 else None,
        "liabilities_to_assets": l_a,
        "traits": {"stage": stage, "predictability": pred, "asset_intensity": intensity, "capital_structure": cap},
        "trait_rules": {"stage": stage_rule, "predictability": pred_rule, "asset_intensity": int_rule,
                        "capital_structure": cap_rule},
    }


def quartiles(xs: list[float]) -> dict:
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return {"q1": None, "median": None, "q3": None, "n": 0}
    if len(xs) == 1:
        return {"q1": xs[0], "median": xs[0], "q3": xs[0], "n": 1}
    q1, med, q3 = statistics.quantiles(xs, n=4, method="inclusive")
    return {"q1": q1, "median": med, "q3": q3, "n": len(xs)}


def benchmarks(companies: list[dict]) -> dict:
    return {m: quartiles([c.get(m) for c in companies]) for m in BENCHMARK_METRICS}


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def parse_traits(spec: str | dict) -> dict:
    """'stage=high growth;asset_intensity=light' or a dict -> {trait: label}."""
    if isinstance(spec, dict):
        d = spec
    else:
        d = dict(p.split("=", 1) for p in (x.strip() for x in spec.split(";")) if p)
    out = {k.strip(): v.strip().lower() for k, v in d.items()}
    bad = [k for k in out if k not in TRAITS]
    if bad:
        raise ValueError(f"unknown trait(s) {bad}; choose from {list(TRAITS)}")
    return out


def sector_id(kind: str, value) -> str:
    if kind == "sector":
        return f"sector-{slug(value)}"
    if kind == "sic":
        return f"sic-{value}"
    if kind == "traits":
        return "traits-" + "-".join(slug(f"{k}-{v}") for k, v in sorted(value.items()))
    return f"list-{slug(value)}"


def build_sector(raw_screen: dict, *, kind: str, value, as_of: str, tickers: list[dict],
                 members: list[str] | None = None, label: str | None = None,
                 limit: int | None = None, rules: dict | None = None,
                 member_sic: dict[str, str] | None = None, taxonomy=None) -> dict:
    """kind sector/sic/list: `members` = CIKs (10-digit). kind traits: `value` = {trait: label}.

    member_sic (CIK -> SIC code) + taxonomy add each company's sector, industry group
    and industry, so the site can re-cut the screen at any level.
    """
    if limit is None:
        limit = SECTOR_LIMIT if kind == "sector" else DEFAULT_LIMIT
    rules = rules or load_rules()
    year = raw_screen["year"]
    fr = Frames(raw_screen)
    by_cik = {}
    for t in tickers:                      # first listed ticker per CIK (the SEC lists the main class first)
        by_cik.setdefault(t["cik"], t["ticker"])
    pool = fr.ciks_with_revenue(year) | fr.ciks_with_revenue(year - 1)
    notes = []
    if kind in ("sector", "sic", "list"):
        wanted = [int(c) for c in (members or [])]
        no_data = [c for c in wanted if c not in pool]
        cands = [c for c in wanted if c in pool]
    elif kind == "traits":
        value = parse_traits(value)
        no_data, cands = [], sorted(pool)
    else:
        raise ValueError(f"kind must be sector, sic, traits or list, not {kind!r}")

    rows = []
    for cik in cands:
        m = company_metrics(fr, cik, year, rules)
        if m is None:
            no_data.append(cik)
            continue
        if kind == "traits" and any(m["traits"][k] != v for k, v in value.items()):
            continue
        m["ticker"] = by_cik.get(m["cik"])
        code = (member_sic or {}).get(m["cik"])
        m["sic"] = code
        c = taxonomy.classify(code) if taxonomy and code else None
        m["classification"] = ({k: c[k] for k in ("sector", "group", "industry")} if c else None)
        rows.append(m)
    no_ticker = [r for r in rows if not r["ticker"]]
    rows = [r for r in rows if r["ticker"]]
    rows.sort(key=lambda r: -r["revenue"])
    over = rows[limit:]
    rows = rows[:limit]
    if no_data:
        notes.append(f"{len(no_data)} listed filer(s) have no {year} or {year - 1} revenue in SEC frames "
                     "(stopped filing, foreign filer, or not tagged) and are left out")
    if no_ticker:
        notes.append(f"{len(no_ticker)} filer(s) without a listed ticker left out")
    if over:
        notes.append(f"kept the {limit} largest by revenue; {len(over)} smaller left out")
    if any(r["stale"] for r in rows):
        notes.append(f"{sum(r['stale'] for r in rows)} company(ies) haven't reported {year} yet; their {year - 1} figures are shown")
    if kind == "traits":
        notes.append("trait screen: asset intensity uses capex / sales only")

    levels = None
    if taxonomy and any(r["classification"] for r in rows):
        # names for the level switch: every group and industry present, with member counts
        levels = {"groups": {}, "industries": {}}
        for r in rows:
            c = taxonomy.classify(r["sic"])
            if not c:
                continue
            levels["groups"].setdefault(c["group"], {"name": c["group_name"], "sector": c["sector"], "count": 0})["count"] += 1
            levels["industries"].setdefault(c["industry"], {"name": c["industry_name"], "group": c["group"], "count": 0})["count"] += 1
    if label is None:
        label = (taxonomy.name(value) if kind == "sector" and taxonomy else
                 f"SIC {value}" if kind == "sic" else
                 " · ".join(v.capitalize() for v in value.values()) if kind == "traits" else value)
    return {
        "schema_version": SCHEMA_VERSION, "stage": "L1.sector",
        "id": sector_id(kind, value), "kind": kind, "label": label,
        "source": {"kind": kind, "value": value}, "as_of": as_of, "year": year,
        "companies": rows, "benchmarks": benchmarks(rows), "levels": levels,
        "excluded": {"no_data": len(no_data), "no_ticker": len(no_ticker), "over_limit": len(over)},
        "notes": notes,
    }
