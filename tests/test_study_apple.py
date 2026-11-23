"""Apple FY2027 growth study: the case script, its frozen inputs and AAPL's dcf.json agree."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STUDY = ROOT / "studies" / "apple-fy2027"


def _case():
    spec = importlib.util.spec_from_file_location("apple_case", STUDY / "case.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_product_lines_add_up_to_filed_sales():
    facts = json.loads((STUDY / "inputs.json").read_text())["facts"]["revenue"]
    for end, total in facts["total"].items():
        parts = sum(facts[k][end]["value"] for k in ("iphone", "services", "mac", "ipad", "wearables"))
        assert abs(parts - total["value"]) < 1e6, end


def test_dcf_json_carries_the_case():
    case = _case()
    res = case.run(json.loads((STUDY / "inputs.json").read_text()))
    assert case.check(res) == []
    assert res["path_growth"][-1] == 0.03                                  # ends on terminal growth
    assert res["cogs_pct_revenue"][0] < 245.23e9 / 478.83e9                # mix shift lowers cost of sales
    assert json.loads((STUDY / "results.json").read_text()) == res
