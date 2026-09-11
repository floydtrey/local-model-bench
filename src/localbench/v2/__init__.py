"""Benchmark Lab V2 contracts and qualification infrastructure.

V2 is intentionally additive. The existing ``localbench`` V1 runner and result
contracts remain available for historical reproduction.
"""

from .benchmark_pack import (
    ASSET_DELIVERY_MODES,
    CAPABILITY_LEVELS,
    PACK_SCHEMA_VERSION,
    RESPONSE_MODES,
    BenchmarkPack,
    load_benchmark_pack,
    parse_benchmark_pack,
)
from .configuration import CONFIG_SPEC_VERSION, resolve_effective_configuration
from .contracts import (
    EVIDENCE_SCHEMA_VERSION,
    RECORD_TYPES,
    EvidenceRef,
    SealedEvidence,
    canonical_json_bytes,
    seal_evidence,
    sha256_json,
)
from .evaluators import (
    EVALUATOR_SPEC_VERSION,
    SCORING_MODES,
    EvidenceConsumption,
    EvaluationCheck,
    EvaluationContext,
    EvaluationDraft,
    EvaluatorDefinition,
    EvaluatorRegistry,
    canonical_definition_bytes,
    definition_sha256,
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
    "ASSET_DELIVERY_MODES",
    "CAPABILITY_LEVELS",
    "PACK_SCHEMA_VERSION",
    "RESPONSE_MODES",
    "BenchmarkPack",
    "load_benchmark_pack",
    "parse_benchmark_pack",
    "CONFIG_SPEC_VERSION",
    "EVIDENCE_SCHEMA_VERSION",
    "RECORD_TYPES",
    "EvidenceRef",
    "SealedEvidence",
    "canonical_json_bytes",
    "seal_evidence",
    "sha256_json",
    "resolve_effective_configuration",
    "EVALUATOR_SPEC_VERSION",
    "SCORING_MODES",
    "EvidenceConsumption",
    "EvaluationCheck",
    "EvaluationContext",
    "EvaluationDraft",
    "EvaluatorDefinition",
    "EvaluatorRegistry",
    "canonical_definition_bytes",
    "definition_sha256",
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
