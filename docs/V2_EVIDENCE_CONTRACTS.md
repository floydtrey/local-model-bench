# Benchmark Lab V2 Evidence Contracts

**Status:** V2 foundation contract

**Applies to:** `architecture/benchmark-lab-v2`

## Purpose

Benchmark Lab V2 must be able to explain exactly which host, runtime, model, effective settings, benchmark inputs, evaluator, and trial produced a scored result. Friendly names and filesystem/network locators are useful metadata, but they are not sufficient evidence identity.

V2 therefore separates two concepts:

- **logical ID** — a stable human/operator-facing name such as `new-tower`, `ollama-local`, or `shared-core-v2`;
- **SHA-256 evidence identity** — the digest of the exact schema version, record type, logical ID, and canonical payload.

Changing evidence while retaining the same logical ID produces a different digest.

## Canonicalization

All V2 sealed evidence uses deterministic UTF-8 JSON with:

- recursively sorted object keys;
- compact separators;
- JSON `null` preserved explicitly;
- non-JSON numeric values such as NaN and Infinity rejected;
- SHA-256 calculated over the schema version, record type, logical ID, and payload together.

Sealed payloads are recursively immutable in memory. Serialization returns a fresh JSON-compatible copy.

## Unknown-data rule

Unknown and unmeasured facts remain `null`.

Benchmark Lab must not infer VRAM, parameter count, quantization, context size, runtime version, driver version, model digest, or other qualification evidence merely because a product/model name normally implies a value.

A record with unknown fields may still be useful for inventory or preflight. Later qualification gates may require specific fields to be measured before the result is eligible for comparison.

## Locator rule

A path, URL, endpoint, model tag, registry name, repository, or other locator may appear as evidence metadata when operationally useful. It does not become the cryptographic identity of the host/runtime/model/benchmark merely because the first implementation uses that locator.

Examples:

- `C:\models\candidate.gguf` locates an artifact; the artifact digest identifies exact bytes when available.
- `candidate:latest` locates a provider model; a provider/artifact digest identifies the exact observed model when available.
- `http://127.0.0.1:11434` locates a runtime endpoint; the RuntimeProfile identifies the observed runtime/build/capabilities.
- `suites/v2/shared-core.json` locates an input; the source SHA-256 identifies the exact input bytes.

## Record chain

A qualification-grade result uses this evidence chain:

```text
HostProfile -------------------------------+
RuntimeProfile ----+                        |
ModelIdentity -----+-> EffectiveConfig(s) --+--> RunManifest
                                             ^       ^
BenchmarkInput ------------------------------+       |
       |                                             |
       +--> TrialIdentity(case + config) ------------+
EvaluatorIdentity -----------------------------------+
                                                     |
                                                     v
                                                CaseResult
                                                     |
                                                     v
                                             EvaluationResult
```

References carry all three identifying facts:

```json
{
  "record_type": "model_identity",
  "logical_id": "candidate-a",
  "sha256": "...64 lowercase hexadecimal characters..."
}
```

A reference to the wrong record type fails closed.

## HostProfile

`host_profile` records one observation of the machine used for a run.

Required payload categories:

- `captured_at`;
- `facts_sha256`;
- `os`;
- `cpu`;
- `memory`;
- `gpus`;
- `storage`;
- `python`;
- `compute_runtimes`;
- `power_thermal` (object or null).

The outer evidence SHA-256 identifies the exact observation and therefore includes collection time and volatile observations. `facts_sha256` is a stable behavior-relevant projection. It deliberately excludes currently available RAM, currently free disk space, and instantaneous thermal state, while retaining OS/build, CPU topology, installed RAM capacity, GPU/VRAM/driver, storage capacity, Python/runtime versions, and active power scheme. Two observations of the same configured machine can therefore have different evidence-record digests but the same host facts fingerprint.

BL-3 defines the actual host probes and which fields become mandatory for qualification. Unsupported measurements remain null.

## RuntimeProfile

`runtime_profile` identifies the observed inference/runtime layer independently of the model.

Required payload categories:

- `runtime_kind`;
- `version`;
- `build`;
- `transport`;
- `executable`;
- `installation_digest`;
- `capabilities`.

An endpoint alone is not runtime identity. Version/build/digest fields remain null until actually observed.

## ModelIdentity

`model_identity` identifies the model artifact/provider object independently of runtime settings.

