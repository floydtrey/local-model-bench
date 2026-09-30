# Independent Inspect screening: cancelled-run postmortem

**Run:** September 28–30, 2026. **Status:** cancelled by the user; not a qualified model-selection benchmark.

## Why we attempted this

The objective was to identify candidates for governor, planner, reviewer, coding, routing, and user-facing intent roles on the user's workstation. Existing ACL, DeepSeek Harness, and custom control policies were not trusted as neutral measures of model capability. An established independent evaluation environment was meant to help distinguish model limitations from restrictions or defects introduced by our own software.

The longer-term purpose was to inform the future governing system: different models may require different prompts, autonomy, tools, and control policies. The goal was not a universal model winner or a single global controller. A finite test can establish demonstrated performance under specified conditions, not an absolute capability ceiling.

## What we actually ran

The earlier preparation expanded into custom role tasks, graders, audits, review gates, and extensive validation. The user objected to the scope and resource cost. We then overcorrected: we reduced execution to three native Inspect tasks but did not preserve adequate coverage of the original role-selection objective. The custom role suite was retained locally as reference and **was not used in this run**.

Execution path: **Inspect AI 0.3.266 → OpenAI-compatible HTTP → local llama.cpp server → existing GGUF**. Native tasks came from `inspect-evals` 0.21.0. This did not execute the repository's older custom benchmark harness, ACL, DeepSeek Harness, or Ollama inference. Ollama's on-disk GGUF blobs supplied most of the files. Qwen3.5 9B used an existing Bartowski Q4_K_M GGUF recovered from prior successful runtime logs after a different Ollama artifact failed metadata compatibility. No model conversion was performed.

The recorded workstation was an RTX 5060 Ti 16GB, Core i7-14700F, and 64GB RAM. Normal runtime: llama.cpp-mindshub build 10955 / `2f539596c`; Flash-Next: its existing CUDA fork build 10818 / `27c54b4bb`. Models retained recorded sampling profiles; this was not a controlled sampling or tuning comparison.

| Native task | Selection | Scoring scope |
|---|---|---|
| ARC Challenge | First 20 samples | Multiple-choice science answers |
| BBH logical_deduction_five_objects | First 20 samples; zero-shot prompt | Multiple-choice ordering deductions |
| IFEval | First 20 samples | Mechanical instruction constraints; strict prompt-level pass reported below |

Each selected sample had two fresh attempts. A third attempt was intended if either valid attempt failed; infrastructure errors were not intended to count as model failures. Planned initial work: 19 configurations × 60 questions × 2 attempts = 2,280 responses. These were small fixed subsets, not full benchmark reproductions or a held-out role assessment.

After an 18-response native path check on Qwen3.5 9B, a user-authorized batch/Python launcher was added to load one model, wait for readiness, invoke native Inspect commands, unload it, and continue. Inspect retained task execution, scoring, and evaluation logs. The launcher owned process sequencing and conditional third-attempt selection; it was additional custom code, although not a replacement evaluation framework.

Each normal server explicitly requested the model's declared context with automatic memory fitting enabled. Generation and reasoning budgets were unrestricted (`--predict -1`, `--reasoning-budget -1`); Inspect added no output or task-time cap. No 4K/8K lock was used. This configured a different execution path; it did not fix or override limits in the earlier assistant system. Full allocated context was not equivalent to a large input test: the largest recorded input was only 259 tokens.

KC/lab isolation was checked at launch. It was not continuously verified. The simplified run did not retain the continuous resource telemetry designed earlier.

## Recorded outcomes, not a role ranking

The following are raw native scores, preserved for traceability. They must not be interpreted as evidence of dependable planning, governance, coding, tool use, or deployment readiness. Counts are correct responses out of the initial attempts; missing third attempts are excluded. Times sum logged sample durations and exclude model loading and inter-task overhead. Context values are confirmed server allocations, not peak GPU-memory measurements.

