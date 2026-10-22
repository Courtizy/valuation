"""Course reasonableness checks on a valuation's inputs and outputs (MBA 789 notes).

Each check returns {"key", "label", "value", "status", "note"} with status
"good" | "warning" | "info", so a page can show it with an icon and a label.

Terminal growth (how fast does the firm grow against a 4-6% nominal economy?)
    grows with the economy   3.5% to 4.5% (about 1 point of the economy's growth comes from new firms)
    slower                   2.4% to 3.5%
    flat real growth         1.5% to 2.4% (in line with inflation)
    negative real growth     0% to 1.5%
    rapid decline            below 0%
    faster than the economy  above 4.5%: never, so it is flagged
When to start the terminal value
    growth in the terminal year should be at steady state, 5% or below
    the terminal value is usually 50% to 75% of EV in a 10-year projection
Exit multiple
    the EV/EBITDA the terminal value implies, against the public comps' average:
    exit multiples are generally too high, especially in fast-growing industries

Synthetic rating: when interest / debt can't be measured, the cost of debt is the
risk-free rate plus the spread for the rating that the interest coverage
(EBIT / interest) suggests. The spreads below are illustrative, in the shape of
Damodaran's large-firm coverage table; set cost_of_capital.rating_spreads to use
current ones.

Lasting cost synergies (Week 9 synergy review): cost synergies only add value forever
while they bring a firm up to normal profits. If terminal ROIC is below the terminal
WACC, the share that can last is the cost cut (after tax) needed to close the gap:
    share = min(1, (WACC_T - ROIC_T) x invested capital_T / (annual cost synergies x (1 - tax)))
and the range runs from 0 to that share. At or above normal profits it is 0.
"""
from __future__ import annotations

ECONOMY_CAP = 0.045
STEADY_GROWTH_MAX = 0.05
TV_SHARE_RANGE = (0.50, 0.75)
EXIT_MULTIPLE_TOLERANCE = 0.25     # implied exit multiple within 25% of the comps average reads as consistent

GROWTH_BANDS = [  # (lower bound, label), checked from the top
    (ECONOMY_CAP, "faster than the economy"),
    (0.035, "grows with the economy"),
    (0.024, "slower than the economy"),
    (0.015, "flat real growth (in line with inflation)"),
    (0.0, "negative real growth"),
    (float("-inf"), "rapid decline"),
]

# (minimum EBIT / interest, rating, spread over the risk-free rate)
RATING_TABLE = [
    (8.5, "AAA", 0.0060), (6.5, "AA", 0.0080), (5.5, "A+", 0.0100), (4.25, "A", 0.0110),
    (3.0, "A-", 0.0125), (2.5, "BBB", 0.0160), (2.25, "BB+", 0.0200), (2.0, "BB", 0.0240),
    (1.75, "B+", 0.0300), (1.5, "B", 0.0350), (1.25, "B-", 0.0430), (0.8, "CCC", 0.0800),
    (0.65, "CC", 0.1000), (0.2, "C", 0.1300), (float("-inf"), "D", 0.1700),
]


def _check(key, label, value, status, note):
    return {"key": key, "label": label, "value": value, "status": status, "note": note}


def growth_band(g: float) -> str:
    for lo, label in GROWTH_BANDS:
        if g >= lo:
            return label
    return GROWTH_BANDS[-1][1]


def terminal_checks(*, terminal_growth: float, last_year_growth: float | None, tv_share: float | None,
                    exit_multiple: float | None = None, comps_multiple: float | None = None) -> list[dict]:
    band = growth_band(terminal_growth)
    out = [_check("terminal_growth", "Terminal growth", terminal_growth,
                  "warning" if terminal_growth > ECONOMY_CAP else "good",
                  f"{band}: no firm grows faster than the economy forever (cap {ECONOMY_CAP:.1%})"
                  if terminal_growth > ECONOMY_CAP else f"{band}")]
    if last_year_growth is not None:
        ok = last_year_growth <= STEADY_GROWTH_MAX
        out.append(_check("steady_state", "Growth when the terminal value starts", last_year_growth,
                          "good" if ok else "warning",
                          "at steady state (5% or below)" if ok else
                          "still above 5%: extend the forecast until growth settles"))
    if tv_share is not None:
        lo, hi = TV_SHARE_RANGE
        ok = lo <= tv_share <= hi
        out.append(_check("tv_share", "Terminal value share of EV", tv_share, "good" if ok else "warning",
                          f"within the usual {lo:.0%}-{hi:.0%}" if ok else
                          (f"above {hi:.0%}: most of the value sits beyond the forecast" if tv_share > hi
                           else f"below {lo:.0%}: check whether the terminal year is too pessimistic")))
    ex = exit_multiple_check(exit_multiple, comps_multiple)
    if ex:
        out.append(ex)
    return out


def exit_multiple_check(exit_multiple: float | None, comps_multiple: float | None) -> dict | None:
    if exit_multiple is not None and comps_multiple:
        gap = exit_multiple / comps_multiple - 1
        ok = abs(gap) <= EXIT_MULTIPLE_TOLERANCE
        why = "" if ok else (": exit multiples are usually too high; check the terminal inputs" if gap > 0
                             else ": below where peers trade today")
        return _check("exit_multiple", "Implied exit EV/EBITDA vs public comps", exit_multiple,
                      "good" if ok else "warning",
                      f"{exit_multiple:.1f}x against a comps average of {comps_multiple:.1f}x ({gap:+.0%}){why}")
    return None


def synthetic_rating(ebit: float | None, interest: float | None, table: list | None = None) -> dict | None:
    """Rating and spread from interest coverage; None when it can't be measured."""
    if ebit is None or not interest or interest <= 0:
        return None
    cov = ebit / interest
    for lo, rating, spread in table or RATING_TABLE:
        if cov >= lo:
            return {"coverage": cov, "rating": rating, "spread": spread,
                    "investment_grade": rating in ("AAA", "AA", "A+", "A", "A-", "BBB")}
    return None


def lasting_cost_share(*, roic_terminal: float | None, wacc_terminal: float, invested_capital: float | None,
                       annual_cost: float, tax_rate: float) -> dict | None:
    """Share of cost synergies whose benefit can last forever (the normal-profit test)."""
    if roic_terminal is None or not invested_capital or not annual_cost:
        return None
    gap = wacc_terminal - roic_terminal
    if gap <= 0:
        return {"share": 0.0, "range": [0.0, 0.0], "basis": "roic",
                "note": f"terminal ROIC {roic_terminal:.1%} is at or above the terminal WACC {wacc_terminal:.1%}: "
                        "profits are normal or better, so no cost synergy lasts forever"}
    share = min(1.0, gap * invested_capital / (annual_cost * (1 - tax_rate)))
    return {"share": share, "range": [0.0, share], "basis": "roic",
            "note": f"terminal ROIC {roic_terminal:.1%} is below the terminal WACC {wacc_terminal:.1%}: "
                    f"up to {share:.1%} of the cost synergies can last, the part that brings profits up to normal"}


def margin_vs_peers(target_margin: float | None, peer_margin: float | None) -> dict | None:
    """The second normal-profit test: EBITDA / sales against the public comps' average."""
    if target_margin is None or peer_margin is None:
        return None
    above = target_margin >= peer_margin
    return {"target": target_margin, "peers": peer_margin, "above": above,
            "note": f"EBITDA margin {target_margin:.1%} vs peers' {peer_margin:.1%}: "
                    + ("at or above normal, so cost synergies shouldn't last forever" if above
                       else "below normal, so part of a cost cut can last")}
