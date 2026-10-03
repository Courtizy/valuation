"""Runner tests (offline). Run: pytest tests/test_pipeline.py"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from fakes import FakeSecClient
from L0_ingest.sec_companyfacts import SecCompanyFactsAdapter
from runner import Paths, execute, main, plan

FIXTURES = Path(__file__).parent / "fixtures"


def FakeClient():
    return FakeSecClient(fallback=lambda url: FIXTURES / ("company_tickers.json" if url.endswith("company_tickers.json")
                                                          else "companyfacts_CIK0000320193.json"))


def factory():
    return SecCompanyFactsAdapter(client=FakeClient())


def make_paths(tmp_path, peers=None):
    paths = Paths(tmp_path / "data", tmp_path / "assumptions")
    if peers is not None:
        d = paths.assumptions / "AAPL"
        d.mkdir(parents=True)
        (d / "comps.json").write_text(json.dumps({"peers": peers}))
    return paths


def test_plan_single_model_order(tmp_path):
    steps = plan("aapl", ["dcf"], "2026-09-30", make_paths(tmp_path), factory)
    assert [s.name for s in steps] == [
        "ingest AAPL", "normalize AAPL", "build detail AAPL", "model dcf", "reconcile"]
    assert [s.layer for s in steps] == ["L0", "L1", "L1", "L2", "L2"]


def test_plan_adds_peers_only_when_a_model_needs_them(tmp_path):
    paths = make_paths(tmp_path, peers=["msft", "AAPL"])
    dcf_only = plan("AAPL", ["dcf"], "2026-09-30", paths, factory)
    assert not any("MSFT" in s.name for s in dcf_only)

    with_comps = plan("AAPL", ["dcf", "comps"], "2026-09-30", paths, factory)
    names = [s.name for s in with_comps]
    assert "ingest MSFT" in names and "build detail MSFT" in names
    assert names.count("ingest AAPL") == 1  # target not duplicated as its own peer
    # every company's L1 finishes before any model runs
    assert names.index("build detail MSFT") < names.index("model dcf")


def test_plan_rejects_unknown_model(tmp_path):
    with pytest.raises(KeyError):
        plan("AAPL", ["magic"], "2026-09-30", make_paths(tmp_path), factory)


def test_paths_are_point_in_time(tmp_path):
    paths = make_paths(tmp_path)
    assert paths.detail("AAPL", "2026-09-30").parent.name == "2026-09-30"
    assert paths.raw_filing("AAPL").parent.name == "raw"


def test_execute_runs_l0_and_l1_then_the_dcf_default_case(tmp_path):
    paths = make_paths(tmp_path)
    report = execute(plan("AAPL", ["dcf"], "2026-09-30", paths, factory))
    status = {name: st for name, st, _ in report}
    assert status["ingest AAPL"] == "done"
    assert paths.raw_filing("AAPL").exists()
    assert status["normalize AAPL"] == "done"
    assert paths.canonical("AAPL", "2026-09-30").exists()
    assert status["build detail AAPL"] == "done"
    assert paths.detail("AAPL", "2026-09-30").exists()
    # no dcf.json: the default case runs; this two-fact fixture has no risk-free rate (no market step), so it
    # stops on that named input, and reconcile has nothing to blend
    assert status["model dcf"] == "failed"
    assert "risk_free" in {name: msg for name, _, msg in report}["model dcf"]   # named input, not a missing file
    assert status["reconcile"] == "failed"          # models are soft; reconcile reports nothing to blend


def test_execute_reports_failures_without_raising(tmp_path):
    from runner import Step

    def boom():
        raise RuntimeError("bad data")

    report = execute([Step("x", "L0", "AAPL", [], boom), Step("y", "L1", "AAPL", [], lambda: None)])
    assert report[0][1] == "failed" and "bad data" in report[0][2]
    assert report[1][1] == "skipped"


def test_cli_dry_run(tmp_path):
    rc = main(["run", "AAPL", "--models", "dcf,comps", "--as-of", "2026-09-30",
               "--data-dir", str(tmp_path / "data"),
               "--assumptions-dir", str(tmp_path / "assumptions"), "--dry-run"],
              adapter_factory=factory)
    assert rc == 0


def test_peer_detail_built_for_the_same_date_is_reused(tmp_path):
    paths = make_paths(tmp_path, peers=["MSFT"])
    d = paths.detail("MSFT", "2026-09-30")
    d.parent.mkdir(parents=True)
    d.write_text("{}")
    names = [s.name for s in plan("AAPL", ["comps"], "2026-09-30", paths, factory)]
    assert "ingest MSFT" not in names and "ingest AAPL" in names


def test_expected_gaps_are_warnings_not_failures():
    from runner import Step

    class Gap(ValueError):
        is_warning = True

    def gap():
        raise Gap("no peer has a price")
    report = execute([Step("model comps", "L2", "KO", [], gap, soft=True)])
    assert report[0][1] == "warning"
