# Worker Runtime Qualification

Date: 2026-10-02

This file records the runtime prerequisite for Worker qualification so future runs do not rediscover the same tool-transport failure.

## Qualified stack

- DeepSeek Harness: `0.1.6-alpha.2`
- Native Ollama plugin: `@zhangyi/dsh-llm-ollama 0.1.17`
- Provider path: DSH headless -> native Ollama plugin -> persistent Ollama daemon
- Initial runtime probe model: `qwen3.5:9b`
- Worker reasoning baseline: off where supported
- Context baseline: 32768
- Max output baseline: 8192

## Failure that invalidated the first Worker batch

The first broad Worker batch produced malformed tool-call arguments such as multiple JSON objects concatenated into one call. Both Qwen3.5 9B and Qwen3.8 27B showed the same failure family.

The failure was traced to native Ollama multi-tool stream assembly in plugin 0.1.17, not to Worker task reasoning.

Upstream issue:

- `1035041186/dsh-llm-ollama#2`
- Title: Native Ollama multi-tool calls can collapse into slot 0 because `function.index` is ignored.

Plugin 0.1.17 keyed streamed tool calls only from `call.index` and otherwise used slot 0. Ollama can provide the index under `call.function.index`. Distinct calls could therefore merge into one malformed call.

## Compatibility patch

Repository helper:

`benchmark/patch-dsh-ollama-multitool.ps1`

The patch is deliberately guarded:

- refuses DSH versions other than 0.1.6-alpha.2;
- refuses plugin versions other than 0.1.17;
- refuses an unexpected source layout;
- saves the untouched original under `local-state/runtime-backups/dsh-llm-ollama-0.1.17/`;
- is idempotent;
- supports `-Restore`.

Patched tool-call slot precedence:

1. `call.index`
2. `call.function.index`
3. `call.id`
4. slot 0 only when none of the above exist

Observed local hashes when first applied:

- original `lib/index.js`: `6a78e73025b0dafbc126de2f6e6ae9084f139e53fe19c46f2fd0fdb3cd02e6f3`
- patched `lib/index.js`: `6cac702d72881b25de15719b31a9a7d2f9d141e1afd284fb924501733d77a565`

A plugin reinstall or upgrade may replace this local patch. Worker runners therefore verify the qualified DSH version, plugin version, and compatibility-patch markers before model execution.

## Runtime preflight

Command:

`benchmark/run-dsh-ollama-multitool-preflight.cmd`

The preflight intentionally exposes only the filesystem read tool and asks Qwen3.5 to issue three reads in one assistant tool-calling response.

Qualified result:

- process completed: PASS
- turn completed: PASS
- exactly three read calls: PASS
- arguments remained separate and valid: PASS
- exactly three completed tool results: PASS
- exact terminal answer: PASS
- no malformed-argument / Ollama replay error: PASS

Observed calls:

- `alpha.txt`
- `beta.txt`
- `gamma.txt`

The permission service emitted a pending warning because shell was deliberately disabled in this read-only preflight. The warning did not block the three read calls and is not treated as a failed read-tool qualification.

## Worker execution smoke

After the transport fix, `benchmark/run-worker-qualification-test01.cmd` passed end-to-end with Qwen3.5 9B.

Validated behavior:

- role turn completed;
- dispatch turn completed;
- only `reporting/config.py` changed;
- no unauthorized file changed;
- no file created or deleted;
- required config behavior passed;
- existing regression tests passed;
- handoff note was present.

This establishes the execution interface prerequisite for comparative Worker Test 01.

## Worker tool overlay

The Worker overlay follows the historically proven DSH shape:

- `tools.mode: native`;
- explicit `workspace-write` sandbox;
- explicit permission preset;
- `approval: never`;
- filesystem sandbox;
- PowerShell sandbox;
- filesystem, filesystem-search, and PowerShell tools enabled;
- delegation, web, and background jobs disabled.

Role establishment remains tool-free. The Worker tool overlay is applied only on the bounded dispatch turn.

## Qualification interpretation

A provider/tool transport failure is not automatically a model Worker failure.

Preserve separate observations for:

- semantic tool selection;
- argument correctness;
- provider/parser compatibility;
- end-to-end task success.

Do not use results from the invalid pre-patch Worker batch as candidate qualification evidence.