Required payload categories:

- `family`;
- `name`;
- `source`;
- `artifact_digest`;
- `provider_digest`;
- `parameter_count`;
- `quantization`;
- `precision`;
- `declared_context_tokens`.

A model tag by itself may be adequate for discovery but is not automatically qualification-grade exact identity. BL-4/BL-8 may reject ambiguous identities for scored comparisons.

## EffectiveRuntimeConfig

`effective_runtime_config` binds the exact runtime and model references together with behavior-bearing settings before scored execution.

Required payload categories:

- `runtime` — RuntimeProfile reference;
- `model` — ModelIdentity reference;
- `settings`;
- `tool_surface`;
- `limits`.

This record is intentionally separate from ModelIdentity: temperature, context target, sampling, tool mode, timeout, concurrency, retry policy, and other behavior-changing settings must not redefine the model itself.

A run may contain more than one EffectiveRuntimeConfig because different benchmark cases can legitimately require different response formats, output limits, context targets, or tool surfaces. Those differences must be sealed before execution rather than merged invisibly into a request later.

## BenchmarkInput

`benchmark_input` identifies exact benchmark input bytes and their capability level.

Required payload categories:

- `suite_id`;
- `source_sha256`;
- `level` (`L0` through `L4`);
- ordered `case_ids`;
- `source_format`;
- optional `source_locator`.

The locator is convenience metadata. `source_sha256` is the exact source identity.

## EvaluatorIdentity

`evaluator_identity` identifies the scoring/assessment implementation independently of the benchmark case.

Required payload categories:

- `evaluator_id`;
- `version`;
- `implementation_sha256`;
- `result_contract`;
- `requires_human_review`.

Changing evaluator code changes its implementation digest even when the logical evaluator ID remains unchanged.

## TrialIdentity

`trial_identity` identifies one planned observation/repetition before execution.

Required payload categories:

- `layer` — `intrinsic`, `lab_tool`, `acl_system`, or `role`;
- `ordinal` starting at 1;
- optional `repeat_group`;
- BenchmarkInput reference;
- exact `case_id` within that benchmark input;
- exact EffectiveRuntimeConfig reference.

This prevents a runner from changing case-specific behavior-bearing settings after the experiment has been sealed. Repeated observations of one case/config get distinct trial identities rather than overwriting each other.

## RunManifest V2

`run_manifest` is an **immutable pre-run experiment definition**.

It binds:

- HostProfile;
- RuntimeProfile;
- ModelIdentity;
- one or more allowed EffectiveRuntimeConfigs;
- one or more BenchmarkInputs;
- one or more EvaluatorIdentities;
- one or more TrialIdentities, each already bound to one case/config;
- exact Benchmark Lab harness/source evidence.

Mutable fields such as `running`, `completed`, progress counters, current case, and failure state do not belong in this sealed manifest. They belong in checkpoint/run-state records. This prevents resume/recovery state from changing the identity of the experiment that was actually defined.

## CaseResult V2

`case_result` records the terminal outcome of one case/trial and binds it back to the immutable experiment definition.

Required payload categories:

- RunManifest reference;
- BenchmarkInput reference;
- TrialIdentity reference;
- `case_id`;
- terminal `status`;
- `started_at` and `finished_at`;
- `metrics`;
- `execution_evidence`;
- optional `terminal_output` descriptor.

Current terminal status vocabulary:

- `success`;
- `error`;
- `blocked`;
- `resource_limit`;
- `protocol_failure`.

Tool-capable execution will add detailed replayable events in BL-6 without changing this high-level binding rule.

## EvaluationResult V2

`evaluation_result` binds one CaseResult to one EvaluatorIdentity.

Required payload categories:

- CaseResult reference;
- EvaluatorIdentity reference;
- verdict (`pass`, `fail`, `review`, or `not_scored`);
- score and maximum score together, or both null;
- `hard_failures` separate from weighted score;
- detailed `checks`.

A high weighted score cannot erase a hard failure. Role-specific weighting will be layered on later without rewriting raw case/evaluation evidence.

## Qualification versus observation

These records establish evidence identity. They do **not** themselves declare that a host, runtime, model, or configuration is qualified.

Qualification is a decision based on evidence and a versioned acceptance policy. Keeping evidence separate from the qualification decision prevents a model/runtime from becoming "approved" merely because its metadata was successfully collected.
