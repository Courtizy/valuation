"""Diluted shares by the treasury stock method.

In-the-money options (strike below the share price) are assumed exercised;
the exercise proceeds buy back shares at the current price:

    diluted = basic + in-the-money options - proceeds / price
"""
from __future__ import annotations


def treasury_stock_method(basic_shares: float, price: float, tranches: list | None = None) -> dict:
    """`tranches`: [(options_outstanding, weighted_average_strike), ...]."""
    if price <= 0:
        raise ValueError("price must be positive")
    itm = proceeds = 0.0
    for n, strike in tranches or []:
        if price > strike:
            itm += n
            proceeds += n * strike
    repurchased = proceeds / price
    return {"basic": basic_shares, "in_the_money_options": itm, "exercise_proceeds": proceeds,
            "shares_repurchased": repurchased, "diluted": basic_shares + itm - repurchased}
