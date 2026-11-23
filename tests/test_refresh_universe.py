import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("refresh_universe", ROOT / "scripts" / "refresh_universe.py")
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


@pytest.fixture(autouse=True)
def _no_damodaran_network(monkeypatch):
    """No test here reaches Damodaran's site; the tests that care replace this."""
    monkeypatch.setattr(refresh, "fetch_damodaran", lambda as_of: None)


def test_universe_file_is_valid():
    u = json.loads((ROOT / "configs" / "public" / "universe.json").read_text())
    assert u["sectors"] and u["tickers"]
    assert all(t == t.upper() for t in u["tickers"])


def test_jobs_add_comps_only_where_peers_exist(tmp_path):
    (tmp_path / "ABC").mkdir()
    (tmp_path / "ABC" / "comps.json").write_text("{}")
    out = refresh.jobs({"sectors": ["sector:technology"], "tickers": ["ABC", "XYZ", "ABC"]},
                       "2026-10-21", "risk-free", tmp_path)
    assert [name for name, _ in out] == ["SIC lists", "sector:technology", "ABC", "XYZ"]      # duplicates dropped
    assert out[0][1] == ["sic-lists", "--as-of", "2026-10-21", "--time-budget", "20"]
    assert out[1][1] == ["sector", "sector:technology", "--as-of", "2026-10-21"]
    assert out[2][1][out[2][1].index("--models") + 1] == "dcf,comps"
    assert out[3][1][out[3][1].index("--models") + 1] == "dcf"
    assert out[3][1][-2:] == ["--market", "risk-free"]


def test_one_failure_does_not_stop_the_rest(tmp_path, monkeypatch):
    calls = []

    def fake(cmd):
        calls.append(cmd[1])
        if cmd[1] == "BAD":
            raise RuntimeError("bad filing")
        return 0

    monkeypatch.setattr(refresh, "pipeline", fake)
    monkeypatch.setattr(refresh, "fetch_risk_free", lambda as_of: None)
    u = tmp_path / "u.json"
    u.write_text(json.dumps({"tickers": ["BAD", "OK"]}))
    assert refresh.main(["--universe", str(u), "--as-of", "2026-10-21"]) == 0
    assert calls == ["--as-of", "BAD", "OK"]           # SIC lists first
    u.write_text(json.dumps({"tickers": ["BAD"]}))
    assert refresh.main(["--universe", str(u), "--as-of", "2026-10-21"]) == 1


# ---- guards against one slow source using up the job (2026-10-26, 11-02, 11-16 runs were cancelled at 90 min)

def test_sic_lists_run_with_a_time_budget():
    out = refresh.jobs({"tickers": []}, "2026-10-21", "risk-free")
    assert out[0][1] == ["sic-lists", "--as-of", "2026-10-21", "--time-budget", "20"]


def test_risk_free_is_fetched_once_before_the_companies(tmp_path, monkeypatch):
    calls, order = [], []
    monkeypatch.setattr(refresh, "pipeline", lambda cmd: order.append(cmd[1]) or 0)
    monkeypatch.setattr(refresh, "fetch_risk_free", lambda as_of: calls.append(as_of) or order.append("RF"))
    u = tmp_path / "u.json"
    u.write_text(json.dumps({"sectors": ["sector:technology"], "tickers": ["A", "B", "C"]}))
    assert refresh.main(["--universe", str(u), "--as-of", "2026-11-02"]) == 0
    assert calls == ["2026-11-02"]
    assert order == ["--as-of", "sector:technology", "RF", "A", "B", "C"]   # SIC lists, sector, then the rate


