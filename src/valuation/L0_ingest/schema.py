"""Contract for raw_filing.json (the L0 -> L1 boundary)."""
from __future__ import annotations

SCHEMA_VERSION = "0.2.0"

REQUIRED_TOP = {
    "schema_version": str,
    "source": str,
    "source_url": str,
    "retrieved_at": str,
    "from_cache": bool,
    "content_sha256": str,
    "entity": dict,
    "facts": list,
}
REQUIRED_ENTITY = {"cik": str, "name": str}
REQUIRED_FACT = {
    "taxonomy": str,
    "tag": str,
    "unit": str,
    "end": str,
    "form": str,
    "filed": str,
    "accn": str,
}
# Present on every fact record but may be null.
OPTIONAL_FACT_KEYS = ("label", "description", "start", "fy", "fp", "frame")

MAX_ERRORS = 50


def validate_raw_filing(doc: dict) -> list[str]:
    """Return a list of human-readable problems; an empty list means valid."""
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["document is not a JSON object"]

    for key, typ in REQUIRED_TOP.items():
        if key not in doc:
            errors.append(f"missing top-level key: {key}")
        elif not isinstance(doc[key], typ):
            errors.append(f"{key} should be {typ.__name__}")
    if errors:
        return errors

    if doc["schema_version"] != SCHEMA_VERSION:
        errors.append(
            f"schema_version {doc['schema_version']!r} != expected {SCHEMA_VERSION!r}"
        )

    for key, typ in REQUIRED_ENTITY.items():
        if not isinstance(doc["entity"].get(key), typ):
            errors.append(f"entity.{key} missing or not {typ.__name__}")

    for i, fact in enumerate(doc["facts"]):
        for key, typ in REQUIRED_FACT.items():
            if not isinstance(fact.get(key), typ):
                errors.append(f"facts[{i}].{key} missing or not {typ.__name__}")
        value = fact.get("value")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append(f"facts[{i}].value missing or not numeric")
        for key in OPTIONAL_FACT_KEYS:
            if key not in fact:
                errors.append(f"facts[{i}].{key} key absent (use null)")
        if len(errors) >= MAX_ERRORS:
            errors.append("... truncated")
            break
    return errors
