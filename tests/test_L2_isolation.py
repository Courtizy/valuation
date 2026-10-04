"""L2 isolation rules and reconcile behaviour. Run: pytest tests/test_L2_isolation.py"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from valuation.L2_models.base import MODEL_NAMES, ModelResult, get_model
from valuation.L2_models.reconcile import build_comparison

L2 = Path(__file__).resolve().parent.parent / "src" / "valuation" / "L2_models"


def _imports(pkg_dir: Path) -> set[str]:
    found = set()
    for py in pkg_dir.rglob("*.py"):
        for node in ast.walk(ast.parse(py.read_text())):
            if isinstance(node, ast.Import):
                found.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                found.add(node.module)
    # compare without the package prefix: valuation.L2_models.dcf -> L2_models.dcf, valuation._core.x -> core.x
    return {n.removeprefix("valuation.").replace("_core", "core", 1) if n.startswith("valuation._core") else n.removeprefix("valuation.")
            for n in found}


@pytest.mark.parametrize("model", MODEL_NAMES)
def test_models_do_not_import_each_other(model):
    others = {f"L2_models.{m}" for m in MODEL_NAMES if m != model} | {"L2_models.reconcile"}
    bad = {i for i in _imports(L2 / model) if any(i == o or i.startswith(o + ".") for o in others)}
    assert not bad, f"{model} imports {bad}"


def test_reconcile_imports_no_model():
    models = {f"L2_models.{m}" for m in MODEL_NAMES} | {"L2_models.base"}
    bad = {i for i in _imports(L2 / "reconcile") if any(i == o or i.startswith(o + ".") for o in models)}
    assert not bad, f"reconcile imports {bad}"


BUILT = {"dcf", "comps"}


def test_all_models_registered_and_scaffolded():
    for m in MODEL_NAMES:
        model = get_model(m)
        assert model.name == m
        with pytest.raises(ValueError if m in BUILT else NotImplementedError):
            model.run({}, {})


@pytest.mark.parametrize("model", MODEL_NAMES)
def test_models_import_only_base_and_core(model):
    allowed = ("L2_models.base", "core")
    layers = ("L0_ingest", "L1_detail", "L2_models", "L3_app", "pipeline")
    for name in _imports(L2 / model):
        if name.split(".")[0] in layers or name.startswith("L2_models"):
            assert any(name == a or name.startswith(a + ".") for a in allowed) or name == f"L2_models.{model}", \
                f"{model} imports {name}"


def test_peer_flags():
    assert get_model("comps").needs_peers and get_model("ipo").needs_peers
    assert not get_model("dcf").needs_peers


def _write(tmp_path, model, value, assumptions, sha="aaa", as_of="2026-09-30"):
    r = ModelResult(model=model, ticker="AAPL", as_of=as_of,
                    value_per_share={"p10": value * 0.8, "p50": value, "p90": value * 1.2, "mean": value},
                    assumptions_used=assumptions,
                    lineage={"as_of": as_of, "inputs": [{"file": "company_detail.json", "sha256": sha}]})
    p = tmp_path / f"{model}.json"
    p.write_text(json.dumps(r.to_dict()))
    return p


def test_reconcile_football_field_and_assumption_diffs(tmp_path):
    a = _write(tmp_path, "dcf", 200, {"cost_of_capital": {"wacc": 0.089}, "terminal": {"growth": 0.025}})
    b = _write(tmp_path, "lbo", 180, {"cost_of_capital": {"wacc": 0.095}, "exit": {"multiple": 12}})
    comp = build_comparison([a, b])
    assert [row["model"] for row in comp["football_field"]] == ["dcf", "lbo"]
    diffs = {d["field"]: d["values"] for d in comp["assumption_differences"]}
    assert diffs == {"cost_of_capital.wacc": {"dcf": 0.089, "lbo": 0.095}}  # shared field only
    assert comp["warnings"] == []


def test_reconcile_warns_on_mismatched_inputs(tmp_path):
    a = _write(tmp_path, "dcf", 200, {}, sha="aaa")
    b = _write(tmp_path, "comps", 210, {}, sha="bbb", as_of="2026-06-30")
    w = build_comparison([a, b])["warnings"]
    assert any("different as_of" in x for x in w)
    assert any("different versions of company_detail.json" in x for x in w)


def test_reconcile_rejects_mixed_tickers(tmp_path):
    a = _write(tmp_path, "dcf", 200, {})
    doc = json.loads(a.read_text()); doc["ticker"] = "MSFT"
    b = tmp_path / "other.json"; b.write_text(json.dumps(doc))
    with pytest.raises(ValueError):
        build_comparison([a, b])
