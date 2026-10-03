"""L1 Company Detail: normalize raw facts to canonical concepts, then build
statements (annual | quarterly | ttm), join market data, and compute ratios.
"""
from .registry import Concept, Registry, load_registry, validate_registry

__all__ = ["Concept", "Registry", "load_registry", "validate_registry"]