| ID / model | ARC | Logic | Instructions | Recorded evaluation minutes | Allocated context |
|---|---:|---:|---:|---:|---:|
| C01 Flash-Next UD-IQ3_XXS | 40/40 | 40/40 | 38/40 | 67.6 | 262144 |
| C02 qwen3:0.6b | 23/40 | 22/40 | 20/40 | 21.3 | 40960 |
| C03 gemma3:1b | 5/40 | 2/40 | 14/40 | 1.0 | 32768 |
| C04 llama3.2:1b | 18/40 | 8/40 | 20/40 | 0.9 | 131072 |
| C05 qwen2.5-coder:7b | 33/40 | 20/40 | 19/40 | 2.9 | 32768 |
| C06 qwen3.5:9b | 40/40 | 40/40 | 40/40 | 65.5 | 262144 |
| C07 gemma4:latest | Load failed | Load failed | Load failed | 0.0 | — |
| C08 gemma4:12b | 39/40 | 40/40 | 37/40 | 269.5 | 262144 |
| C09 gemma4:12b-it-q8_0 | 40/40 | 40/40 | 38/40 | 254.2 | 262144 |
| C10 gpt-oss:20b | Load failed | Load failed | Load failed | 0.0 | — |
| C11 qwen3.6:27b | 40/40 | 40/40 | 39/40 | 567.4 | 262144 |
| C12 qwen3.8:27b | 40/40 | 40/40 | 38/40 | 213.7 | 262144 |
| C13 qwen3-coder:30b | 36/40 | 36/40 | 35/40 | 23.0 | 262144 |
| C14 qwen3.6:35b | 40/40 | 40/40 | 39/40 | 57.8 | 262144 |
| C15 laguna-xs-2.1:latest | 35/40 | 40/40 | 32/40 | 39.0 | 262144 |
| C16 muse-glimmer:latest | 35/40 | 36/40 | 37/40 | 142.3 | 131072 |
| C17 granite4.2:30b | 30/40 | 34/40 | 9/9 partial | 438.7 | 131072 |
| C18 Nemotron 3.5 Lightning 30B | Not reached | — | — | — | — |
| C19 North Mini Code 1.0 | Not reached | — | — | — | — |

## What actually happened

The launcher recorded interruption at September 30, 06:51:12 America/Chicago. There are 1,769 logged responses: fourteen models completed 120 responses each and Granite recorded 89 before interruption. C07 and C10 failed loading; C18 and C19 were not reached. The process-name check during review found no llama-server process.

Every recorded response has one Inspect model event. Completed evaluations used the same sample-ID sets across models. This was not a hidden multi-turn agent workflow or repeated model-retry loop. Nevertheless, time inside an evaluation was not necessarily productive time. My earlier description of approximately 99% evaluation time should not have been used to reassure the user that the run was efficient.

## Confirmed pathological outputs

| Model / sample | Observed behavior | Time |
|---|---|---:|
| Gemma4 12B Q4 / IFEval 1069 epoch 1 | Asked for a 500+ word meeting email with two keywords and no commas. Reasoning degenerated into repeated arithmetic such as `11 + 11 + 13 + 12`. Generated 262,083 output tokens, filled the 262,144-token context, returned no final answer. Native stop reason: `max_tokens`; strict score: failed. | 116.2 minutes |
| Qwen3 0.6B / IFEval 1040 epoch 1 | Resume request; final output degenerated into repeated escaped quote characters. Filled 40,960-token context. | 5.51 minutes |
| Qwen3 0.6B / IFEval 1087 epoch 2 | Output reached the 40,960-token context; final text alone was 220,484 characters. Strict score failed. | 5.50 minutes |
| Qwen3 0.6B / IFEval 1108 epoch 1 | Kannada-only answer request; filled context during generation and produced no final answer. | 5.50 minutes |

These four context-exhausted responses consumed 132.7 minutes in total. Their `max_tokens` stop reason reflects reaching the available context under this configuration, not an introduced 2K/4K output cap. They were scored as instruction failures, not passes. There is no evidence here that an EOS/parser defect caused them; establishing the initiating cause would require a separate investigation. The saved content directly establishes repetition for the Gemma arithmetic and Qwen quote cases.

Granite IFEval 1021 epoch 1 took 39.62 minutes to produce a two-paragraph uppercase critique. It generated 9,964 output tokens, with 36,519 characters of reasoning and a 985-character final answer. The reasoning repeatedly revisited whether capital `A` satisfied the uppercase requirement. It stopped normally and passed the mechanical checks. That is a scored pass with very poor efficiency, not a timeout.

Other slow cases also terminated normally: Qwen3.6 27B's longest response took 26.57 minutes for 8,659 output tokens; Gemma4 Q8's took 15.96 minutes for 13,525. Qwen3.5 9B's longest took 2.01 minutes for 7,820. The four context-exhausted cases do not explain the entire duration. Both substantial reasoning output and low observed throughput contributed.

