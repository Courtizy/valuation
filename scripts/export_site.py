"""Public door: everything the static site needs besides the pipeline's published data.

    python scripts/export_site.py

  1. brand/ (css, js, icons) -> site/brand/
  2. the pre-loaded demo: synthetic companies through the real pipeline -> site/demo/data/
  3. CHANGELOG.md -> site/data/changelog.json (the Method page's changelog)
  4. site/data index refreshed (publish over what's there; demo data never stays in it)

Real companies reach site/data through the Pipeline workflow (SEC filings, showcase mode).
The site only displays JSON; all math stays in src/valuation/.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
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


def main() -> int:
    copy_brand()
    print("brand -> site/brand")
    print("demo ->", write_demo(SITE / "demo").relative_to(ROOT))
    (SITE / "data").mkdir(parents=True, exist_ok=True)
    (SITE / "data" / "changelog.json").write_text(json.dumps({"releases": changelog()}, indent=1))
    publish(ROOT / "data-not-in-repo", SITE)   # refresh index.json / companies.json over the published data
    print("site/data index refreshed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
