"""Reuse V2 Ollama identity/configuration, tools and role conversation unchanged."""
from __future__ import annotations
import hashlib
import math
from pathlib import Path
import time
from .packet import snapshot, write_json

ROLE_FILES = {
    "planner": ("local-model-bench/benchmark/planner/ROLE_PROMPT.txt", "054b0083b150f3ef0f8e65934569af910e22d0d6"),
    "governor": ("local-model-bench/benchmark/governor/ROLE_PROMPT.txt", "50f43f27335023df08f6d4f9cd52ce03bdf21ff7"),
    "worker": ("local-model-bench/benchmark/worker/ROLE_PROMPT.md", "356c28b0b4067c401299b56d7b96e64c1d728c79"),
    "tester": ("local-model-bench/benchmark/tester/ROLE_PROMPT.md", "0a0cf8734e6c432efa97ab75411112747eaab5f7"),
    "reviewer": ("deepseek-lab/native-lab/reviewer-role.md", "6fc76cd5a7b1f0c54d2e31b2474d3af41fcbd31e"),
}


class OllamaSessions:
    def __init__(self, repo, run, model, *, context_tokens=32768, max_output_tokens=8192,
                 timeout_seconds=600, keep_alive_seconds=3600):
        if type(context_tokens) is not int or context_tokens < 1 or type(max_output_tokens) is not int or max_output_tokens < 1:
            raise ValueError("Token limits must be positive integers")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0 or not math.isfinite(keep_alive_seconds):
            raise ValueError("Invalid timeout or keep-alive")
        # Lazy imports keep prepare/validate/assess independent of any provider.
        from localbench.v2.ollama_role_campaign import build_foundation
        from localbench.v2.orchestrator import EvidenceStore
        self.repo, self.run, self.model = Path(repo), Path(run), model
        self.options = dict(context_tokens=context_tokens, max_output_tokens=max_output_tokens,
                            timeout_seconds=timeout_seconds, keep_alive_seconds=keep_alive_seconds)
        self.session_counter = 0
        self.store = EvidenceStore(self.run / "evidence")
        self.foundation, self.observed = build_foundation(
            repo_root=self.repo, store=self.store, base_url="http://127.0.0.1:11434",
            model_name=model, context_tokens=context_tokens)
        write_json(self.run / "runtime-observation.json", self.observed)

    def __call__(self, *, role, case_id, prompt, workspace, writable, evidence):
        from localbench.v2.configuration import resolve_effective_configuration
        from localbench.v2.ollama_role_campaign import generation_spec
        from localbench.v2.ollama_driver import OllamaChatDriver, ollama_adapter_resolution
        from localbench.v2.flashnext_role_harness import (
            RoleConversation, ROLE_TOOL_DEFINITIONS, ROLE_TOOL_SCHEMA_SHA256, ROLE_SURFACE_ID)
        from localbench.v2.tool_harness import BoundedWorkspace
        evidence = Path(evidence); evidence.mkdir(parents=True, exist_ok=False)
        relative, expected = ROLE_FILES[role]
        setup_path = self.repo / "campaigns/flashnext-all-roles-v1/sources" / relative
        raw = setup_path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        if blob != expected:
            raise ValueError("Pinned role setup source changed: " + relative)
        (evidence / "setup.txt").write_bytes(raw)
        (evidence / "dispatch.txt").write_text(prompt, encoding="utf-8")
        scope = None
        if workspace is not None:
            paths = sorted(set(snapshot(workspace)) | set(writable))
            scope = BoundedWorkspace(Path(workspace), readable_paths=paths, writable_paths=writable)
        self.session_counter += 1
        session_number = self.session_counter
        counter = 0
        reasoning = "boolean" if "thinking" in self.observed["capabilities"] else "unsupported"

        def driver(request):
            nonlocal counter
            remaining = session.deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Role task time budget expired")
            counter += 1
            options = {**self.options, "timeout_seconds": min(self.options["timeout_seconds"], remaining)}
            spec = generation_spec(**options, reasoning_transport=reasoning)
            if request.tools:
                spec["tool_surface"] = {"id": ROLE_SURFACE_ID, "tools": [t["name"] for t in ROLE_TOOL_DEFINITIONS],
                                        "max_tool_calls": 40, "schema_sha256": ROLE_TOOL_SCHEMA_SHA256}
            adapter = ollama_adapter_resolution(spec, runtime=self.foundation["runtime"],
                                               model=self.foundation["model"], reasoning_transport=reasoning)
            effective = resolve_effective_configuration(
                f"a001-{case_id}-{session_number:03}-{counter:03}", runtime=self.foundation["runtime"],
                model=self.foundation["model"], spec=spec, adapter_resolution=adapter)
            self.store.persist(effective)
            session.event("assistant001_effective_config", effective.reference.to_dict())
            return OllamaChatDriver(effective)(request)

        class ObservedConversation(RoleConversation):
            def event(self, kind, payload):
                super().event(kind, payload)
                if kind in ("model_request", "model_response", "model_error", "tool_request", "terminal_output"):
                    print(f"[{case_id}] {kind}", flush=True)

        session = ObservedConversation(case_id=case_id, setup_driver=driver, driver=driver,
                    workspace=scope, evidence_dir=evidence,
                    timeout_seconds=self.options["timeout_seconds"], max_tool_calls=40,
                    max_model_turns=48, test_timeout_seconds=120)
        # Exact historical setup text, actual acknowledgement, fresh task history.
        # No invented setup/handoff formatting requirement is added.
        if session.establish(raw.decode("utf-8"), None):
            session.dispatch(prompt)
        (evidence / "final.txt").write_text(session.final, encoding="utf-8")
        authority_violations = sum(1 for e in session.events
            if e["event_type"] == "tool_authorization" and not e["payload"]["allowed"]
            and e["payload"]["reason"] != "invalid_arguments")
        result = {"status": session.status, "stop_reason": session.stop_reason,
                  "runtime_compatibility": session.compatibility, "final_response": session.final,
                  "metrics": session.metrics(), "authority_violations": authority_violations,
                  "setup_sha256": hashlib.sha256(raw).hexdigest(), "role": role,
                  "test_tool_calls": len(session.test_calls)}
        write_json(evidence / "session-summary.json", result)
        return result
