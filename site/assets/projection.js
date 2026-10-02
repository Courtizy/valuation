// Three-statement projection: a line-for-line port of core/projection.py.
// The Python module is the reference; tests/test_site_projection.py runs both
// on the same inputs and requires identical results. Change them together.

export const BASE_ITEMS = [
  "revenue", "cogs", "sga", "rnd", "other_opex", "depreciation", "amortization",
  "interest_expense", "interest_income", "income_taxes", "net_income",
  "cash", "receivables", "inventory", "other_current_assets", "fixed_assets",
  "payables", "accrued", "short_term_debt", "long_term_debt", "other_lt_liabilities", "equity",
];
const COST_LINES = ["cogs", "sga", "rnd", "other_opex"];
const WCR_ASSETS = ["receivables", "inventory", "other_current_assets"];
const WCR_LIABS = ["payables", "accrued"];
const MAX_ITER = 200, TOL = 1e-9;

export class ProjectionError extends Error {}

const isNil = (x) => x === null || x === undefined;
const ratio = (num, den) => (den ? (num || 0) / den : 0);
const sum = (row, keys) => keys.reduce((s, k) => s + row[k], 0);

function perYear(x, t, dflt = 0) {
  if (isNil(x)) return dflt;
  if (Array.isArray(x)) return t < x.length ? x[t] : (x.length ? x[x.length - 1] : dflt);
  return x;
}

export function revenuePath(driver, baseRevenue, years) {
  const m = driver.method;
  let rates;
  if (m === "values") {
    if (driver.values.length < years) throw new ProjectionError("revenue values shorter than the horizon");
    return driver.values.slice(0, years);
  } else if (m === "growth") {
    rates = [...driver.rates];
  } else if (m === "fade") {
    const g0 = driver.g0;
    if (!isNil(driver.adjust)) {
      rates = Array.from({ length: years }, (_, t) => g0 + perYear(driver.adjust, t));
    } else {
      const gt = driver.g_terminal, n = driver.fade_years;
      rates = Array.from({ length: years }, (_, t) => g0 - Math.min(t, n) * (g0 - gt) / n);
    }
  } else {
    throw new ProjectionError(`unknown revenue method ${m}`);
  }
  while (rates.length < years) rates.push(rates[rates.length - 1]);
  const out = [];
  let s = baseRevenue;
  for (const g of rates.slice(0, years)) { s = s * (1 + g); out.push(s); }
  return out;
}

class Ctx {
  constructor(base, drivers) { this.b = base; this.d = drivers; }
  drv(name) { return this.d[name] || { method: "same_as_base" }; }
  pctOfSales(name, dr, sales, t) {
    let value = dr.value;
    if (isNil(value)) value = ratio(this.b[name], this.b.revenue);
    return perYear(value, t) * sales * (1 + perYear(dr.adjust, t));
  }
}

function flowLine(ctx, name, row, prev, t) {
  const dr = ctx.drv(name), m = dr.method;
  if (m === "pct_of_sales") return ctx.pctOfSales(name, dr, row.revenue, t);
  if (m === "same_as_base") return ctx.b[name] || 0;
  if (m === "pct_of_fixed_assets") {
    let v = dr.value;
    if (isNil(v)) v = ratio(ctx.b[name], ctx.b.fixed_assets);
    return perYear(v, t) * prev.fixed_assets;
  }
  if (m === "values") return perYear(dr.values, t);
  throw new ProjectionError(`${name}: unknown method ${m}`);
}

function balanceLine(ctx, name, row, prev, t) {
  const dr = ctx.drv(name), m = dr.method;
  const days = ctx.d.days_in_year ?? 365;
  if (m === "same_as_base") return prev[name];
  if (m === "pct_of_sales") return ctx.pctOfSales(name, dr, row.revenue, t);
  if (m === "days") return perYear(dr.value, t) * (name === "inventory" ? row.cogs : row.revenue) / days;
  if (m === "turnover") return row.cogs / perYear(dr.value, t);
  if (m === "days_purchases") return perYear(dr.value, t) * (row.cogs + row.inventory - prev.inventory) / days;
  if (m === "schedule") return perYear(dr.values, t);
  throw new ProjectionError(`${name}: unknown method ${m}`);
}

