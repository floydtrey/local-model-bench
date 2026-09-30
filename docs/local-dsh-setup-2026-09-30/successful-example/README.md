# Successful historical DSH foreground delegation

Date: September 22, 2026. DSH 0.1.5-rc.2, headless profile, Ollama Qwen3.5 9B test alias. Parent session `session-c3ca20ec-1ba4-4be1-b902-5065a5f3f669`; two native child sessions are included as observable transcript excerpts.

The prompt required exactly two read-only workers. One read `temperature.json` (`value: 88`) and reported HOT at >=85. The other read `disk.json` (`free_gb: 30`) and reported OK at >=5. The parent was instructed to use foreground calls and wait for actual results rather than calculate itself.

Both child transcripts contain a real `read` call and result. The parent transcript contains two `subagent` calls, child registration, returned worker results, and the final answer:

```json
{"temperature": "HOT", "disk": "OK"}
```

Recorded process result: exit 0, no timeout, **11.7 seconds** wall time. The native turn ended `completed`. This is a successful synthetic tool/delegation example, not a general correctness claim. The earlier background version ended before workers completed; foreground was a material change.

The included `profile.yml` and `subagents.yml` are the actual historical overlays. Their 16,384 context, 2,048 output allowance, 120-second request timeout, disabled automatic retries, restricted tools and no-approval policy are retained as evidence—not recommended settings for the redesigned lab. `Modelfile` records the historical alias configuration; there are no new weights in this packet.

The original test invoked the installed DSH CLI's `--profile headless` entry with both overlays, a dedicated DSH home, working directory set to the synthetic case folder, `DSH_PERMISSION_MODE=workspace-write`, `DSH_TELEMETRY_DISABLED=1`, and `QWEN_TEST_KEY` set to a non-secret local API placeholder. The runner imposed a separate 120-second process wait for this case. The actual success took 11.7 seconds, not that timeout.

Equivalent documented CLI shape, after explicitly provisioning the same test alias and mapping the example paths, is:

```powershell
# From the synthetic case directory, with a separately configured test DSH_HOME:
& "$env:APPDATA\npm\dsh.cmd" --profile headless --patch .\profile.yml --patch .\subagents.yml (Get-Content .\prompt.txt -Raw)
```

This command is documentation of the earlier invocation pattern; it was not rerun. Do not use the normal user home inadvertently. Exported paths are redacted markers and need explicit mapping. The three JSON excerpts retain sequence IDs and observable tool receipts, omit system/request frames and reasoning, and redact local account paths. They are readable excerpts, not replayable complete native session files. Original-source hashes are in the parent manifest.