## Test and launcher limitations

- The suite comprised the first 20 examples of ARC Challenge, one BBH logical-deduction subset, and IFEval, each twice. Several models saturated the small reasoning sample. No representative full-dataset claim is justified.
- IFEval scores specified mechanical constraints. A requested Wikipedia summary was supplied without a browsing tool or source text; satisfying formatting did not establish factual accuracy. Coding, tools, planning, delegation, governance, control-policy comparison, and concurrent responsiveness were not tested.
- Model-specific sampling profiles were reused, not optimized or experimentally controlled. The earlier assistant evaluation also used a different runtime/artifact and output budget. Differences cannot be attributed to the model or one setting alone.
- Third-attempt commands combined `--sample-id` with a YAML `limit: 20`. Inspect rejected this before producing an evaluation log. This is our launcher defect; mocked tests failed to exercise the real CLI argument interaction. The consistency protocol was therefore incomplete.
- Execution status `success` means the evaluation completed; it does not imply a useful answer, a correct answer, or a normal stopping reason. We should have reviewed longest outputs and stop reasons before treating the run as healthy.
- Avoiding arbitrary context/output locks was appropriate. It did not justify leaving obviously repetitive generation unexamined for hours. No settings or safeguards have been changed during this review.

## Hardware evidence and its limits

Recorded server properties confirm context allocation, and the saved model outputs confirm generation under those configurations. Gemma Q4 and Qwen 0.6B additionally reached the recorded full window, although with unusable content. This is useful capacity evidence for those exact combinations.

The normal launchers used automatic memory fitting with an explicitly set context. The retained properties record context but do not establish actual GPU/CPU layer distribution or peak RAM/VRAM. No continuous hardware telemetry was included in this simplified run. Therefore these logs do not prove GPU-only operation, memory headroom, optimal settings, or capacity/speed for two or three concurrent roles. KC/lab isolation was checked at launch, not continuously verified.

The two load failures were compatibility failures, not out-of-memory diagnoses:

- C07 Gemma4 smaller variant: `wrong number of tensors; expected 2131, got 720`.
- C10 GPT-OSS 20B: `unknown model architecture: 'gptoss'`.

## Disposition

Retain logs as configuration-specific load/context/throughput observations and failure examples. Do not use the score table to appoint roles or dismiss models, and do not interpret elapsed time as a hardware-only comparison. No restart, recovery run, model modification, runtime tuning, or new benchmark system was performed. The unresolved third-attempt launcher defect remains; the existing launcher should not be reused unchanged.

The local machine-readable review is `cancelled-run-review-evidence.json`. Raw model transcripts and machine-specific paths are retained locally, not published here. The hashes below identify the exact native logs reviewed; they are provenance identifiers, not downloadable attachments.

## Where we went wrong and what must change before another run

1. **Scope drift, then lost coverage.** We spent excessive preparation effort on custom infrastructure, then reduced the suite until it no longer addressed the intended roles. Reusing established software was correct; silently treating narrow proxies as sufficient was not.
2. **Insufficient end-to-end launcher validation.** The native path check exercised ordinary evaluations. Mocked lifecycle checks exercised switching and cleanup but missed the actual CLI conflict on third attempts. A successful mock was overstated as assurance that the workflow worked.
3. **Insufficient examination of generated content.** Repetition, empty final answers, stop reasons, and slow constraint checking should have been inspected before interpreting hours of activity as useful work. No arbitrary small output limit is prescribed as the remedy; runaway detection and intervention criteria must be explicit and model-appropriate.
4. **Misleading progress interpretation.** Reporting execution success or time inside evaluations was insufficient. The reports should have separated completion, correctness, useful output, abnormal stopping, and throughput. Perfect scores on these small subsets did not resolve earlier practical failures.
5. **Incomplete hardware attribution.** Allocation and successful generation are evidence; they do not establish actual placement, peak memory, headroom, or optimal concurrency. Runtime compatibility failures must not be labeled hardware-capacity failures.

The user considered hardware observations the only materially useful outcome. The assessment here preserves scores as an audit record, not a recommendation to use them for model selection. The run remains cancelled. No rerun, new framework, arbitrary context restriction, or recovery campaign is authorized by this document. Any future evaluation should begin with a bounded real role task and validate the actual execution path before committing a long hardware run.

## Evidence provenance

