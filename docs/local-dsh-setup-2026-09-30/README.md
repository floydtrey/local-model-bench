# Local DSH benchmark setup reference

Captured September 30, 2026 for redesigning the benchmark lab from a chat without access to this Windows workstation. This is a sanitized observational snapshot, not a new harness, installation recipe, or approval to restore old limits. No model inference or service changes were performed while collecting it.

## Start here

The existing setup has **three distinct paths**. Do not conflate their results:

| Path | What it actually establishes |
|---|---|
| Current DSH `web` / `lab-native` | Configured model catalog, tools, foreground delegation, custom KC memory and execution guards. Configuration captured; not freshly end-to-end qualified here. |
| September 22 DSH `headless` synthetic test | A documented successful parent + two foreground workers using Qwen3.5 9B through Ollama. Exact historical settings and observable transcript excerpts are included. |
| September 28–30 Inspect run | Existing GGUFs through llama.cpp, including Flash-Next's fork. It did **not** use DSH. Confirms specific load/context/generation observations, not DSH integration or role reliability. See the separate cancelled-run postmortem. |

### Files by question

- **Models and provider definitions:** [dsh-home/settings.yaml](dsh-home/settings.yaml), [installed-versions.json](installed-versions.json).
- **Agents/subagents and tools:** [lab-native agent composition](dsh-home/.agent-presets/lab-native/agent.cordis.yml), its `preset.yml`, [shipped bundle snapshots](installed-bundles/), and the optional `kc-memory-test` preset.
- **Actual custom controls:** [LAB-CONTROLS.md](dsh-home/LAB-CONTROLS.md), the user instruction snapshot `dsh-home/AGENTS.md`, and [custom source snapshots](custom-extensions/). These describe the existing environment, not mandatory policy for the redesigned lab.
- **Web-search configuration and patch:** [web profile overlay](dsh-home/profiles/web/cordis.patch.yml), [web-search notes](web-search/README.md), installed code and a diff against its local backup.
- **Launch information:** the commands below; [verified Flash-Next server command](runtime/C01-inspect-verified-launch.json); [verified Qwen9B command](runtime/C06-inspect-verified-launch.json); original Flash-Next build and historical launch scripts under `runtime/flashnext-historical/`.
- **Successful agent run:** [synthetic example](successful-example/README.md), parent/child observable transcripts, prompt, two input files, result, and historical overlays.
- **Provenance:** [snapshot-manifest.json](snapshot-manifest.json) records original/export hashes and source locations. Local usernames are redacted. Inspect's model artifact roster is under `runtime/`.

## Installed runtime versus source checkout

The active installed CLI is `@deepseek-ai/dsh` **0.1.5-rc.2**, reached by `%APPDATA%\npm\dsh.cmd`, using Node **v24.21.0**. Its installed dependency tree is `%APPDATA%\npm\node_modules\@deepseek-ai\dsh\node_modules\@deepseek-ai\`.

The separate source checkout is `C:\AI\deepseek\deepseek-harness`, at `ddefc45fbc7f8e46dd73185e68295696d1297887` when inspected. Do not assume its APIs or docs are identical to the installed release. `custom-extensions/compaction-trial/runtime.mjs` explicitly resolves the installed runtime and rejects versions other than 0.1.5-rc.2. Newer DSH versions require revalidation; this packet does not prove compatibility with them.

The existing home is `%USERPROFILE%\.dsh`. Its web root `cordis.yml` is empty intentionally: shipped bundle patches (`dsh-base`, `dsh-web-app`) are composed first, followed by the user `cordis.patch.yml`, then command-line overlays. The empty root does not mean there are no tools. Profile plugin dependencies are in `dsh-home/profiles/web/package.json`.

## Provider and model facts

The live settings use Ollama's OpenAI-compatible endpoint at `http://127.0.0.1:11434/v1`, `api: openai-completions`, and `apiKeyEnv: DSH_NATIVE_LOCAL_OLLAMA_KEY`. The default is provider `ollama`, model `gemma4:12b-it-q8_0`, preset `lab-native`.

The full recorded model list is included, including older aliases. Many entries still have `maxTokens: 32768`; historical qualification aliases contain 2K/4K/8K output allowances and 4K/16K/32K contexts. These are **observed old configuration values, not recommendations or newly approved restrictions**. One `openai` provider entry labels Gemma's context as 132000 while the Ollama entry says 131072; preserve this discrepancy as a configuration issue, not proof of backend capacity.

`contextWindow` in a DSH model definition is not evidence that the server allocated that amount. Record the actual server/Ollama configuration, effective request, output allowance, reasoning mode, quantization, and stop reason. Earlier reasoning-off qualification required an explicit `reasoningEfforts.off: none` with `supportsReasoningEffort: true`; a blank mapping had not disabled reasoning. Other model families can require different mappings.

The failed Inspect run selected GGUF files directly. An Ollama package working through Ollama does not prove that its blob works through a particular llama.cpp build: the ordinary build rejected GPT-OSS architecture and a smaller Gemma tensor layout. The recovered Bartowski Qwen3.5 9B artifact worked where another Ollama artifact did not. Exact model files matter.

## Agent ownership, delegation and tool surface

DSH owns sessions, native parent/child relationships, tool execution, approvals, and persistence. The custom agent preset supplies scoped composition, not a replacement session engine. Its persona also injects the local user instruction and Lab control references.

The configured native preset exposes filesystem read/write/edit/search, foreground PowerShell on Windows, skills, goals, plan mode, user questions, todos, web tools, presentation, and job inspection/control. Availability is further restricted by actual permissions and guards. PowerShell and subagents have `enableRunInBackground: false`; listing jobs does not imply permission to launch background work.

