"""Benchmark Lab V2 contracts and qualification infrastructure.

V2 is intentionally additive. The existing ``localbench`` V1 runner and result
contracts remain available for historical reproduction.
"""

from .contracts import (
    EVIDENCE_SCHEMA_VERSION,
    RECORD_TYPES,
    EvidenceRef,
    SealedEvidence,
    canonical_json_bytes,
    seal_evidence,
    sha256_json,
)

__all__ = [
    "EVIDENCE_SCHEMA_VERSION",
    "RECORD_TYPES",
    "EvidenceRef",
    "SealedEvidence",
    "canonical_json_bytes",
    "seal_evidence",
    "sha256_json",
]
