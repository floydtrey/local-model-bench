from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .models import BenchmarkCase, Suite
from .util import sha256_bytes, validate_id


CASE_HEADING = re.compile(r"^##[ \t]+Case:[ \t]*(?P<id>[^\r\n]+?)[ \t]*\r?$", re.MULTILINE)
META_COMMENT = re.compile(
    r"\A[ \t\r\n]*<!--[ \t]*localbench[ \t\r\n]+(?P<json>.*?)[ \t\r\n]*-->[ \t\r\n]*",
    re.DOTALL,
)


def _validate_evaluation(value: Any, case_id: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise ValueError(f"case {case_id!r} evaluation must be an object")
    if value.get("kind") not in {"plan", "task_set"}:
        raise ValueError(f"case {case_id!r} evaluation kind must be plan or task_set")
    if value.get("expected_status") not in {"ready", "blocked"}:
        raise ValueError(f"case {case_id!r} evaluation expected_status must be ready or blocked")
    requirement_ids = value.get("requirement_ids")
    if (
        not isinstance(requirement_ids, list)
        or not requirement_ids
        or any(not isinstance(item, str) or not item for item in requirement_ids)
        or len(requirement_ids) != len(set(requirement_ids))
    ):
        raise ValueError(f"case {case_id!r} evaluation needs unique requirement_ids")
    if int(value.get("max_items", 7)) < 0:
        raise ValueError(f"case {case_id!r} evaluation max_items cannot be negative")
    forbidden = value.get("forbidden_substrings", [])
    if not isinstance(forbidden, list) or any(not isinstance(item, str) for item in forbidden):
        raise ValueError(f"case {case_id!r} forbidden_substrings must be strings")
    semantic_checks = value.get("semantic_checks", [])
    if not isinstance(semantic_checks, list):
        raise ValueError(f"case {case_id!r} semantic_checks must be an array")
    for check in semantic_checks:
        if (
            not isinstance(check, dict)
            or not isinstance(check.get("label"), str)
            or not isinstance(check.get("any_of"), list)
            or not check["any_of"]
            or any(not isinstance(item, str) or not item for item in check["any_of"])
        ):
            raise ValueError(f"case {case_id!r} has an invalid semantic check")


def _messages(case: dict[str, Any], case_id: str) -> list[dict[str, str]]:
    if "messages" in case and "prompt" in case:
        raise ValueError(f"case {case_id!r} cannot contain both prompt and messages")
    if "messages" in case:
        value = case["messages"]
        if not isinstance(value, list) or not value:
            raise ValueError(f"case {case_id!r} messages must be a non-empty list")
        normalized: list[dict[str, str]] = []
        for index, message in enumerate(value):
            if not isinstance(message, dict):
                raise ValueError(f"case {case_id!r} message {index} must be an object")
            role = message.get("role")
            content = message.get("content")
            if role not in {"system", "user", "assistant"} or not isinstance(content, str):
                raise ValueError(
                    f"case {case_id!r} message {index} needs a valid role and string content"
                )
            normalized.append({"role": role, "content": content})
        return normalized
    prompt = case.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        raise ValueError(f"case {case_id!r} needs a non-empty prompt or messages")
    messages: list[dict[str, str]] = []
    system = case.get("system")
    if system is not None:
        if not isinstance(system, str):
            raise ValueError(f"case {case_id!r} system must be a string")
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt.strip()})
    return messages


