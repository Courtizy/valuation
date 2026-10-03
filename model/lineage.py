"""Lineage block carried by every L1+ output file.

Lets any result be traced to the exact input files that produced it, and lets
reconcile detect models that ran on different versions of the same input.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def lineage_block(as_of: str, inputs: list[str | Path]) -> dict:
    return {
        "as_of": as_of,
        "inputs": [{"file": Path(p).name, "sha256": sha256_file(p)} for p in inputs],
    }