def test_no_risk_free_rate_skips_companies_at_once(tmp_path, monkeypatch, capsys):
    ran = []
    monkeypatch.setattr(refresh, "pipeline", lambda cmd: ran.append(cmd[1]) or 0)

    def down(as_of):
        raise TimeoutError("The read operation timed out")
    monkeypatch.setattr(refresh, "fetch_risk_free", down)
    u = tmp_path / "u.json"
    u.write_text(json.dumps({"sectors": ["sector:technology"], "tickers": ["A", "B"]}))
    assert refresh.main(["--universe", str(u), "--as-of", "2026-11-02"]) == 0     # the sector still built
    assert ran == ["--as-of", "sector:technology"]                              # no company was started
    out = capsys.readouterr()
    assert "2 failed (A, B)" in out.out and "no risk-free rate" in out.out


def test_damodaran_is_fetched_once_and_its_outage_costs_no_company_a_retry(tmp_path, monkeypatch, capsys):
    """Damodaran is optional: when its one fetch fails, every company still runs, told not to retry it."""
    cmds, asked = [], []
    monkeypatch.setattr(refresh, "pipeline", lambda cmd: cmds.append(cmd) or 0)
    monkeypatch.setattr(refresh, "fetch_risk_free", lambda as_of: None)

    def down(as_of):
        asked.append(as_of)
        raise TimeoutError("The read operation timed out")
    monkeypatch.setattr(refresh, "fetch_damodaran", down)
    u = tmp_path / "u.json"
    u.write_text(json.dumps({"tickers": ["A", "B"]}))
    assert refresh.main(["--universe", str(u), "--as-of", "2026-11-23"]) == 0
    assert asked == ["2026-11-23"]                                         # once, not once per company
    runs = [c for c in cmds if c[0] == "run"]
    assert [c[1] for c in runs] == ["A", "B"] and all(c[-1] == "--no-damodaran" for c in runs)
    assert "Damodaran unavailable" in capsys.readouterr().out
    cmds.clear()
    monkeypatch.setattr(refresh, "fetch_damodaran", lambda as_of: None)
    refresh.main(["--universe", str(u), "--as-of", "2026-11-23"])
    assert not any("--no-damodaran" in c for c in cmds)                    # up: nothing changes


def test_no_damodaran_drops_the_step_from_a_company_run(tmp_path):
    from valuation.runner.company import plan
    from valuation.runner.paths import Paths
    paths = Paths(tmp_path / "data", tmp_path / "assumptions")
    names = lambda **kw: [s.name for s in plan("ABC", ["dcf"], "2026-11-23", paths, object, "L2",  # noqa: E731
                                               market_factory=object, market_prices=False, **kw)]
    assert "industry betas and ERP (Damodaran)" in names()
    assert "industry betas and ERP (Damodaran)" not in names(damodaran=False)


def test_no_market_scope_never_asks_for_the_rate(tmp_path, monkeypatch):
    monkeypatch.setattr(refresh, "pipeline", lambda cmd: 0)
    monkeypatch.setattr(refresh, "fetch_risk_free", lambda as_of: (_ for _ in ()).throw(AssertionError("called")))
    u = tmp_path / "u.json"
    u.write_text(json.dumps({"tickers": ["A"]}))
    assert refresh.main(["--universe", str(u), "--as-of", "2026-11-02", "--market", "none"]) == 0


class _SlowEdgar:
    """A fake SEC adapter whose every SIC page takes `secs` of a fake clock."""
    def __init__(self, clock, secs):
        self.clock, self.secs, self.asked = clock, secs, []

    def sic_members(self, code, deadline=None, clock=None):
        if deadline is not None and self.clock() >= deadline:
            raise TimeoutError("budget")
        self.asked.append(code)
        self.clock.t += self.secs
        return {"sic": code, "description": None, "ciks": ["0000000001"]}


class _Clock:
    t = 0.0

    def __call__(self):
        return self.t


