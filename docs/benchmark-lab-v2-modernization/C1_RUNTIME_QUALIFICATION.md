# Stage C1 private runtime and optional API qualification

Prepared 2026-10-10. Scope is isolated development fixtures and dependency qualification, not service readiness, actual identity acceptance, model execution or deployment.

The [official full x64 Python3.15.0 archive](https://www.python.org/ftp/python/3.15.0/windows-3.15.0.json) matched SHA2566b1a3f885ce416cf3a68af203e62203664eb5224d8d0c1d2a1945fddec5c500b. Actual runtime: Python3.15.0, MSCv1951, AMD64; linked SQLite3.53.4, source ID2026-07-24 19:02:57 bf7c7f30031888f4e796e429ab3978879485813aaca6f641c7b33e4e09459bcc; SQLite DLL SHA2568a65064bad951ce2ed19104f125b6258fb6d770b01e9868637b89f808a6fbeff. Private module origins and real Tk startup were checked. A's default operational gate remains enforced; an authored DB reached schema10/WAL/FULL without validation_only.

A fresh private venv used the runtime's bundled pip26.2.1. Downloaded official wheels, inspected package METADATA/requirements, then installed offline with --no-index --require-hashes --only-binary=:all:. pip check passed. Resolver accepted the candidates without dependency overrides; Starlette was selected transitively rather than forced. The complete lock SHA256 is80cf8eaaeb216cec0e3e0a01f55a7a2bcbe9c0e318d2a1a6b62c4a9b87b3d8a0.

| Resolved package | Exact version |
| --- | --- |
| FastAPI | 0.143.0 |
| Starlette | 1.7.0 |
| Pydantic / core | 2.14.0 / 2.50.0 (cp315 Windows x64 wheel) |
| Uvicorn / h11 | 0.54.0 / 0.16.0 |
| AnyIO / idna | 4.15.1 / 3.20 |
| click | 8.5.0 |
| annotated-doc / annotated-types | 0.0.5 / 0.8.0 |
| typing-extensions / typing-inspection | 4.16.0 / 0.4.4 |
| opentelemetry-api | 1.45.1 |

OpenTelemetry API is a declared FastAPI dependency; no SDK/exporter or outbound telemetry destination was installed/configured. No Authlib/JOSE/login packages, HTTPX client or unrelated extras were used.

Seven initial runtime fixtures passed: retained localbench/module imports, strict nullable schemas and invalid types/nonfinite rejection, requests/error statuses, lifespan/OpenAPI schema, native SSE/Last-Event-ID, default DB gate/pragmas and real Tk. Uvicorn asyncio/h11 used an OS-selected ephemeral127.0.0.1 socket and shut down. This is harmless fixture serving, not another deployed Benchmark service. Source C1 additionally checks real Uvicorn lifecycle/SSE, default denial/no effects, native passivity and exact publication bindings.

Failures retained locally: ordinary sandbox network DNS denied before network permission; initial venv ensurepip failed writing to sandbox temp, corrected with process-scoped TEMP/TMP inside this workspace and a fresh venv; initial SSE fixture assumed compact JSON whitespace, corrected to parse/assert exact JSON semantics. Native Windows strict path resolution emitted a sandbox location warning and blocked one retained containment fixture; the authorized isolated regression run outside that sandbox passed without changing native guards or runtime files. Initial source snapshot omitted campaign/schema/validation fixtures and a crash test was launched from the wrong working directory; these harness gaps were corrected without changing retained tests. No failure was hidden or bypassed with validation_only/ignore-requires-python/forceful dependency overrides.

Primary inspection: [FastAPI pinned metadata](https://github.com/fastapi/fastapi/blob/0.143.0/pyproject.toml), [native SSE](https://fastapi.tiangolo.com/tutorial/server-sent-events/), [Starlette pinned metadata](https://github.com/Kludex/starlette/blob/1.7.0/pyproject.toml), [Pydantic pinned metadata](https://github.com/pydantic/pydantic/blob/v2.14.0/pyproject.toml), [Uvicorn pinned metadata](https://github.com/Kludex/uvicorn/blob/0.54.0/pyproject.toml), [Windows private runtime guidance](https://docs.python.org/3.15/using/windows.html), [venv](https://docs.python.org/3.15/library/venv.html), [pip hash enforcement](https://pip.pypa.io/en/stable/topics/secure-installs/). Upstream classifiers/CI alone did not establish the combined3.15 stack; these actual isolated fixtures do, within the stated coverage.

The full runtime and venv are private workspace files, not registered installations. No live registry, global PATH, launcher, global pip, model, queue, provider, runtime or settings changed. Runtime/wheels/raw transcripts stay local and are not uploaded. Only source, documentation and the hash lock are proposed for GitHub. The API lock targets CPython3.15 Windows x64; it is not a cross-platform lock or auth/production qualification.
