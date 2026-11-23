"""Apple's own growth case, from its filed sales by product line, checked against similar companies.

    python studies/apple-fy2027/case.py            # prints the case, writes results.json
    python studies/apple-fy2027/case.py --check    # and confirms AAPL's dcf.json carries it

Inside view: each product line (iPhone, Services, Mac, iPad, Wearables) grows at its own five-year
CAGR (FY2021-FY2026), fading in a straight line to 3% over ten years, the engine's fade. Their sum
is the revenue path. Cost of sales follows the mix: products and services each keep their FY2026
cost ratio, so a growing Services share lowers the total ratio.

Cross-check, the course's way round: the price is worked backwards into the growth it implies
(the engine's reverse DCF, details.price_implied_growth), and that growth is judged against this
path and against what similar companies actually grew. The similar companies are the comps peers
in configs/public/assumptions/AAPL/comps.json. They are reported here, not blended into the path.
"""
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

HERE = Path(__file__).parent
DCF_JSON = HERE.parents[1] / "configs" / "public" / "assumptions" / "AAPL" / "dcf.json"
LINES = ("iphone", "services", "mac", "ipad", "wearables")
TERMINAL, FADE_YEARS, YEARS = 0.03, 10, 11


def cagr(series: dict, years: int = 5) -> float:
    ends = sorted(series)
    return (series[ends[-1]] / series[ends[-1 - years]]) ** (1 / years) - 1


def run(inputs: dict) -> dict:
    rev, cos = inputs["facts"]["revenue"], inputs["facts"]["cost_of_sales"]
    val = lambda d: {e: x["value"] for e, x in d.items()}            # noqa: E731
    base_end = max(rev["total"])
    g0 = {k: cagr(val(rev[k])) for k in LINES}
    level = {k: rev[k][base_end]["value"] for k in LINES}
    check = sum(level.values()) - rev["total"][base_end]["value"]
    assert abs(check) < 1e6, f"product lines don't add up to total sales ({check:,.0f})"
    cos_ratio = {"products": cos["products"][base_end]["value"] / rev["products"][base_end]["value"],
                 "services": cos["services"][base_end]["value"] / rev["services"][base_end]["value"]}
    growth, cogs, services_share, prev = [], [], [], sum(level.values())
    for t in range(YEARS):
        for k in LINES:
            level[k] *= 1 + g0[k] - min(t, FADE_YEARS) * (g0[k] - TERMINAL) / FADE_YEARS
        total = sum(level.values())
        s = level["services"] / total
        growth.append(total / prev - 1)
        services_share.append(s)
        cogs.append((1 - s) * cos_ratio["products"] + s * cos_ratio["services"])
        prev = total
    peers = {t: cagr(r) for t, r in inputs["similar_companies"]["revenue"].items()}
    similar = statistics.median(peers.values())
    r = lambda x: round(x, 4)                                          # noqa: E731
    return {
        "base_year_end": base_end,
        "line_cagr_5y": {k: r(v) for k, v in g0.items()},
        "cost_ratio_fy2026": {k: r(v) for k, v in cos_ratio.items()},
        "path_growth": [r(g) for g in growth],
        "cogs_pct_revenue": [r(c) for c in cogs],
        "services_share": [r(s) for s in services_share],
        "similar_companies_cagr_5y": {t: r(v) for t, v in sorted(peers.items())},
        "similar_companies_median": r(similar),
    }


def dcf_inputs(res: dict) -> dict:
    """What AAPL's dcf.json must carry for the engine to run this case."""
    g = res["path_growth"]
    return {"revenue_growth": g[0], "growth_adjust": [round(x - g[0], 4) for x in g],
            "cost_pct_revenue": {"cogs": res["cogs_pct_revenue"]}}


def check(res: dict) -> list[str]:
    fc = json.loads(DCF_JSON.read_text())["forecast"]
    want = dcf_inputs(res)
    return [f"{k}: dcf.json has {fc.get(k)!r}, the case gives {v!r}" for k, v in want.items() if fc.get(k) != v]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    res = run(json.loads((HERE / "inputs.json").read_text()))
    (HERE / "results.json").write_text(json.dumps(res, indent=1) + "\n")
    print("five-year CAGR by line:", ", ".join(f"{k} {v:.1%}" for k, v in res["line_cagr_5y"].items()))
    print("similar companies:", ", ".join(f"{k} {v:.1%}" for k, v in res["similar_companies_cagr_5y"].items()),
          f"-> median {res['similar_companies_median']:.1%}")
    print(f"{'year':>4} {'growth':>7} {'services':>9} {'cogs':>7}")
    for t, (g, s, c) in enumerate(zip(res["path_growth"], res["services_share"], res["cogs_pct_revenue"])):
        print(f"{t + 1:>4} {g:>7.1%} {s:>9.1%} {c:>7.1%}")
    if args.check:
        bad = check(res)
        print("\n".join(bad) if bad else "dcf.json carries this case")
        raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