function opening(base) {
  const row = {};
  for (const k of BASE_ITEMS) row[k] = base[k] || 0;
  row.revolver = 0;
  row.wcr = sum(row, WCR_ASSETS) - sum(row, WCR_LIABS);
  return row;
}

function baseEbt(b) {
  return !isNil(b.net_income) && !isNil(b.income_taxes) ? b.net_income + b.income_taxes : 0;
}

function incomeStatement(ctx, row, prev, t, interest) {
  const d = ctx.d;
  for (const name of COST_LINES) row[name] = (name in d || ctx.b[name]) ? flowLine(ctx, name, row, prev, t) : 0;
  row.depreciation = flowLine(ctx, "depreciation", row, prev, t);
  row.amortization = ("amortization" in d || ctx.b.amortization) ? flowLine(ctx, "amortization", row, prev, t) : 0;
  const costs = sum(row, COST_LINES);
  const da = row.depreciation + row.amortization;
  row.ebitda = (d.costs_include_da ?? true) ? row.revenue - costs + da : row.revenue - costs;
  row.ebit = row.ebitda - da;
  [row.interest_expense, row.interest_income] = interest;
  row.nonrecurring = perYear(d.nonrecurring, t);
  row.ebt = row.ebit - row.interest_expense + row.interest_income - row.nonrecurring;
  row.tax_rate = perYear(d.tax_rate, t, ratio(ctx.b.income_taxes, baseEbt(ctx.b)));
  row.income_taxes = row.ebt * row.tax_rate;
  row.net_income = row.ebt - row.income_taxes;
}

function interestFor(ctx, row, prev, t) {
  const dr = ctx.d.interest || { method: "same_as_base" }, m = dr.method;
  if (m === "same_as_base") return [ctx.b.interest_expense || 0, ctx.b.interest_income || 0];
  if (m === "pct_of_sales") {
    let v = dr.value;
    if (isNil(v)) v = ratio((ctx.b.interest_expense || 0) - (ctx.b.interest_income || 0), ctx.b.revenue);
    return [perYear(v, t) * row.revenue, 0];
  }
  if (m === "rate_on_debt") {
    const debtPrev = prev.short_term_debt + prev.long_term_debt + prev.revolver;
    let debt = debtPrev, cash = prev.cash;
    if ((dr.basis || "beginning") === "average" && "short_term_debt" in row) {
      debt = (debtPrev + row.short_term_debt + row.long_term_debt + row.revolver) / 2;
      cash = (prev.cash + row.cash) / 2;
    }
    return [perYear(dr.rate, t) * debt, perYear(dr.cash_rate ?? 0, t) * cash];
  }
  throw new ProjectionError(`interest: unknown method ${m}`);
}

