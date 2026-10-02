"""Copy pipeline outputs into site/data and write site/data/index.json.

  python -m L3_app.publish --data-dir data --site-dir site

For every data/{TICKER}/{as_of}/ it copies company_detail.json, comparison.json
and model_results/*.json when present. Raw SEC files and canonical statements
stay out of the site. The index is rebuilt from what is in site/data, so runs
published earlier are kept.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

AS_OF = re.compile(r"^\d{4}-\d{2}-\d{2}$")
PUBLISHED = ("company_detail.json", "comparison.json")


def copy_outputs(data_dir: Path, site_data: Path) -> list[str]:
    copied = []
    for tdir in sorted(p for p in data_dir.iterdir() if p.is_dir()):
        for adir in sorted(p for p in tdir.iterdir() if p.is_dir() and AS_OF.match(p.name)):
            dest = site_data / tdir.name / adir.name
            files = [adir / f for f in PUBLISHED if (adir / f).exists()]
            files += sorted((adir / "model_results").glob("*.json")) if (adir / "model_results").exists() else []
            if not files:
                continue
            for f in files:
                target = dest / f.relative_to(adir)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(f, target)
                copied.append(str(target.relative_to(site_data)))
    return copied


def build_index(site_data: Path) -> dict:
    companies = []
    for tdir in sorted(p for p in site_data.iterdir() if p.is_dir()):
        runs = []
        name, demo = tdir.name, False
        for adir in sorted((p for p in tdir.iterdir() if p.is_dir() and AS_OF.match(p.name)), reverse=True):
            detail = adir / "company_detail.json"
            if not detail.exists():
                continue
            doc = json.loads(detail.read_text())
            name = doc.get("entity", {}).get("name") or name
            demo = demo or bool(doc.get("demo"))
            runs.append({
                "as_of": adir.name,
                "detail": f"{tdir.name}/{adir.name}/company_detail.json",
                "comparison": (f"{tdir.name}/{adir.name}/comparison.json"
                               if (adir / "comparison.json").exists() else None),
                "models": sorted(p.stem for p in (adir / "model_results").glob("*.json"))
                if (adir / "model_results").exists() else [],
                "latest": doc.get("latest", {}),
            })
        if runs:
            companies.append({"ticker": tdir.name, "name": name, "demo": demo, "runs": runs})
    companies.sort(key=lambda c: (c["demo"], c["ticker"]))
    return {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "companies": companies}


def concept_labels() -> dict:
    """Display names for the site, from the L1 registry (the one source of labels)."""
    from L1_detail.registry import load_registry
    return {c.id: {"name": c.display_name, "statement": c.statement}
            for c in load_registry().concepts.values()}


def publish(data_dir: Path, site_dir: Path) -> dict:
    site_data = site_dir / "data"
    site_data.mkdir(parents=True, exist_ok=True)
    copied = copy_outputs(data_dir, site_data) if data_dir.exists() else []
    index = build_index(site_data)
    (site_data / "index.json").write_text(json.dumps(index, indent=2))
    (site_data / "concepts.json").write_text(json.dumps(concept_labels(), indent=2))
    return {"copied": copied, "companies": [c["ticker"] for c in index["companies"]]}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="L3_app.publish")
    p.add_argument("--data-dir", type=Path, default=Path("data"))
    p.add_argument("--site-dir", type=Path, default=Path("site"))
    args = p.parse_args(argv)
    out = publish(args.data_dir, args.site_dir)
    print(f"copied {len(out['copied'])} file(s); index lists {', '.join(out['companies']) or 'nothing'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
