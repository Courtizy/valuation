from __future__ import annotations

import argparse
from pathlib import Path

from L3_app.demo import write_demo


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="L3_app.demo")
    p.add_argument("--site-dir", type=Path, default=Path("site"))
    args = p.parse_args(argv)
    print(f"wrote demo data -> {write_demo(args.site_dir)}")
    from L3_app.publish import publish
    publish(Path("data-not-used-for-demo"), args.site_dir)   # rebuild index.json / companies.json
    return 0





if __name__ == "__main__":
    raise SystemExit(main())