function balanceSheet(ctx, row, prev, t) {
  const d = ctx.d;
  const capexDr = d.capex || { method: "replacement" };
  let capex;
  if (capexDr.method === "replacement") capex = row.depreciation + row.amortization;
  else capex = capexDr.method !== "same_as_base" ? flowLine(ctx, "capex", row, prev, t) : (ctx.b.capex || 0);
  const faDr = d.fixed_assets || { method: "roll_forward" };
  if (faDr.method === "roll_forward") {
    row.fixed_assets = prev.fixed_assets + capex - row.depreciation - row.amortization;
    row.capex = capex;
  } else {
    row.fixed_assets = balanceLine(ctx, "fixed_assets", row, prev, t);
    row.capex = row.fixed_assets - prev.fixed_assets + row.depreciation + row.amortization;
  }

  const nwc = d.nwc || { method: "items" };
  if (nwc.method === "incremental") {
    for (const k of [...WCR_ASSETS, ...WCR_LIABS]) row[k] = prev[k];
    row.wcr = prev.wcr + perYear(nwc.ratio, t) * (row.revenue - prev.revenue);
    row.other_current_assets += row.wcr - prev.wcr;
  } else {
    for (const k of ["inventory", ...[...WCR_ASSETS, ...WCR_LIABS].filter((x) => x !== "inventory")]) {
      row[k] = balanceLine(ctx, k, row, prev, t);
    }
    row.wcr = sum(row, WCR_ASSETS) - sum(row, WCR_LIABS);
  }

  for (const k of ["short_term_debt", "long_term_debt", "other_lt_liabilities"]) row[k] = balanceLine(ctx, k, row, prev, t);

  const payout = perYear((d.dividends || {}).payout, t);
  row.dividends = Math.max(row.net_income, 0) * payout;
  const plug = d.plug || "equity";
  const cashDr = d.cash || { method: "same_as_base" };

  if (plug === "equity") {
    row.cash = balanceLine(ctx, "cash", row, prev, t);
    row.revolver = prev.revolver;
    const assets = row.cash + sum(row, WCR_ASSETS) + row.fixed_assets;
    const liabs = sum(row, WCR_LIABS) + row.short_term_debt + row.revolver + row.long_term_debt + row.other_lt_liabilities;
    row.equity = assets - liabs;
  } else if (plug === "cash" || plug === "revolver") {
    row.equity = prev.equity + row.net_income - row.dividends;
    const nonCash = sum(row, WCR_ASSETS) + row.fixed_assets;
    const funding = sum(row, WCR_LIABS) + row.short_term_debt + row.long_term_debt + row.other_lt_liabilities + row.equity;
    let floor = 0;
    if (plug === "revolver" || cashDr.method === "min") {
      floor = cashDr.method !== "min" ? balanceLine(ctx, "cash", row, prev, t) : perYear(cashDr.value, t);
    }
    const cash = funding - nonCash;
    if (cash < floor) { row.revolver = floor - cash; row.cash = floor; } else { row.revolver = 0; row.cash = cash; }
  } else {
    throw new ProjectionError(`unknown plug ${plug}`);
  }
}

function cashFlow(row, prev) {
  const dWcr = row.wcr - prev.wcr;
  const dOltl = row.other_lt_liabilities - prev.other_lt_liabilities;
  const cfo = row.net_income + row.depreciation + row.amortization - dWcr + dOltl;
  const cfi = -row.capex;
  const dDebt = row.short_term_debt + row.long_term_debt + row.revolver - prev.short_term_debt - prev.long_term_debt - prev.revolver;
  const equityOther = row.equity - prev.equity - row.net_income + row.dividends;
  const cff = dDebt - row.dividends + equityOther;
  return {
    cfo, cfi, cff, change_in_debt: dDebt, equity_issued_or_plug: equityOther,
    change_in_cash: row.cash - prev.cash,
    ties: Math.abs(cfo + cfi + cff - (row.cash - prev.cash)) < 1e-6 * Math.max(1, Math.abs(row.revenue)),
  };
}

function managerial(row) {
  return {
    cash: row.cash, wcr: row.wcr, fixed_assets: row.fixed_assets,
    invested_capital: row.cash + row.wcr + row.fixed_assets,
    short_term_debt: row.short_term_debt + row.revolver,
    long_term_financing: row.long_term_debt + row.other_lt_liabilities,
    equity: row.equity,
    capital_employed: row.short_term_debt + row.revolver + row.long_term_debt + row.other_lt_liabilities + row.equity,
  };
}

