"""Freeze Apple's filed sales by product line and its product / services cost of sales into inputs.json.

    SEC_USER_AGENT="Your Name you@example.com" python studies/apple-fy2027/build_inputs.py
    python studies/apple-fy2027/build_inputs.py --xbrl FY2026=path/aapl-20260926_htm.xml FY2023=path/...   # offline

The product lines are dimensional facts (ProductOrServiceAxis), which SEC company facts leave out,
so they come from each 10-K's XBRL instance. The FY2026 10-K covers FY2024-FY2026 and the FY2023
10-K covers FY2021-FY2023. Each value keeps the accession it came from.
"""
from __future__ import annotations

import argparse
import json
import os
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

CIK = "320193"
FILINGS = {   # 10-K -> (accession, instance document, filed)
    "FY2026": ("0000320193-26-000026", "aapl-20260926_htm.xml", "2026-11-03"),
    "FY2023": ("0000320193-23-000106", "aapl-20230930_htm.xml", "2023-11-03"),
}
LINES = {"aapl:IPhoneMember": "iphone", "aapl:MacMember": "mac", "aapl:IPadMember": "ipad",
         "aapl:WearablesHomeandAccessoriesMember": "wearables", "us-gaap:ServiceMember": "services",
         "us-gaap:ProductMember": "products", None: "total"}
TAGS = {"RevenueFromContractWithCustomerExcludingAssessedTax": "revenue", "CostOfGoodsAndServicesSold": "cost_of_sales"}
X = "{http://www.xbrl.org/2003/instance}"
DIM = "{http://xbrl.org/2006/xbrldi}explicitMember"


def facts(xml: bytes, accession: str) -> list[dict]:
    root = ET.fromstring(xml)
    ctx = {}
    for c in root.findall(f"{X}context"):
        per = c.find(f"{X}period")
        start, end = per.find(f"{X}startDate"), per.find(f"{X}endDate")
        members = [m.text for m in c.iter(DIM)]
        if start is None or len(members) > 1:
            continue
        ctx[c.get("id")] = (start.text, end.text, members[0] if members else None)
    out = []
    for el in root:
        tag = el.tag.split("}")[-1]
        c = ctx.get(el.get("contextRef"))
        if tag not in TAGS or not c or c[2] not in LINES:
            continue
        start, end, member = c
        if int(end[:4]) * 12 + int(end[5:7]) - int(start[:4]) * 12 - int(start[5:7]) < 11:   # annual only
            continue
        out.append({"line": LINES[member], "item": TAGS[tag], "end": end, "value": float(el.text),
                    "accession": accession})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--xbrl", nargs="*", default=[], help="FYxxxx=path to a saved instance document")
    args = ap.parse_args()
    local = dict(a.split("=", 1) for a in args.xbrl)
    rows = []
    for fy, (acc, doc, _) in FILINGS.items():
        if fy in local:
            xml = Path(local[fy]).read_bytes()
        else:
            ua = os.environ.get("SEC_USER_AGENT") or ap.error("set SEC_USER_AGENT (SEC asks for a contact)")
            url = f"https://www.sec.gov/Archives/edgar/data/{CIK}/{acc.replace('-', '')}/{doc}"
            xml = urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": ua}), timeout=60).read()
        rows += facts(xml, acc)
    data: dict = {}
    for r in sorted(rows, key=lambda r: (r["item"], r["line"], r["end"], r["accession"])):
        slot = data.setdefault(r["item"], {}).setdefault(r["line"], {})
        if r["end"] not in slot or r["accession"] > slot[r["end"]]["accession"]:   # latest 10-K wins
            slot[r["end"]] = {"value": r["value"], "accession": r["accession"]}
    out = {"company": "Apple Inc.", "cik": CIK, "unit": "USD",
           "filings": {fy: {"accession": a, "document": d, "filed": f} for fy, (a, d, f) in FILINGS.items()},
           "facts": data}
    path = Path(__file__).with_name("inputs.json")
    path.write_text(json.dumps(out, indent=1) + "\n")
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
# The similar_companies block is added from the engine's own company detail, so the peers' revenue
# goes through the same normalization as every company on the site:
#     for t in WDC FTNT NTAP STX PANW DELL; do python -m valuation run $t --as-of 2026-11-23 --stop-after L1; done
# then each one's views.annual revenue (last six fiscal years) is copied in.
