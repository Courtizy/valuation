"""Discount rates: CAPM cost of equity, beta levering, WACC before and in the terminal year.

Logic
-----
1. Unlever the observed equity beta at the current market debt-to-equity:
       beta_u = beta_e / (1 + (1 - t) * D/E_current)
2. Relever at the target (long-run) debt-to-equity:
       beta_TL = beta_u * (1 + (1 - t) * D/E_target)
3. Weights from the target ratio:  %E = 1 / (1 + D/E),  %D = D/E / (1 + D/E)
4. Pre-terminal WACC uses today's long-term government rate:
       r_E = r_f + beta_TL * MRP
       WACC = r_E * %E + r_D * (1 - t) * %D
5. Terminal-year WACC uses a normalized long-run government rate r_f,T and
   keeps today's credit spread:
       r_E,T = r_f,T + beta_TL * MRP
       r_D,T = r_f,T + (r_D - r_f)
       WACC_T = r_E,T * %E + r_D,T * (1 - t) * %D
   When no terminal rate is given, r_f,T = r_f and the two WACCs match.
"""
from __future__ import annotations


def capm(risk_free: float, beta: float, mrp: float) -> float:
    return risk_free + beta * mrp


def unlever_beta(beta_equity: float, debt_to_equity: float, tax_rate: float) -> float:
    return beta_equity / (1 + (1 - tax_rate) * debt_to_equity)


def relever_beta(beta_unlevered: float, debt_to_equity: float, tax_rate: float) -> float:
    return beta_unlevered * (1 + (1 - tax_rate) * debt_to_equity)


def wacc(cost_of_equity: float, pre_tax_cost_of_debt: float, tax_rate: float, debt_to_equity: float) -> float:
    we, wd = 1 / (1 + debt_to_equity), debt_to_equity / (1 + debt_to_equity)
    return cost_of_equity * we + pre_tax_cost_of_debt * (1 - tax_rate) * wd


def discount_rates(*, risk_free: float, pre_tax_cost_of_debt: float, beta: float, equity_risk_premium: float,
                   tax_rate: float, current_debt_to_equity: float, target_debt_to_equity: float | None = None,
                   risk_free_terminal: float | None = None) -> dict:
    """All the course's discount-rate figures. Debt-to-equity uses market equity."""
    target = current_debt_to_equity if target_debt_to_equity is None else target_debt_to_equity
    rf_t = risk_free if risk_free_terminal is None else risk_free_terminal
    beta_u = unlever_beta(beta, current_debt_to_equity, tax_rate)
    beta_tl = relever_beta(beta_u, target, tax_rate)
    re = capm(risk_free, beta_tl, equity_risk_premium)
    re_t = capm(rf_t, beta_tl, equity_risk_premium)
    rd_t = rf_t + pre_tax_cost_of_debt - risk_free
    return {
        "beta_levered_observed": beta,
        "beta_unlevered": beta_u,
        "beta_relevered": beta_tl,
        "current_debt_to_equity": current_debt_to_equity,
        "target_debt_to_equity": target,
        "equity_weight": 1 / (1 + target),
        "debt_weight": target / (1 + target),
        "cost_of_equity": re,
        "wacc": wacc(re, pre_tax_cost_of_debt, tax_rate, target),
        "risk_free_terminal": rf_t,
        "cost_of_equity_terminal": re_t,
        "pre_tax_cost_of_debt_terminal": rd_t,
        "wacc_terminal": wacc(re_t, rd_t, tax_rate, target),
    }
