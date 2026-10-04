from __future__ import annotations

import argparse
from pathlib import Path

from valuation.L3_app.demo import write_demo


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="valuation.L3_app.demo", description="Build the pre-loaded demo into SITE_DIR/demo/data")
    p.add_argument("--site-dir", type=Path, default=Path("site"))
    args = p.parse_args(argv)
    print(f"wrote demo data -> {write_demo(args.site_dir / 'demo')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
