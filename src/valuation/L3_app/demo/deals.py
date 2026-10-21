"""A synthetic deal list for DEMO's transaction comps: industrial machinery takeovers, written
the way an SDC Platinum export pastes from Excel (tab-separated, $ millions), five marked best."""
from __future__ import annotations

import random

HEADERS = ["Year Announced", "Target Name", "Acquiror Name", "Enterprise Value evaluated at offer price ($mil)",
           "Target Net Sales LTM ($mil)", "Target EBITDA LTM ($mil)", "Price Per Share",
           "Target Share Price 1 Week Prior to Announcement", "Target Share Price 4 Weeks Prior to Announcement",
           "Target Primary SIC Code", "Net Debt ($ mil)", "Shares Out. (mil)", "Best"]
NAMES = ["Arbor", "Brightline", "Cobalt", "Delta Forge", "Eastgate", "Fulcrum", "Granite", "Harbor", "Ironwood", "Juniper",
         "Keystone", "Lakeside", "Meridian", "Northfield", "Oakmont", "Pinnacle", "Quarry", "Ridgeway", "Summit",
         "Tidewater", "Union Valve", "Vantage", "Westbrook", "Yardley"]
BUYERS = ["Atlas Industrial", "Beacon Capital", "Crown Holdings", "Dynamo Group", "Everest Partners", "Foundry Corp"]


def demo_deal_list(seed: int = 11) -> str:
    rng = random.Random(seed)
    rows = ["\t".join(HEADERS)]
    for i, name in enumerate(NAMES):
        sales = round(rng.uniform(400, 3200), 1)
        margin = rng.uniform(0.10, 0.22)
        ebitda = round(sales * margin, 1)
        pre_ev = ebitda * rng.uniform(7.5, 13.0)
        net_debt = round(pre_ev * rng.uniform(-0.05, 0.35), 1)
        shares = round(rng.uniform(20, 160), 2)
        p1 = round((pre_ev - net_debt) / shares, 2)
        p4 = round(p1 * rng.uniform(0.92, 1.05), 2)
        offer = round(p1 * (1 + rng.uniform(0.12, 0.55)), 2)
        ev = round(offer * shares + net_debt, 1)
        rows.append("\t".join(str(x) for x in [2017 + i % 9, f"{name} Industries (synthetic)", rng.choice(BUYERS) + " (synthetic)",
                                               ev, sales, ebitda, offer, p1, p4, 3569, net_debt, shares,
                                               "yes" if i in (2, 5, 9, 14, 20) else ""]))
    return "\n".join(rows) + "\n"
