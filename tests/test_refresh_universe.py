import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("refresh_universe", ROOT / "scripts" / "refresh_universe.py")
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


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
    assert out[0][1] == ["sic-lists", "--as-of", "2026-10-21"]
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
    u = tmp_path / "u.json"
    u.write_text(json.dumps({"tickers": ["BAD", "OK"]}))
    assert refresh.main(["--universe", str(u), "--as-of", "2026-10-21"]) == 0
    assert calls == ["--as-of", "BAD", "OK"]           # SIC lists first
    u.write_text(json.dumps({"tickers": ["BAD"]}))
    assert refresh.main(["--universe", str(u), "--as-of", "2026-10-21"]) == 1
