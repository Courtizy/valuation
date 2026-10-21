"""Aswath Damodaran's public datasets (NYU Stern): US industry betas and the implied equity risk premium.

  Betas.html     pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/Betas.html
                 one row per industry: firms, levered beta, D/E, tax rate, unlevered beta,
                 cash / firm value, unlevered beta corrected for cash, ...
  histimpl.html  .../datafile/histimpl.html
                 one row per year: S&P 500, T-bond rate, implied ERP (FCFE), ...

Updated each January. Free and published for teaching; cited wherever a figure is used.
These replace the illustrative sector betas when no price-based beta may be shown
(showcase mode) and the flat 5% ERP of the DCF default case. Parsed by column name,
so a reordered or added column doesn't break it.
"""
from __future__ import annotations

import re
from html.parser import HTMLParser

BETAS_URL = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/Betas.html"
ERP_URL = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/histimpl.html"


def norm(name: str) -> str:
    """Industry names carry stray double spaces ("Beverage  (Soft)"); compare them collapsed."""
    return re.sub(r"\s+", " ", name or "").strip()


class _Tables(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None
        self.text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(norm("".join(self._cell)))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if any(self._row):
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)
        self.text.append(data)


def _parse(html: str) -> tuple[list[list[str]], str]:
    p = _Tables()
    p.feed(html)
    return p.rows, norm(" ".join(p.text))


def _num(s: str) -> float | None:
    s = (s or "").replace(",", "").strip()
    if not s or s in ("NA", "#N/A", "-"):
        return None
    pct = s.endswith("%")
    try:
        v = float(s.rstrip("%"))
    except ValueError:
        return None
    return v / 100 if pct else v


def _updated(text: str) -> str | None:
    m = re.search(r"(?:Date of Analysis|Updated?)\W+(?:Data used is as of\s+)?([A-Z][a-z]+ \d{4})", text)
    return m.group(1) if m else None


def _table(rows: list[list[str]], first_header: str) -> tuple[list[str], list[list[str]]]:
    for i, r in enumerate(rows):
        if r and norm(r[0]).lower() == first_header.lower():
            return [norm(h).lower() for h in r], rows[i + 1:]
    raise ValueError(f"no table with a '{first_header}' header")


def _col(header: list[str], *names: str) -> int | None:
    for n in names:
        if n.lower() in header:
            return header.index(n.lower())
    return None


def parse_betas(html: str) -> dict:
    """{updated, source, industries: {name: {firms, beta, debt_to_equity, tax_rate, beta_unlevered,
    cash_to_firm_value, beta_unlevered_cash_corrected}}}."""
    rows, text = _parse(html)
    header, body = _table(rows, "Industry Name")
    cols = {"firms": _col(header, "number of firms"), "beta": _col(header, "beta"),
            "debt_to_equity": _col(header, "d/e ratio"), "tax_rate": _col(header, "effective tax rate"),
            "beta_unlevered": _col(header, "unlevered beta"), "cash_to_firm_value": _col(header, "cash/firm value"),
            "beta_unlevered_cash_corrected": _col(header, "unlevered beta corrected for cash")}
    if cols["beta_unlevered"] is None or cols["beta"] is None:
        raise ValueError(f"betas table is missing its beta columns: {header}")
    out = {}
    for r in body:
        if len(r) < len(header) or not r[0]:
            continue
        rec = {k: (_num(r[i]) if i is not None else None) for k, i in cols.items()}
        if rec["beta_unlevered"] is None:
            continue
        rec["firms"] = int(rec["firms"]) if rec["firms"] is not None else None
        out[norm(r[0])] = rec
    if not out:
        raise ValueError("betas table has no rows")
    return {"updated": _updated(text), "source": BETAS_URL, "industries": out}


def parse_erp(html: str) -> dict:
    """The latest year's implied ERP: {year, value, tbond_rate, updated, source}."""
    rows, text = _parse(html)
    header, body = _table(rows, "Year")
    i_erp = next((i for i, h in enumerate(header) if h.startswith("implied erp")), None)
    i_tb = _col(header, "t.bond rate")
    if i_erp is None:
        raise ValueError(f"ERP table has no 'Implied ERP' column: {header}")
    years = [(int(r[0]), _num(r[i_erp]), _num(r[i_tb]) if i_tb is not None else None)
             for r in body if r and r[0].isdigit() and len(r) > i_erp and _num(r[i_erp]) is not None]
    if not years:
        raise ValueError("ERP table has no rows")
    year, erp, tb = max(years)
    return {"year": year, "value": erp, "tbond_rate": tb, "updated": _updated(text), "source": ERP_URL}
