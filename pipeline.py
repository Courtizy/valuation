"""Pipeline runner: sequences L0 -> L1 -> L2 for a ticker and its peers.

  python pipeline.py run AAPL --models dcf,comps --as-of 2026-09-30 --dry-run
  python pipeline.py run AAPL --models dcf
  python pipeline.py sector sic-of:AAPL              # the sector a company belongs to (Technology)
  python pipeline.py sector sector:technology        # a sector of inputs/sectors/taxonomy.json
  python pipeline.py sector sic:3674                 # one SEC industry code
  python pipeline.py sector "traits:stage=high growth;asset_intensity=light"
  python pipeline.py sector list:my_semis            # tickers in inputs/sectors/my_semis.json

The runner holds sequencing only. Every layer stays runnable on its own, and
the app (L3) calls this instead of orchestrating inside Streamlit.

Data layout:
  data/{TICKER}/raw/raw_filing.json                        L0
  data/{TICKER}/{as_of}/canonical_statements.json          L1 stage 1
  data/{TICKER}/{as_of}/company_detail.json                L1 stage 2
  data/{TICKER}/{as_of}/model_results/{model}.json         L2 models
  data/{TICKER}/{as_of}/comparison.json                    L2 reconcile
  data/_screen/{as_of}/raw_screen.json                     L0 sector frames (all filers)
  data/_screen/{as_of}/sic_{code}.json                     L0 EDGAR company list for a SIC code
  data/sectors/{sector_id}/{as_of}/sector.json             L1 sector screen
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "model"))  # code lives in model/

from runner import SECTOR_KINDS, Paths, Step, execute, load_peers, main, parse_sector_spec, plan, run_sector  # noqa: F401

if __name__ == "__main__":
    sys.exit(main())
