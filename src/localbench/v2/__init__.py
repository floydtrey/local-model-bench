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
from .records import (
    CASE_STATUSES,
    EVALUATION_VERDICTS,
    RUN_LAYERS,
    benchmark_input,
    case_result,
    effective_runtime_config,
    evaluation_result,
    evaluator_identity,
    host_profile,
    model_identity,
    run_manifest,
    runtime_profile,
    trial_identity,
)

__all__ = [
    "EVIDENCE_SCHEMA_VERSION",
    "RECORD_TYPES",
    "EvidenceRef",
    "SealedEvidence",
    "canonical_json_bytes",
    "seal_evidence",
    "sha256_json",
    "CASE_STATUSES",
    "EVALUATION_VERDICTS",
    "RUN_LAYERS",
    "host_profile",
    "runtime_profile",
    "model_identity",
    "effective_runtime_config",
    "benchmark_input",
    "evaluator_identity",
    "trial_identity",
    "run_manifest",
    "case_result",
    "evaluation_result",
]