def _case_from_dict(raw: dict[str, Any], defaults: dict[str, Any]) -> BenchmarkCase:
    if not isinstance(raw, dict):
        raise ValueError("each case must be an object")
    case_id = validate_id(raw.get("id"), "case id")
    context = raw.get("context", {})
    if isinstance(context, str):
        context = {"mode": context}
    if not isinstance(context, dict):
        raise ValueError(f"case {case_id!r} context must be a string or object")
    mode = context.get("mode", defaults.get("context_mode", "isolated"))
    if mode not in {"isolated", "preserve"}:
        raise ValueError(f"case {case_id!r} context mode must be isolated or preserve")
    group = context.get("group")
    if mode == "preserve":
        group = group or defaults.get("context_group")
        if not group:
            raise ValueError(f"case {case_id!r} preserve context requires a group")
        validate_id(group, f"case {case_id!r} context group")
    elif group is not None:
        raise ValueError(f"case {case_id!r} isolated context cannot specify a group")
    tags = raw.get("tags", [])
    if not isinstance(tags, list) or any(not isinstance(item, str) for item in tags):
        raise ValueError(f"case {case_id!r} tags must be a list of strings")
    options = dict(defaults.get("options", {}))
    raw_options = raw.get("options", {})
    if not isinstance(raw_options, dict):
        raise ValueError(f"case {case_id!r} options must be an object")
    options.update(raw_options)
    _validate_evaluation(raw.get("evaluation"), case_id)
    merged = dict(raw)
    if "system" not in merged and defaults.get("system") is not None:
        merged["system"] = defaults["system"]
    known = {"id", "prompt", "messages", "system", "context", "tags", "options"}
    metadata = {key: value for key, value in raw.items() if key not in known}
    return BenchmarkCase(
        id=case_id,
        messages=_messages(merged, case_id),
        context_mode=mode,
        context_group=group,
        tags=tags,
        options=options,
        metadata=metadata,
    )


def _suite_from_dict(raw: dict[str, Any], path: Path, digest: str) -> Suite:
    if not isinstance(raw, dict):
        raise ValueError(f"suite {path} must contain an object")
    if raw.get("schema_version", 1) != 1:
        raise ValueError("only suite schema_version 1 is supported")
    suite_id = validate_id(raw.get("suite_id"), "suite_id")
    defaults = raw.get("defaults", {})
    if not isinstance(defaults, dict):
        raise ValueError("suite defaults must be an object")
    cases_raw = raw.get("cases")
    if not isinstance(cases_raw, list) or not cases_raw:
        raise ValueError("suite cases must be a non-empty list")
    cases = [_case_from_dict(item, defaults) for item in cases_raw]
    duplicates = sorted({case.id for case in cases if sum(c.id == case.id for c in cases) > 1})
    if duplicates:
        raise ValueError(f"duplicate case ids in suite {suite_id}: {', '.join(duplicates)}")
    name = raw.get("name", suite_id)
    if not isinstance(name, str) or not name.strip():
        raise ValueError("suite name must be a non-empty string")
    return Suite(suite_id, name, cases, path, digest, defaults)


def _load_markdown(text: str, path: Path, digest: str) -> Suite:
    matches = list(CASE_HEADING.finditer(text))
    if not matches:
        raise ValueError(f"Markdown suite {path} has no '## Case: case-id' headings")
    preamble = text[: matches[0].start()]
    suite_meta: dict[str, Any] = {}
    preamble_match = META_COMMENT.search(preamble)
    if preamble_match:
        suite_meta = json.loads(preamble_match.group("json"))
    suite_id = suite_meta.get("suite_id", path.stem)
    defaults = suite_meta.get("defaults", {})
    cases: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[match.end() : end]
        case_meta: dict[str, Any] = {}
        comment = META_COMMENT.match(body)
        if comment:
            case_meta = json.loads(comment.group("json"))
            body = body[comment.end() :]
        case_meta = dict(case_meta)
        case_meta["id"] = match.group("id").strip()
        case_meta["prompt"] = body.strip()
        cases.append(case_meta)
    return _suite_from_dict(
        {
            "suite_id": suite_id,
            "name": suite_meta.get("name", suite_id),
            "defaults": defaults,
            "cases": cases,
        },
        path,
        digest,
    )


def load_suite(path: Path) -> Suite:
    path = path.resolve()
    data = path.read_bytes()
    digest = sha256_bytes(data)
    text = data.decode("utf-8-sig")
    if path.suffix.lower() == ".json":
        return _suite_from_dict(json.loads(text), path, digest)
    if path.suffix.lower() in {".md", ".markdown"}:
        return _load_markdown(text, path, digest)
    raise ValueError(f"unsupported suite format: {path.suffix}; use .json or .md")


def normalized_suite(suite: Suite) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "suite_id": suite.id,
        "name": suite.name,
        "source_path": str(suite.source_path),
        "source_sha256": suite.source_sha256,
        "defaults": suite.defaults,
        "cases": [
            {
                "id": case.id,
                "messages": case.messages,
                "context": {
                    "mode": case.context_mode,
                    **({"group": case.context_group} if case.context_group else {}),
                },
                "tags": case.tags,
                "options": case.options,
                "metadata": case.metadata,
            }
            for case in suite.cases
        ],
    }
