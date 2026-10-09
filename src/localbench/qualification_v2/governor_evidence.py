"""Read existing sealed role evidence for comparable Governor trials; no execution."""
from __future__ import annotations

import json
import math
from pathlib import Path

from localbench.assistant001.runtime import ROLE_FILES
from localbench.v2.contracts import EvidenceRef, SealedEvidence, sha256_json
from .planner_packet import read_regular, sha


def captured_protocol(run, packet, session, repo):
    """Fail closed on absent/altered evidence; never infer config from a model tag.

    The role harness decreases the per-call timeout as its fixed case budget is
    consumed. Retain these observations, compare the same original case budget,
    and compare every other effective option exactly. No performance ranking is
    derived here. Different thinking transports deliberately form different groups.
    """
    run, repo = Path(run), Path(repo)
    identity = json.loads(read_regular(run / "runtime-identity.json"))
    inputs = json.loads(read_regular(run / "runner-inputs.json"))

    def load(value, expected_type):
        ref = EvidenceRef.from_dict(value)
        if ref.record_type != expected_type:
            raise ValueError("Wrong evidence type")
        path = run / "evidence/records" / ref.record_type / (ref.sha256 + ".json")
        record = SealedEvidence.from_dict(json.loads(read_regular(path)))
        if record.reference != ref:
            raise ValueError("Evidence reference mismatch")
        return record.to_dict()["payload"]

    foundation = {k: load(identity[k], t) for k, t in (
        ("runtime", "runtime_profile"), ("model", "model_identity"),
        ("host", "host_profile"), ("interface", "execution_interface_identity"))}
    if (foundation["interface"]["runtime"] != identity["runtime"]
            or foundation["interface"]["model"] != identity["model"]
            or inputs["model"] != foundation["model"]["name"]
            or inputs["transport"] != "direct_ollama"
            or inputs["host_execution_authorized"] is not False):
        raise ValueError("Captured foundation/configuration binding mismatch")
    if not (foundation["model"].get("provider_digest") or foundation["model"].get("artifact_digest")):
        raise ValueError("Exact model artifact/provider digest is missing")
    evidence = run / "roles/governor"
    setup = read_regular(evidence / "setup.txt")
    canonical_setup = read_regular(repo / "campaigns/flashnext-all-roles-v1/sources" / ROLE_FILES["governor"][0])
    if setup != canonical_setup or sha(setup) != session.get("setup_sha256"):
        raise ValueError("Role setup mismatch")
    if read_regular(evidence / "dispatch.txt").decode("utf-8").replace("\r\n", "\n") != packet["prompt"].replace("\r\n", "\n"):
        raise ValueError("Dispatch evidence differs from frozen prompt")
    events = [json.loads(line) for line in read_regular(evidence / "events.jsonl").splitlines()]
    requests, responses, configs, terminals, timeouts, sequence = [], [], [], [], [], []
    budget = inputs["timeout_seconds"]
    if not isinstance(budget, (int, float)) or isinstance(budget, bool) or not math.isfinite(budget) or budget <= 0:
        raise ValueError("Invalid case time budget")
    for ordinal, event in enumerate(events, 1):
        digest = event.pop("event_sha256", None)
        if event.get("sequence") != ordinal or sha256_json(event) != digest:
            raise ValueError("Role event integrity mismatch")
        kind, payload = event["event_type"], event["payload"]
        if kind in ("model_request", "model_response", "assistant001_effective_config", "terminal_output"):
            sequence.append(kind)
        if kind == "tool_request":
            raise ValueError("Tool attempts are outside this controlled Governor protocol")
        if kind == "model_request":
            if payload.get("case_id") != packet["case_id"] or payload.get("tools") or payload.get("context_assets"):
                raise ValueError("Wrong case or unexpected candidate exposure")
            requests.append(payload)
        elif kind == "model_response":
            if payload.get("tool_calls"):
                raise ValueError("Tool response outside no-tools protocol")
            responses.append(payload)
        elif kind == "terminal_output":
            terminals.append(payload.get("content"))
        elif kind == "assistant001_effective_config":
            config = load(payload, "effective_runtime_config")
            if config["runtime"] != identity["runtime"] or config["model"] != identity["model"]:
                raise ValueError("Effective configuration identity mismatch")
            settings = config["settings"]
            adapter = settings["adapter_resolution"]
            request = adapter["effective_request"]
            if (settings["comparison_mode"] != "strict" or adapter["status"] != "exact" or adapter["deviations"]
                    or config["tool_surface"]["id"] != "none" or config["tool_surface"]["tools"]
                    or request["model"] != inputs["model"] or request["model_sha256"] != identity["model"]["sha256"]
                    or request["runtime_sha256"] != identity["runtime"]["sha256"]
                    or settings["generation"]["context_tokens"] != inputs["context_tokens"]
                    or settings["generation"]["max_output_tokens"] != inputs["max_output_tokens"]):
                raise ValueError("Effective settings differ from declared controlled protocol")
            timeout = config["limits"].pop("timeout_seconds")
            if not 0 < timeout <= budget or request.pop("timeout_seconds") != timeout:
                raise ValueError("Invalid remaining timeout evidence")
            timeouts.append(timeout)
            # Exact model identities vary across contestants, never their config.
            request.pop("model")
            request.pop("model_sha256")
            config.pop("model")
            configs.append(config)
    expected_sequence = ["model_request", "assistant001_effective_config", "model_response"] * 2 + ["terminal_output"]
    if (sequence != expected_sequence or len(requests) != 2 or len(configs) != 2 or configs[0] != configs[1]
            or len(responses) != 2 or responses[-1].get("content") != session.get("final_response")
            or terminals != [session.get("final_response")]
            or requests[0]["messages"] != [{"role": "user", "content": setup.decode("utf-8")}]
            or len(requests[1]["messages"]) != 3
            or requests[1]["messages"][0] != requests[0]["messages"][0]
            or requests[1]["messages"][1].get("role") != "assistant"
            or requests[1]["messages"][1].get("content") != responses[0].get("content")
            or requests[1]["messages"][2] != {"role": "user", "content": packet["prompt"]}):
        raise ValueError("Expected fresh setup and single no-tools dispatch evidence")
    protocol = {"effective_config": configs[0], "case_timeout_seconds": budget,
                "role_setup_sha256": sha(setup), "host_facts_sha256": foundation["host"]["facts_sha256"],
                "transport": "direct_ollama", "session_policy": "fresh setup + one text-only dispatch"}
    return {"identity": identity, "inputs": inputs, "protocol": protocol,
            "effective_timeout_observations": timeouts, "model_identity": identity["model"]}
