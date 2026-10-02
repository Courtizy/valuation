"""Contract for canonical_statements.json (L1 stage 1 -> stage 2)."""
from __future__ import annotations

CANONICAL_SCHEMA_VERSION = "0.1.0"

REQUIRED_TOP = {
    "schema_version": str, "stage": str, "as_of": str, "registry_version": str,
    "entity": dict, "source": dict, "lineage": dict, "records": list,
    "checks": list, "coverage": dict, "warnings": list,
}
REQUIRED_RECORD = {
    "concept": str, "statement": str, "period_type": str, "unit": str, "end": str,
    "method": str, "source": dict, "restated": bool,
}
NULLABLE_RECORD = ("start", "months", "fiscal_year", "fiscal_period", "value_as_filed")
METHODS = {"reported", "summed", "derived"}
MAX_ERRORS = 50


def validate_canonical(doc: dict) -> list[str]:
    errors: list[str] = []
    if not isinstance(doc, dict):
        return ["document is not a JSON object"]
    for key, typ in REQUIRED_TOP.items():
        if not isinstance(doc.get(key), typ):
            errors.append(f"{key} missing or not {typ.__name__}")
    if errors:
        return errors
    if doc["schema_version"] != CANONICAL_SCHEMA_VERSION:
        errors.append(f"schema_version {doc['schema_version']!r} != {CANONICAL_SCHEMA_VERSION!r}")

    seen = set()
    for i, r in enumerate(doc["records"]):
        for key, typ in REQUIRED_RECORD.items():
            if not isinstance(r.get(key), typ):
                errors.append(f"records[{i}].{key} missing or not {typ.__name__}")
        v = r.get("value")
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            errors.append(f"records[{i}].value missing or not numeric")
        for key in NULLABLE_RECORD:
            if key not in r:
                errors.append(f"records[{i}].{key} key absent (use null)")
        if r.get("method") not in METHODS:
            errors.append(f"records[{i}].method {r.get('method')!r} not in {sorted(METHODS)}")
        if r.get("period_type") == "instant" and r.get("start") is not None:
            errors.append(f"records[{i}]: instant record has a start date")
        if r.get("period_type") == "duration" and r.get("start") is None:
            errors.append(f"records[{i}]: duration record has no start date")
        key = (r.get("concept"), r.get("start"), r.get("end"))
        if key in seen:
            errors.append(f"records[{i}]: duplicate {key}")
        seen.add(key)
        if len(errors) >= MAX_ERRORS:
            errors.append("... truncated")
            break
    return errors
