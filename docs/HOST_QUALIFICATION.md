# Benchmark Lab V2 Host Qualification

**Status:** collector implemented; intended-host capture pending

**Model/provider execution:** not used

## Purpose

Host qualification records the machine/environment that later benchmark evidence depends on. It does not load a model, contact Ollama, or grant any ACL authority.

The collector is intentionally best-effort and evidence-preserving: unsupported or unavailable measurements remain `null`/empty rather than being inferred from product names.

## Local-only default

Host profiles default to:

```text
local-state/host-profiles/<logical-host-id>.json
```

`local-state/` is ignored by Git because raw host/runtime qualification data may contain machine-specific evidence. Publish only deliberately selected/sanitized artifacts.

## Capture command

After installing the repository into its virtual environment, capture the intended benchmark host with:

```powershell
.\.venv\Scripts\python.exe -m localbench.v2.host --id new-tower
```

To measure the storage volume containing a particular benchmark/model workspace:

```powershell
.\.venv\Scripts\python.exe -m localbench.v2.host `
  --id new-tower `
  --target-path C:\projects
```

The command prints:

- the output file path;
- `facts_sha256`, the stable measured-configuration fingerprint;
- `evidence_sha256`, the exact observation digest including collection time and volatile observations.

It does not contact a model endpoint.

## Captured categories

The current collector records:

- OS/system/release/version/edition/machine architecture;
- CPU model, physical cores when available, and logical cores;
- installed and currently available physical memory;
- GPU name, VRAM, driver version, and a non-secret device locator when available;
- benchmark target-volume total/free storage;
- Python implementation/version/compiler/architecture;
- observed NVIDIA driver CUDA capability and installed CUDA toolkit version when their command-line tools are available;
- active Windows power scheme;
- thermal state as `null` until a trustworthy bounded probe exists.

The collector deliberately does not capture hostname, MAC address, motherboard serial, disk serial, Windows product key, or account/user identity.

## GPU evidence precedence

For NVIDIA hardware, `nvidia-smi` is preferred because it can report VRAM and driver information directly from the NVIDIA stack.

If that probe is unavailable on Windows, the collector falls back to `Win32_VideoController` through PowerShell/CIM. The fallback may provide less reliable VRAM information on some systems, so the `probe_source` field is retained and later qualification policy may require a stronger observation for performance comparisons.

No GPU value is guessed merely from the card name.

## Stable fingerprint versus exact observation

Every HostProfile has two useful hashes:

### `evidence_sha256`

The outer sealed-record digest identifies the exact observation. It changes when `captured_at` or any captured value changes.

### `facts_sha256`

The stable host-configuration fingerprint excludes deliberately volatile observations:

- currently available RAM;
- currently free disk space;
- instantaneous thermal state.

It retains behavior-relevant configuration such as:

- OS/build;
- CPU/core topology;
- installed RAM capacity;
- GPU/VRAM/driver;
- storage volume capacity;
- Python environment;
- compute runtime versions;
- active power scheme.

Therefore two captures of the same configured machine may have different evidence digests but the same facts fingerprint.

## BL-3 acceptance gate

BL-3 is not complete merely because the collector exists.

Before the new tower is declared host-qualified:

1. run the deterministic repository tests on the intended checkout;
2. capture a HostProfile on the new tower;
3. inspect the profile for obviously missing/malformed critical measurements;
4. repeat the capture once without intentionally changing configuration;
5. confirm the two captures have the same `facts_sha256` unless a behavior-relevant fact actually changed;
6. retain both raw profiles locally as qualification evidence.

No model download or model request is required for this gate.

## Current limitations

- Windows is the intended first host; non-Windows collection is best-effort.
- Physical CPU-core count currently uses Windows CIM; other platforms may report it as null.
- NVIDIA telemetry has the strongest GPU path today; other Windows GPUs use the generic CIM fallback.
- Thermal telemetry is deliberately not invented and is currently null.
- This stage records host/compute-runtime facts only. Ollama/llama.cpp/Pydantic/model identity and effective behavior settings are separate V2 records handled by later construction tasks.
