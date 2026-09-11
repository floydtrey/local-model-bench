# Benchmark Lab V2 Ollama Driver

**Status:** deterministic source qualification; no real model execution required

## Purpose

`localbench.v2.OllamaChatDriver` maps a sealed `EffectiveRuntimeConfig` and a
normalized `ModelTurnRequest` to Ollama's non-streaming `/api/chat` contract. The
driver is deliberately narrow: it accepts only an exact
`benchmark-lab-ollama-chat:v1` adapter resolution bound to the same runtime and
model identities as the effective configuration.

The adapter seals the provider origin, model tag, generation options, structured
output format, reasoning control, timeout, model residency, context-delivery
contract, and tool-conversion contract before execution. The driver rejects an
unknown, incomplete, degraded, or identity-mismatched resolution.

## Canonical campaign settings

The initial tower qualification profiles use:

- context tokens: `32768`;
- maximum output tokens: `4096`;
- temperature: `0`;
- seed: `42`;
- top-p: `1`;
- retries and retry delay: `0`;
- concurrency: `1`;
- timeout: `600` seconds;
- network policy: `provider_only`;
- non-streaming chat;
- model residency: `unload_after_model` with Ollama `keep_alive: 0`.

Reasoning remains model-and-configuration behavior, not a claim that different
families implement an identical internal mechanism:

| Candidate tag | Canonical reasoning | Ollama transport |
| --- | --- | --- |
| `qwen3.5:9b` | enabled, no effort | boolean `think: true` |
| `gemma4:12b` | enabled, no effort | boolean `think: true` |
| `qwen2.5-coder:7b` | unsupported | `think` omitted |
| `gpt-oss:20b` | enabled, medium | string `think: "medium"` |
| `qwen3.6:27b` | enabled, no effort | boolean `think: true` |
| `qwen3-coder:30b` | enabled, no effort | boolean `think: true` |
| `qwen3.6:35b` | enabled, no effort | boolean `think: true` |

## Normalization behavior

- `text` omits Ollama `format`, `json_object` maps to `"json"`, and
  `json_schema` maps to the exact schema object.
- Inline context assets become one deterministic system message after the
  case-authored leading system messages. Asset IDs, digests, media types, and
  UTF-8 bytes remain visible in the request.
- Neutral tool definitions map to Ollama function tools. Tool results are
  canonical JSON messages with an explicit `tool_name`.
- Provider tool calls receive deterministic per-turn call IDs because Ollama's
  response contract does not supply the neutral harness call ID.
- Provider thinking text, terminal text, tool calls, timing/token metadata, and
  the raw provider-response digest are retained in the normalized response.
- For a multi-turn tool exchange, the provider's prior thinking field is returned
  through the normalized assistant message and mapped back to Ollama as `thinking`.

## Qualification boundary

The unit tests use an in-process fake HTTP endpoint. They do not contact the tower
runtime or load a model. A later, separately authorized gate must seal the seven
candidate-specific effective configurations and make one non-scored request to
qualify the installed Ollama version against this driver. Scored runs remain
unauthorized until that evidence passes.
