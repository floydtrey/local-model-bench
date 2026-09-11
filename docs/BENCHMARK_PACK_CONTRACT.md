# Benchmark Pack V2 Contract

**Contract version:** `benchmark-lab-pack:v2`

**Construction task:** BL-5A

## Purpose

A Benchmark Pack is the portable definition of future benchmark content. It describes what a case requires without embedding provider-specific request fields, runtime defaults, ACL authority, or evaluator implementation code.

The pack is intentionally independent of where it is stored. Public generic packs may live in this repository; private ACL-derived or production-derived packs may live elsewhere and use the same contract.

## Pack-level fields

Each pack declares:

- `schema_version` — exactly `benchmark-lab-pack:v2`;
- `pack_id` — stable human/operator-facing ID;
- `pack_version` — explicit version label;
- `name` — reporting label;
- `description` — string or null;
- `level` — exactly one of `L0`, `L1`, `L2`, `L3`, or `L4`;
- `cases` — ordered non-empty case definitions with unique IDs.

A pack uses one capability level. Mixed L0/L1/L2 behavior belongs in separate packs so harness semantics do not change from case to case invisibly.

## Exact source identity

The loader hashes the exact UTF-8 JSON source bytes before parsing them.

`source_sha256` therefore changes when exact bytes change, including whitespace, formatting, or locator edits. This is the reproduction identity used by V2 `benchmark_input` evidence.

The loader never substitutes a path, filename, pack ID, or version label for the exact source digest.

## Semantic identity

The loader also calculates `semantic_sha256` over normalized behavior-bearing pack content.

The semantic projection deliberately excludes:

- pack `name`;
- pack `description`;
- case reporting `tags`;
- context-asset `source_locator` values.

It retains behavior-bearing content such as:

- pack ID/version and level;
- model-visible messages;
- context-asset content digests and delivery mode;
- case objective;
- response requirements;
- tool requirements;
- configuration-profile requirement;
- evaluator contract references;
- hard-failure references;
- repetition policy.

This allows the lab to distinguish “the source file moved or was reformatted” from “the actual test changed.” Exact run evidence still keeps `source_sha256`.

## Case definition

Every case declares:

- `case_id`;
- `objective`;
- `input`;
- `requirements`;
- `evaluators`;
- `hard_failure_rules`;
- `repetitions`;
- `tags`.

Unknown fields fail closed.

### Candidate-visible messages

`input.messages` is an ordered array of role/content objects. Supported roles are:

- `system`;
- `user`;
- `assistant`.

The Benchmark Pack contract does not add provider-specific message fields.

### Context assets

`input.context_assets` references fixture bytes outside the case JSON.

Each asset declares:

- `asset_id`;
- exact content `sha256`;
- `media_type`;
- `delivery`;
- `source_locator`.

Supported delivery modes in BL-5A are:

- `inline_context`;
- `readonly_reference`.

The locator tells the executor where to obtain bytes. The digest identifies what bytes are expected. A moved private file therefore does not silently become a different fixture merely because its path changed.

BL-5A validates the declaration but does not materialize or authorize fixture access. That belongs to later execution infrastructure.

## Level constraints

### L0

L0 is prompt-only model behavior.

- context assets are forbidden;
- tool surface must be `none`;
- required tool list must be empty.

### L1

L1 may declare controlled context assets but does not enter the standardized tool loop.

- tool surface must be `none`;
- required tool list must be empty.

### L2-L4

L2 and above may declare a non-`none` tool-surface requirement. A non-`none` surface must name at least one required tool.

Declaring a tool surface does not grant authority or prove the harness exists. Later construction gates resolve and enforce it.

## Configuration requirements

A case references a provider-neutral `configuration_profile` and declares only case-specific requirements:

- `response_contract`;
- `tool_surface`;
- optional `minimum_context_tokens` represented explicitly as an integer or null.

The pack does not carry Ollama `options`, llama.cpp flags, Pydantic AI settings, provider URLs, GPU configuration, or hidden runtime overrides.

Before scored execution, BL-4 machinery must resolve the applicable profile plus runtime/model/provider mapping into one exact sealed `EffectiveRuntimeConfig`.

## Response contract

Supported response modes are:

- `text`;
- `json_object`;
- `json_schema`.

`json_schema` requires a schema object. Other response modes do not accept a schema object.

This expresses the output requirement without dictating how an individual provider maps it onto its API.

## Evaluator references

A case references evaluators by:

- `evaluator_id`;
- `contract_version`.

The pack does not contain evaluator Python code or an implementation digest. BL-5B will resolve these portable references to exact evaluator implementations and V2 `evaluator_identity` evidence before scored execution.

This keeps benchmark content separate from grading machinery.

## Hard failures

`hard_failure_rules` names evaluator-owned rules using:

- `evaluator_id`;
- `rule_id`.

Every hard-failure rule must point to an evaluator declared by that case. Duplicate rules fail validation.

Hard failures remain distinct from weighted scores. BL-5A only defines references; BL-5B defines their evaluation semantics.

## Repetition policy

Each case explicitly declares:

- `screen_trials`;
- `qualification_trials`.

Both are positive integers, and qualification trials cannot be fewer than screening trials.

The policy is part of semantic benchmark identity. A campaign may select the appropriate named phase, but it must not silently invent the number of trials after results begin.

## V2 evidence conversion

A loaded Benchmark Pack can produce existing V2 `benchmark_input` evidence.

For a V2 pack:

- `logical_id` is the stable `pack_id`;
- `suite_id` is rendered as `pack_id@pack_version` for human-visible version context;
- `source_sha256` is the exact source-byte digest;
- `level` is copied from the pack;
- `case_ids` preserve pack order;
- `source_format` is `benchmark-lab-pack:v2`;
- `source_locator` is optional and is not automatically populated from the local filesystem.

The final point is intentional: loading a private pack from a local path must not automatically leak that path into persisted/public evidence.

## Public/private storage

The contract does not require packs to live under the repository.

A private pack may be loaded from any authorized local location. Its `source_sha256`, semantic identity, case definitions, and referenced fixture digests work the same way as a public pack.

Whether raw pack bytes or fixture locators may be published is a separate artifact-policy decision.

## BL-5A non-goals

BL-5A does not:

- create real shared capability cases;
- implement evaluator logic;
- execute a provider/model;
- implement the bounded tool loop;
- grant file/network/process authority;
- resolve configuration profiles into provider requests;
- score a model;
- assign roles.

Synthetic case definitions in `tests/test_v2_benchmark_pack.py` exist only to prove the contract validator and are not benchmark content.