def test_sic_lists_stop_at_the_time_budget_and_rotate_weekly(tmp_path):
    from valuation.runner.paths import Paths
    from valuation.runner.sector import sic_lists
    clock = _Clock()
    edgar = _SlowEdgar(clock, 60)                       # one minute per code
    done, failed = sic_lists("2026-11-16", Paths(tmp_path, tmp_path), lambda: edgar, budget_seconds=600, clock=clock)
    assert done == 10 and len(edgar.asked) == 10        # ten minutes of budget, ten codes
    assert failed and "not tried (time budget 10 min)" in failed[-1]
    clock.t, nxt = 0.0, _SlowEdgar(clock, 60)
    sic_lists("2026-11-23", Paths(tmp_path / "w2", tmp_path), lambda: nxt, budget_seconds=60, clock=clock)
    assert nxt.asked[0] != edgar.asked[0]               # next week starts somewhere else
    clock.t, free = 0.0, _SlowEdgar(clock, 60)
    done, failed = sic_lists("2026-11-16", Paths(tmp_path / "w3", tmp_path), lambda: free, clock=clock)
    assert failed == [] and done == len(free.asked) > 10   # no budget: every code


# ---- comps for every company: peers picked from this run's sector screens

def _screens(tmp_path, as_of="2026-11-23"):
    row = lambda t, rev, g, m, ind: {"ticker": t, "revenue": rev, "revenue_cagr": g, "operating_margin": m,  # noqa: E731
                                     "classification": {"sector": "S", "industry": ind}}
    tech = [row("AAA", 100e9, 0.08, 0.30, "hw"), row("HW1", 90e9, 0.02, 0.10, "hw"), row("HW2", 80e9, 0.03, 0.12, "hw"),
            row("HW3", 70e9, 0.01, 0.08, "hw"), row("TINY", 1e9, 0.08, 0.30, "sw")]
    food = [row("BEV", 60e9, 0.07, 0.29, "bev"), row("GRO", 150e9, 0.03, 0.02, "gro")]
    for sid, rows in (("sector-technology", tech), ("sector-food", food)):
        p = tmp_path / "data" / "sectors" / sid / as_of / "sector.json"
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({"label": sid, "companies": rows}))
    src = tmp_path / "assumptions"
    (src / "HAND").mkdir(parents=True)
    (src / "HAND" / "comps.json").write_text('{"peers": ["X"]}')
    return src


def test_auto_comps_picks_like_companies_across_sectors(tmp_path):
    src = _screens(tmp_path)
    out, report = refresh.auto_comps(["AAA", "HAND", "NONE"], "2026-11-23", data_dir=tmp_path / "data",
                                     source=src, out=tmp_path / "copy")
    doc = json.loads((out / "AAA" / "comps.json").read_text())
    assert {p["ticker"] for p in doc["peers"]} == {"HW1", "HW2", "HW3", "TINY"}   # the sector set, from its own screen
    like = [p["ticker"] for p in doc["closest"]]
    assert like[0] == "BEV"                       # same growth and margin, another sector
    assert "TINY" not in like                     # under 1/20 of the revenue
    assert json.loads((out / "HAND" / "comps.json").read_text()) == {"peers": ["X"]}   # hand-picked lists win
    assert "NONE" in report and not (out / "NONE").exists()
    assert not (src / "AAA").exists()             # configs are never written


def test_refresh_passes_the_picked_assumptions_to_each_company(tmp_path, monkeypatch):
    cmds = []
    monkeypatch.setattr(refresh, "pipeline", lambda cmd: cmds.append(cmd) or 0)
    monkeypatch.setattr(refresh, "fetch_risk_free", lambda as_of: None)
    picked = tmp_path / "picked"
    (picked / "A").mkdir(parents=True)
    (picked / "A" / "comps.json").write_text("{}")
    monkeypatch.setattr(refresh, "auto_comps", lambda tickers, as_of: (picked, {}))
    u = tmp_path / "u.json"
    u.write_text(json.dumps({"tickers": ["A", "B"]}))
    assert refresh.main(["--universe", str(u), "--as-of", "2026-11-23", "--market", "all"]) == 0
    runs = {c[1]: c for c in cmds if c[0] == "run"}
    assert runs["A"][runs["A"].index("--models") + 1] == "dcf,comps"
    assert runs["B"][runs["B"].index("--models") + 1] == "dcf"
    assert all(c[-2:] == ["--assumptions-dir", str(picked)] for c in runs.values())
