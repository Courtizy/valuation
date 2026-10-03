"""Small numeric helpers shared by every layer."""
from __future__ import annotations


def div(a, b):
    """a / b, or None when either is missing or b is zero (a missing ratio, never a fake zero)."""
    return None if a is None or b is None or b == 0 else a / b
