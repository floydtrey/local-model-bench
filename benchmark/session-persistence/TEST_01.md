# Session Persistence Test 01

## Purpose

Validate that DSH durable sessions can support multiple role-specific conversations on the same model without cross-session leakage, and that those sessions survive unloading the model and loading a different model in between.

This is a correctness test for session architecture, not a Worker-quality benchmark.

## Models

Primary model: `qwen3.5:9b`  
Alternate model: `llama3.2:1b`

The primary model is intentionally small/fast for this architecture proof. If this passes, the same test can later be rerun with the selected Worker/Reviewer models.

## Sessions

### Session A
Role: `WORKER_ALPHA`  
Marker: `A_MARKER_7319`  
Project: `HARBOR`

### Session B
Role: `REVIEWER_BETA`  
Marker: `B_MARKER_2846`  
Project: `ORCHID`

### Session C
Alternate-model load probe only.  
Role: `SWAP_GAMMA`  
Marker: `C_MARKER_9052`

## Sequence

1. Create Session A on the primary model.
2. Create Session B on the same primary model.
3. Resume A and verify exact A recall.
4. Resume B and verify exact B recall.
5. Explicitly stop/unload the primary model through Ollama.
6. Start Session C on the alternate model, proving another model was loaded and used.
7. Resume Session A on the primary model after the swap and verify exact A recall.
8. Resume Session B on the primary model and verify exact B recall.

## Pass conditions

- Session A recalls its own role, marker, and project before and after the model swap.
- Session B recalls its own role, marker, and project before and after the model swap.
- A output never contains B's marker.
- B output never contains A's marker.
- Session A and Session B retain distinct DSH session IDs.
- The primary model is confirmed absent from Ollama's loaded-model list after the explicit stop.
- The alternate model is confirmed loaded/used before the original model is resumed.
- DSH can resume A and B after the primary model has been unloaded.

Prompt/KV cache reuse is recorded when observable but is not required for correctness. A rebuilt inference context is acceptable as long as the durable DSH session reconstructs the correct logical history.
