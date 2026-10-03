"""L0 Ingest: fetch and cache raw source data, emit raw_filing.json.

L0 is deliberately faithful to the source. It does not dedupe, filter, or
map tags to canonical line items; that is L1's job.
"""
from .schema import SCHEMA_VERSION, validate_raw_filing
from .sec_companyfacts import SecCompanyFactsAdapter

__all__ = ["SCHEMA_VERSION", "validate_raw_filing", "SecCompanyFactsAdapter"]