Delegation uses `subagent` with `provider: spawn` and model-selection settings, plus `subagent_fork` with `provider: fork` inheriting the parent's route/history. Both are foreground one-shot in this preset. The current selectable child roster is:

- `ollama / gpt-oss:20b-32k`
- `ollama / qwen3-coder:30b-16k`
- `ollama / qwen2.5-coder:7b-32k`

Do not assume every catalog model is selectable as a child. Codex and Claude Code delegation rows are disabled; workflow and Ralph rows are also disabled. This configuration is not a verified concurrent three-role deployment.

The live preset adds custom progress, uncertain-effect, permission-boundary, result-review and KC memory behavior. Examples include four consecutive tool errors, repeated identical tool/argument/result checks, streaming repetition handling, and owner review commands. Tool-result pruning is configured separately (8192-character threshold, 4096-character head, 1024-character tail). Memory compaction is marked `auto: false`. These are control variables that can change benchmark results; they must not be mistaken for model behavior or silently removed when claiming to test this deployment.

The included 15 source modules are the recursively discovered static local dependencies of the configured custom plugin entry points. They are an implementation reference, **not a self-contained installation**: installed DSH packages, provisioned KC endpoints/credentials/state, and deployment path mapping are external. No credentials, state databases, ordinary sessions, browser cookies, or model weights are included.

## KC, remote access and isolation

The host overlay declares a KC MCP client at `http://127.0.0.1:8766/mcp`, `streamable-http`, 90-second tool-call timeout, reconnect enabled, and nonfatal startup errors. The original header obtains a scoped credential from a local file. The published overlay replaces that expression with `process.env.KC_BENCHMARK_KEY`; its value is intentionally absent. This is a documented redaction, not a changed live configuration.

The memory extension separately references local `state/server.json` and `state/credential.json`; those files are excluded. Their provisioned values are required to operate that integration. Cloudflare identity code is included as a dependency reference, with its deployed host replaced by `LAB_PUBLIC_HOST`; its Access settings and credentials are not supplied. External exposure is not required for a local benchmark.

The cancelled Inspect run kept KC/lab offline. A DSH test that invokes KC cannot honestly claim that same condition. Either explicitly test a supported isolated preset without those integrations, or run and disclose the services required by the live preset. Choosing between these is a design decision, not something this snapshot silently does.

## Existing launch interfaces

The installed CLI help confirms the supported profile entry points:

```powershell
# Existing web deployment, with its existing home/configuration:
& "$env:APPDATA\npm\dsh.cmd" --profile web

# Inspect profile CLI options without starting model work:
& "$env:APPDATA\npm\dsh.cmd" --help
```

No DSH process was found during the collection's process check. Consequently a live web host's current port and additional launch flags were not recovered or invented. Use the installed profile's help and existing deployment launcher to resolve them before a new run. The synthetic example documents a previously successful headless command.

`${USERPROFILE}` and `${QWEN_TEST_ROOT}` in exported snapshots are redaction markers. They are **not guaranteed to expand inside DSH YAML or JavaScript strings**. Map them explicitly when using files. Do not replace the live DSH home with this snapshot; it includes historical limits and depends on excluded provisioned state. No automatic installation script is provided.

## Flash-Next and llama.cpp

Fork: [thecodacus/llama.cpp](https://github.com/thecodacus/llama.cpp), revision `27c54b4bbcefadedcec6397477cc2e866c1db716`. Its source working tree was clean at collection. Binary: `C:\AI\FlashNext-Lab\build\cuda-13.3\bin\llama-server.exe`; CUDA toolkit: `C:\AI\FlashNext-Lab\tools\cuda-13.3`. The original build script records Visual Studio Build Tools and build switches.

Model: `unsloth/Qwen3.8-Flash-Next-GGUF`, revision `2c41bd2a0b3f51c503c11f1c7ed2e6bb34036beb`, UD-IQ3_XXS, three shards. The first GGUF shard is the load entry; all shards must remain present. The artifact set is about 82 GB on disk, not a claim that all weights fit in GPU memory.

The verified Inspect launch used the fork's mmap/lazy loading, `-ngl 99 -ncmoe 99`, Flash Attention, f16 KV cache, eight CPU threads, batch 256/microbatch 128, disabled asynchronous CPU scheduling, one slot, context 262144, Jinja, and DeepSeek reasoning serialization. Exact arguments, environment prefix and artifact paths are in `runtime/C01-inspect-verified-launch.json`. The original standalone launcher still contains `-c 8192`; it is included under **historical** for provenance and must not be mistaken for the verified full-context launch or a future recommendation. Expert-profile CSVs exist locally but were not enabled in the verified command; only hashes/sizes are included.

Flash-Next completed all 120 initial Inspect responses. This is a successful runtime example, **not a successful DSH agent trace**. The current DSH settings contain no Flash-Next provider/model registration. A DSH connection still needs a model definition targeting `http://127.0.0.1:8080/v1` and the server's actual alias (`C01` in the verified command; `flashnext-iq3` in the historical launcher), followed by request/reasoning/tool compatibility checks. No validated DSH Flash-Next configuration is being claimed or fabricated.

## What the redesign must resolve

Use DSH's supported profiles/presets/provider interfaces and session records. Preserve its ownership of execution and state. Determine which current control extensions belong in the experimental condition; define role tasks and independent behavioral checks; record actual backend capacity and effective model settings; validate native tool transport and parent/child completion. Verify the complete invocation path rather than just syntax or process exit.

The successful synthetic trace proves a small foreground delegation path only. It does not validate coding, reliable governance, persistent background workers, concurrent large contexts, or all model families. The cancelled screen likewise cannot supply those missing conclusions. Do not rerun that screen or restore its launcher as a prerequisite to the redesign.