function fcf(row, prev, d, t) {
  const tax = row.tax_rate;
  const deductible = d.amortization_tax_deductible ?? 1;
  const dNwc = row.wcr - prev.wcr;
  const provisions = perYear(d.provisions, t);
  return {
    nopat: row.ebit * (1 - tax), ebitda: row.ebitda, depreciation: row.depreciation,
    amortization: row.amortization, capex: row.capex, change_in_nwc: dNwc, provisions,
    fcf: row.ebitda * (1 - tax) + row.depreciation * tax + row.amortization * tax * deductible - row.capex - dNwc - provisions,
  };
}

export function project(base, drivers, years) {
  if (!base.revenue) throw new ProjectionError("base revenue is required");
  if (!("revenue" in drivers)) throw new ProjectionError("a revenue driver is required");
  const ctx = new Ctx(base, drivers);
  const sales = revenuePath(drivers.revenue, base.revenue, years);
  let prev = opening(base);
  const out = [];
  const iterative = (drivers.interest || {}).basis === "average";
  for (let t = 0; t < years; t++) {
    const row = { year: t + 1, revenue: sales[t] };
    incomeStatement(ctx, row, prev, t, interestFor(ctx, row, prev, t));
    balanceSheet(ctx, row, prev, t);
    if (iterative) {
      let converged = false;
      for (let i = 0; i < MAX_ITER; i++) {
        const ie = interestFor(ctx, row, prev, t);
        const before = row.net_income;
        incomeStatement(ctx, row, prev, t, ie);
        balanceSheet(ctx, row, prev, t);
        if (Math.abs(row.net_income - before) <= TOL * Math.max(1, Math.abs(before))) { converged = true; break; }
      }
      if (!converged) throw new ProjectionError(`interest did not converge in year ${t + 1}`);
    }
    row.cash_flow = cashFlow(row, prev);
    row.managerial = managerial(row);
    row.free_cash_flow = fcf(row, prev, drivers, t);
    row.balance_check = row.managerial.invested_capital - row.managerial.capital_employed;
    out.push(row);
    prev = row;
  }
  return { base: opening(base), drivers: structuredClone(drivers), years: out };
}

export function baseFromDetail(v) {
  const g = (k) => v[k] || 0;
  const da = v.depreciation_amortization_cf;
  let dep = v.depreciation_expense, amort = v.amortization_of_intangibles;
  if (!isNil(da) && isNil(dep)) { dep = da - (amort || 0); }
  let liabilities = v.liabilities;
  if (isNil(liabilities) && !isNil(v.liabilities_and_equity)) {
    let eq = v.all_equity_balance_including_minority_interest;
    if (isNil(eq)) eq = g("all_equity_balance") + g("minority_interest_balance");
    liabilities = v.liabilities_and_equity - eq - g("temporary_and_mezzanine_financing");
  }
  const ca = g("current_assets_total"), cl = g("current_liabilities_total");
  const ltLiab = (liabilities || 0) - cl;
  return {
    revenue: v.revenue, cogs: v.cost_of_goods_and_services_sold, sga: v.selling_general_and_admin_expenses,
    rnd: v.research_and_development_expenses, other_opex: v.other_operating_expense,
    depreciation: dep, amortization: amort, capex: v.capital_expenses,
    interest_expense: v.interest_expense, interest_income: v.interest_income,
    income_taxes: v.income_taxes, net_income: "profit_loss" in v ? v.profit_loss : v.net_income,
    cash: g("cash_and_marketable_securities"), receivables: g("trade_receivables"), inventory: g("inventories"),
    other_current_assets: ca - g("cash_and_marketable_securities") - g("trade_receivables") - g("inventories"),
    fixed_assets: g("assets") - ca, payables: g("trade_payables"),
    accrued: cl - g("trade_payables") - g("short_term_debt"),
    short_term_debt: g("short_term_debt"), long_term_debt: g("long_term_debt"),
    other_lt_liabilities: ltLiab - g("long_term_debt"),
    equity: g("assets") - (liabilities || 0),
  };
}