Run identifier: `all-20260928-173729-857012`. Started September 28 at 17:37:29 and interrupted September 30 at 06:51:12, America/Chicago (UTC−05:00), approximately 37 hours 14 minutes elapsed. The 1,769 recorded sample durations total approximately 36.08 hours; the difference includes load/startup intervals and interrupted work that did not become a completed sample, not just idle overhead.

This report was derived from the native `.eval` logs, saved server properties and launch arguments, per-model server logs, the launcher's summary, and third-attempt console errors. The review did not regenerate responses or rescore answers. Completed-task sample-ID sets were checked for agreement across models. There was one model event in each of the 1,769 recorded responses. Hardware specifications and earlier assistant-test settings came from existing project records.

<details><summary>Native evaluation log hashes</summary>

- `C01/arc/initial/2026-09-28T22-37-54-00-00_arc-challenge_QsJ3Nfh5erUCsJEed9iW7E.eval` — SHA-256 `319df509a227d61a7bcd190e886772a3f53248ccb65879502e1edb45f9794af5`
- `C01/instructions/initial/2026-09-28T22-56-36-00-00_ifeval_HCXGfQSfFM4ngaaDJt9EMZ.eval` — SHA-256 `6b75a5004327f9001b2d6b204e5cbd1d87e71e3e41414dbe19c568bc5eb6af57`
- `C01/logic/initial/2026-09-28T22-44-34-00-00_bbh_PPcc9fN25uobXX2RKvCkoh.eval` — SHA-256 `b036197c1a273e4f788b22f0c48bca120ec065a5ae0061a4ff41bc7859d222ef`
- `C02/arc/initial/2026-09-28T23-46-06-00-00_arc-challenge_kGmuDH8ZG2FBDDdoz54HzQ.eval` — SHA-256 `21b049bdd7a5c4ab0259210158f580a3377d85301b913961123563d33a390893`
- `C02/instructions/initial/2026-09-28T23-50-36-00-00_ifeval_dXwWzzRmAPACZyZHAJ8Ctf.eval` — SHA-256 `14048eff7082c5800846045bf9d8b42cde8ebceac8365072b7ceba2e9803471c`
- `C02/logic/initial/2026-09-28T23-47-16-00-00_bbh_Vc2RcvfcrAiKfgJN5eWwWX.eval` — SHA-256 `30d79555f3bac959a2cc87965cf2a9db5d08c56dc4e2f7b695e23ec18da359be`
- `C03/arc/initial/2026-09-29T00-08-04-00-00_arc-challenge_NXpLE6Kfx3qWCueZkwSszb.eval` — SHA-256 `f60c1c07c6e2913189ff06bc52ffb869f1e0f19a4850eae81a4dccf9f77e5c57`
- `C03/instructions/initial/2026-09-29T00-08-35-00-00_ifeval_ZSmyxJ2vgMWraTFwDQnHar.eval` — SHA-256 `b43f5944999c3fe80ae5f2e673e67815bfc4d6bdbbb64affae5ba98f0c7793db`
- `C03/logic/initial/2026-09-29T00-08-19-00-00_bbh_CVEjxsfhDRXooJHJ4mzdME.eval` — SHA-256 `7a339231a0253581b63514ba429fe8bd15576879647fcb4689f83d0ee2051f1a`
- `C04/arc/initial/2026-09-29T00-09-41-00-00_arc-challenge_Z3bAoV8mB7PPKYW7T9aZRE.eval` — SHA-256 `6b549330c244a98676de977d5c0a28500d3f212aeecda7439ab80b718cc84091`
- `C04/instructions/initial/2026-09-29T00-10-10-00-00_ifeval_93bRNwNy2v4PAqzk628KcX.eval` — SHA-256 `03e83c1466ec540c37e4a6d713b3af92b14bcc65b23213884964e62aabc6dce8`
- `C04/logic/initial/2026-09-29T00-09-56-00-00_bbh_56jwxeGaFQsoBiUgnhpEgX.eval` — SHA-256 `824bc1a207aaae41e5fc30b1388b6b4c167399e5fcbc8f1807a37e5ed76286d1`
- `C05/arc/initial/2026-09-29T00-11-26-00-00_arc-challenge_45Q42kZZbwXaHvgaFRVLqN.eval` — SHA-256 `a2fff88279d562c1e6400f7d332ed3ef13aa72ed6515cc2fc78bb16473197220`
- `C05/instructions/initial/2026-09-29T00-12-37-00-00_ifeval_mkpMY8ov5ueYw4qZjCoX9i.eval` — SHA-256 `bcfaec656795d0e7d2e8ed3d13ec84821194d849940ff804ed6585971ff21d9a`
- `C05/logic/initial/2026-09-29T00-11-45-00-00_bbh_bzozUC7pnsNCf3oG4VJLzH.eval` — SHA-256 `c93a5a094f43d66b6c992ee4ab754d5eaafdab0aa641a628ca53c09c5f245869`
- `C06/arc/initial/2026-09-29T00-15-06-00-00_arc-challenge_XYGGaisApKgcBH283T2xcu.eval` — SHA-256 `ef0b23886d8f3e9c6566e52ca4d8262b4934ecbe5eb853348abf894d2a0857f3`
- `C06/instructions/initial/2026-09-29T00-49-07-00-00_ifeval_kVNveww7HEbDmcV8XzG4Qg.eval` — SHA-256 `e65215e14186b9b6b094d7551adf35e1392935abafd41983f6ac038b1b17ce54`
- `C06/logic/initial/2026-09-29T00-28-22-00-00_bbh_GihBbbEadz8SqAaMHjjwVi.eval` — SHA-256 `11521358791b0d3696155813ad014157051b72b63f845cefb9661fd240f0ecd6`
- `C08/arc/initial/2026-09-29T01-21-15-00-00_arc-challenge_GeGiQXSgfUDAAUr996Tupu.eval` — SHA-256 `94156e8645cb4438d7be1da2c851e060815388acfbeca0d16f311ca9069b433e`
- `C08/instructions/initial/2026-09-29T03-06-01-00-00_ifeval_ZZXsB4dXeyYqMriuSBmA9G.eval` — SHA-256 `9e9148e11d3ee519d0dbbfbe60674af11dc60eb63a8c14fd5dc54481025e93bc`
- `C08/logic/initial/2026-09-29T01-50-26-00-00_bbh_FsMUYr2yCC9fVQTFvHzFF6.eval` — SHA-256 `7ccbf06199ac4c87b2268022d4378914590a30eaa10d0e9983f5255515936daf`
- `C09/arc/initial/2026-09-29T05-51-40-00-00_arc-challenge_3pNphuRK4Wqmexvgb4f2zD.eval` — SHA-256 `d1bb61d5b635a8e0bb48ff03bbd6c69218b3fe2834d03604b8d63b31235a0611`
- `C09/instructions/initial/2026-09-29T08-28-03-00-00_ifeval_26gGEmudkTDkiN3RLrFVZ6.eval` — SHA-256 `edb36fe07008efda5d33a01221a4f38ffdf00b65c95d9f4517add3513b22b61a`
- `C09/logic/initial/2026-09-29T06-38-51-00-00_bbh_j4hWV44Cdk2sRms7atPoij.eval` — SHA-256 `4a80e9a396cf61f61ab3339a9bea1990e47c9792658051fa79b3e8f007eec699`
- `C11/arc/initial/2026-09-29T10-06-57-00-00_arc-challenge_T3kDTj3MsP3dZrpETqRLVX.eval` — SHA-256 `15dc16da280fd76813d9952a1561bbc317b9e4113e11adebb19140011d942e57`
- `C11/instructions/initial/2026-09-29T14-47-06-00-00_ifeval_ZkjqBQGB7pkwcBS6jv5p4L.eval` — SHA-256 `2d87cd689b9bde87c7850b75f4943a823194cb724dc7c22b3dcf5dcb5c08f235`
- `C11/logic/initial/2026-09-29T11-30-24-00-00_bbh_Z88KAx85ZfABAJ86ZqQYtN.eval` — SHA-256 `d782d25670ec88ec2904e9c3de6aa06206d3adfdef95af4edd7c47a60d4082d0`
- `C12/arc/initial/2026-09-29T19-35-19-00-00_arc-challenge_UXi5Nqme7dzfhmAKf9QBLq.eval` — SHA-256 `e682ce5dda2fe0e5c889eabc11cc906b1702db6a6a08c8dc4b116bd9ef1a8493`
- `C12/instructions/initial/2026-09-29T20-32-24-00-00_ifeval_AP5TWU6GwSnjSnKmziMoKJ.eval` — SHA-256 `b3c5c9739051a8113c5e78be0cd51761fd4e15170ec2aeeff4c9a3a964f0ff4a`
- `C12/logic/initial/2026-09-29T19-54-16-00-00_bbh_C3xv6aenZhDTSYTf4Pxvph.eval` — SHA-256 `5a4191897ad583a68e414542d7faff4984745b832589b73dbe2c38a7fb2ac245`
- `C13/arc/initial/2026-09-29T23-16-26-00-00_arc-challenge_XAzBqiUNtzBvsahykhNsv5.eval` — SHA-256 `4effbe3e3eb7c7cad1ba29561c66347f9626e1453f6886ae3c3335fc40f3c803`
- `C13/instructions/initial/2026-09-29T23-32-56-00-00_ifeval_mhUN8HvRqdUy2mi7DVRN4B.eval` — SHA-256 `da14a184638072096a77faaaa40b3b026435abede7dc3f9d250db0e1dbed74c1`
- `C13/logic/initial/2026-09-29T23-19-40-00-00_bbh_BBKYjzVf7vJWajgBEHyg6g.eval` — SHA-256 `c3d0a581774e0d5518bba1ea516837a5ea9c354e270bcd9f6d536dbace873dd7`
- `C14/arc/initial/2026-09-29T23-40-27-00-00_arc-challenge_cWERKNLPmnMHu7GTTTJLWw.eval` — SHA-256 `8776fdc3e2ec89aef0b386f7904897d8f4ce3b41045bf7e440e13f8e04ceb8a7`
- `C14/instructions/initial/2026-09-30T00-08-44-00-00_ifeval_ELm2WGwhSqxqC7G6NHffJs.eval` — SHA-256 `a68e8d6e3efe7fa74253c39b35cb04bfcd4684e15a97c7d5988e3b536058bcd9`
- `C14/logic/initial/2026-09-29T23-50-08-00-00_bbh_g4fDdnvpfNLFcubPGdpvXc.eval` — SHA-256 `efbf5b0c964905e0c4bfd09d4b845323f77a519075ddab44d56cf1457cab51a2`
- `C15/arc/initial/2026-09-30T00-39-06-00-00_arc-challenge_G6tptLTEUnFqmvzR5vyxCU.eval` — SHA-256 `099eddc4772997003cf691577f27fd46129831f506a4db841553b97436e5652c`
- `C15/instructions/initial/2026-09-30T01-06-35-00-00_ifeval_HikPPQchfB3mA58zHyt73j.eval` — SHA-256 `9062f8dd73b3070b69d802983a0ab79d99d576fb89f643f99ce4c1a20a559b46`
- `C15/logic/initial/2026-09-30T00-47-35-00-00_bbh_7x22nATdirVsefXxX7p2AD.eval` — SHA-256 `fb56c0610f336c1af55991282bf1aa811d53e270a6a25524f2e516de325cb71a`
- `C16/arc/initial/2026-09-30T01-19-03-00-00_arc-challenge_2KzohN5ohCJa7A2uuhjmat.eval` — SHA-256 `0a0253ce79dea1456430f53320bf29fe19751691e945b3450d70500687a42262`
- `C16/instructions/initial/2026-09-30T02-23-00-00-00_ifeval_Z32KxPxVUwgUWMUxubY7gw.eval` — SHA-256 `2f5e41403b7bcdd0c3de7e747a40bdcd7f0a15736e18116619629ce667f68fbe`
- `C16/logic/initial/2026-09-30T01-40-00-00-00_bbh_L2y8A3hyvYrYyX9GStEiAV.eval` — SHA-256 `db5a06ed92eba2720319bc8ff6ed1f73183390667ded082376f31abd9d58bef3`
- `C17/arc/initial/2026-09-30T03-42-35-00-00_arc-challenge_3AcPAHcMgcDqNT8xqcfn9K.eval` — SHA-256 `f6ffb476f882089ab2989009e163988d4bc310a81001dbd506a5707537ab1b03`
- `C17/instructions/initial/2026-09-30T07-23-18-00-00_ifeval_CzJkBVJofG3Te2m6pXtewC.eval` — SHA-256 `3915409d4b8b6d99d49d1fa7cff146b9e8a8e722fffd7383ecd04996d3b2ed5e`
- `C17/logic/initial/2026-09-30T04-27-44-00-00_bbh_LpqqCQdmzqi8uYVnUXKXRS.eval` — SHA-256 `4b975a74fc441993558d2cceba0acbfbe8d96c6517edcad26d42f6b7a50f7333`

</details>
