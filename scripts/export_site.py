"""Public door: everything the static site needs besides the pipeline's published data.

    python scripts/export_site.py

  1. brand/ (css, js, icons) -> site/brand/
  2. the pre-loaded demo: synthetic companies through the real pipeline -> site/demo/data/
  3. CHANGELOG.md -> site/data/changelog.json (the Method page's changelog)
  4. site/data index refreshed (publish over what's there; demo data never stays in it)
  5. site/py/valuation.zip: the engine and configs/public, for the in-browser Run (Pyodide)

Real companies reach site/data through the Pipeline workflow (SEC filings, showcase mode).
The site only displays JSON; all math stays in src/valuation/.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
sys.path.insert(0, str(ROOT / "src"))

from valuation.L3_app.demo import write_demo  # noqa: E402
from valuation.L3_app.publish import publish  # noqa: E402


def copy_brand() -> None:
    dst = SITE / "brand"
    if dst.exists():
        shutil.rmtree(dst)
    for part in ("css", "js", "icons"):
        shutil.copytree(ROOT / "brand" / part, dst / part)


def changelog(limit: int = 8) -> list[dict]:
    """[{version, date, items}] from CHANGELOG.md ('## [0.2.0] - 2026-10-04' headings, '- ' items)."""
    out = []
    for block in re.split(r"^## ", (ROOT / "CHANGELOG.md").read_text(), flags=re.M)[1:]:
        head, *lines = block.strip().splitlines()
        m = re.match(r"\[?([^\]\s]+)\]?\s*[-–]\s*(.+)", head)
        out.append({"version": m.group(1) if m else head, "date": m.group(2).strip() if m else "",
                    "items": [l[2:].strip() for l in lines if l.startswith("- ")]})
    return out[:limit]


def web_package(out: Path = SITE / "py" / "valuation.zip") -> Path:
    """src/valuation and configs/public, laid out as in the repo so the package finds its configs."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for base in (ROOT / "src" / "valuation", ROOT / "configs" / "public"):
            for f in sorted(base.rglob("*")):
                if f.is_file() and "__pycache__" not in f.parts and f.suffix in (".py", ".json"):
                    z.write(f, f.relative_to(ROOT).as_posix())
    return out


def main() -> int:
    copy_brand()
    print("brand -> site/brand")
    print("demo ->", write_demo(SITE / "demo").relative_to(ROOT))
    (SITE / "data").mkdir(parents=True, exist_ok=True)
    (SITE / "data" / "changelog.json").write_text(json.dumps({"releases": changelog()}, indent=1))
    publish(ROOT / "data-not-in-repo", SITE)   # refresh index.json / companies.json over the published data
    print("site/data index refreshed")
    print("engine ->", web_package().relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
