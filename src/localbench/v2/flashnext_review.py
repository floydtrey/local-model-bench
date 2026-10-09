"""Standardized all-role candidate review package.

Raw V2 evidence remains authoritative. The XLSX is a dependency-free reporting
projection so benchmark machines do not need a spreadsheet package installed.
"""
from __future__ import annotations

import csv
import io
import json
import math
import zipfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable, Mapping
from xml.sax.saxutils import escape

from .contracts import canonical_json_bytes


def _number(value: Any) -> float | int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return value
    return None


def _mean(values: Iterable[Any]) -> float | None:
    numbers = [float(v) for v in values if _number(v) is not None]
    return sum(numbers) / len(numbers) if numbers else None


def _case_row(result: Mapping[str, Any], profile: Mapping[str, Any]) -> dict[str, Any]:
    metrics = result.get("metrics") or {}
    return {
        "candidate_id": profile.get("candidate_id"),
        "candidate_name": profile.get("candidate_name"),
        "role": result.get("role"),
        "case_id": result.get("case_id"),
        "ordinal": result.get("ordinal"),
        "status": result.get("status"),
        "stop_reason": result.get("stop_reason"),
        "runtime_compatibility": result.get("runtime_compatibility"),
        "correctness": result.get("correctness"),
        "deterministic_passed": result.get("deterministic_passed"),
        "first_pass_passed": result.get("first_pass_passed"),
        "repair_attempted": result.get("repair_attempted"),
        "repair_passed": result.get("repair_passed"),
        "human_review_required": result.get("human_review_required"),
        "qualification_status": result.get("qualification_status"),
        "wall_seconds": metrics.get("wall_seconds"),
        "prompt_tokens": metrics.get("prompt_tokens"),
        "output_tokens": metrics.get("output_tokens"),
        "generation_seconds": metrics.get("generation_seconds"),
        "generation_tokens_per_second": metrics.get("generation_tokens_per_second"),
        "overall_output_tokens_per_second": metrics.get("overall_output_tokens_per_second"),
        "model_turns": metrics.get("model_turns"),
        "tool_calls": metrics.get("tool_calls"),
        "denied_tool_calls": metrics.get("denied_tool_calls"),
        "schema_normalizations": metrics.get("schema_normalizations"),
        "validation_failures": metrics.get("validation_failures"),
        "validation_retry_turns": metrics.get("validation_retry_turns"),
        "repetition_detections": metrics.get("repetition_detections"),
        "test_tool_calls": metrics.get("test_tool_calls"),
        "final_output_words": metrics.get("final_output_words"),
        "evidence_directory": result.get("evidence_directory"),
        # Additive qualification-v2 projections; missing historical values stay unknown.
        "track": result.get("track"),
        "planner_mode": result.get("planner_mode"),
        "governor_mode": result.get("governor_mode"),
        "governance_sha256": result.get("governance_sha256"),
        "candidate_decision": result.get("candidate_decision"),
        "reference_review_status": result.get("reference_review_status"),
        "critical_unsafe_approval": result.get("critical_unsafe_approval"),
        "failure_classifications": json.dumps(result["failure_classifications"]) if result.get("failure_classifications") is not None else None,
        "model_identity": json.dumps(result["model_identity"], sort_keys=True) if result.get("model_identity") else None,
        "comparison_protocol": json.dumps(result["comparison_protocol"], sort_keys=True) if result.get("comparison_protocol") else None,
        "execution_status": result.get("execution_status"),
        "assessed_outcome": result.get("assessed_outcome"),
        "human_review_status": result.get("human_review_status"),
        "input_sha256": result.get("input_sha256"),
        "candidate_sha256": result.get("candidate_sha256"),
        "rubric_version": result.get("rubric_version"),
        "rubric_sha256": result.get("rubric_sha256"),
        "assessment_file": result.get("assessment_file"),
        "session_evidence_directory": result.get("session_evidence_directory"),
        "configuration_evidence_directory": result.get("configuration_evidence_directory"),
        "runtime_identity": json.dumps(result["runtime_identity"], sort_keys=True) if result.get("runtime_identity") else None,
        "comparison_eligible": result.get("comparison_eligible"),
        "comparison_note": result.get("comparison_note"),
        "output_origin": result.get("output_origin"),
    }


def _role_rows(case_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in case_rows:
        groups[str(row["role"])].append(row)
    rows = []
    for role in ("planner", "governor", "worker", "tester", "reviewer"):
        cases = groups.get(role, [])
        if not cases:
            continue
        evaluated = [r.get("deterministic_passed") for r in cases if r.get("deterministic_passed") is not None]
        rows.append({
            "role": role,
            "cases": len(cases),
            "success_status": sum(r.get("status") == "success" for r in cases),
            "deterministic_passes": sum(v is True for v in evaluated),
            "deterministic_evaluated": len(evaluated),
            "human_review_pending": sum(bool(r.get("human_review_required")) for r in cases),
            "schema_normalizations": sum(int(r.get("schema_normalizations") or 0) for r in cases),
            "validation_retry_turns": sum(int(r.get("validation_retry_turns") or 0) for r in cases),
            "repetition_detections": sum(int(r.get("repetition_detections") or 0) for r in cases),
            "mean_generation_tokens_per_second": _mean(r.get("generation_tokens_per_second") for r in cases),
            "mean_wall_seconds": _mean(r.get("wall_seconds") for r in cases),
            "total_output_tokens": sum(int(r.get("output_tokens") or 0) for r in cases),
            "recommendation": "HUMAN_REVIEW_PENDING",
        })
    return rows


def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    if not rows:
        return b""
    out = io.StringIO(newline="")
    writer = csv.DictWriter(out, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().encode("utf-8")


def _col_name(index: int) -> str:
    result = ""
    while index:
        index, rem = divmod(index - 1, 26)
        result = chr(65 + rem) + result
    return result


def _cell(ref: str, value: Any, style: int = 0) -> str:
    style_attr = f' s="{style}"' if style else ""
    if value is None:
        return f'<c r="{ref}"{style_attr}/>'
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"{style_attr}><v>{1 if value else 0}</v></c>'
    if _number(value) is not None:
        return f'<c r="{ref}"{style_attr}><v>{value}</v></c>'
    text = escape(str(value))
    return f'<c r="{ref}" t="inlineStr"{style_attr}><is><t>{text}</t></is></c>'


def _sheet_xml(rows: list[dict[str, Any]]) -> str:
    headers = list(rows[0]) if rows else ["empty"]
    values = [headers] + [[row.get(header) for header in headers] for row in rows]
    xml_rows = []
    for ridx, row in enumerate(values, 1):
        cells = [_cell(f"{_col_name(cidx)}{ridx}", value, 1 if ridx == 1 else 0)
                 for cidx, value in enumerate(row, 1)]
        xml_rows.append(f'<row r="{ridx}">{"".join(cells)}</row>')
    last = f"{_col_name(len(headers))}{max(1, len(values))}"
    widths = "".join(
        f'<col min="{i}" max="{i}" width="{40 if i <= 8 else 18}" customWidth="1"/>'
        for i in range(1, len(headers) + 1)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f'<dimension ref="A1:{last}"/>'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        f'<cols>{widths}</cols><sheetData>{"".join(xml_rows)}</sheetData>'
        f'<autoFilter ref="A1:{_col_name(len(headers))}1"/></worksheet>'
    )


def _write_xlsx(path: Path, sheets: list[tuple[str, list[dict[str, Any]]]]) -> None:
    content_types = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
    ]
    for i in range(1, len(sheets) + 1):
        content_types.append(
            f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        )
    content_types.append('</Types>')
    workbook_sheets = "".join(
        f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>'
        for i, (name, _) in enumerate(sheets, 1)
    )
    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets>{workbook_sheets}</sheets></workbook>'
    )
    rels = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
    ]
    for i in range(1, len(sheets) + 1):
        rels.append(
            f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>'
        )
    rels.append(
        f'<Relationship Id="rId{len(sheets)+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    )
    rels.append('</Relationships>')
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    styles = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
        '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>'
        '<fill><patternFill patternType="solid"><fgColor rgb="FFD9EAF7"/><bgColor indexed="64"/></patternFill></fill></fills>'
        '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
        '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
        '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
        '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/></cellXfs>'
        '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "".join(content_types))
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", "".join(rels))
        archive.writestr("xl/styles.xml", styles)
        for i, (_, rows) in enumerate(sheets, 1):
            archive.writestr(f"xl/worksheets/sheet{i}.xml", _sheet_xml(rows))


def write_review_package(*, output_dir: Path, summary: Mapping[str, Any], profile: Mapping[str, Any],
                         shared_run: Path | None, phase: str) -> dict[str, Any]:
    output = Path(output_dir) / "review"
    output.mkdir(parents=True, exist_ok=False)
    case_rows = [_case_row(result, profile) for result in summary.get("results", [])]
    role_rows = _role_rows(case_rows)
    recovery_rows = [{
        "role": row["role"], "case_id": row["case_id"],
        "schema_normalizations": row["schema_normalizations"],
        "validation_failures": row["validation_failures"],
        "validation_retry_turns": row["validation_retry_turns"],
        "repetition_detections": row["repetition_detections"],
        "denied_tool_calls": row["denied_tool_calls"],
        "repair_attempted": row["repair_attempted"],
        "repair_passed": row["repair_passed"],
    } for row in case_rows]
    performance_rows = [{
        "role": row["role"], "case_id": row["case_id"], "wall_seconds": row["wall_seconds"],
        "prompt_tokens": row["prompt_tokens"], "output_tokens": row["output_tokens"],
        "generation_seconds": row["generation_seconds"],
        "generation_tokens_per_second": row["generation_tokens_per_second"],
        "overall_output_tokens_per_second": row["overall_output_tokens_per_second"],
        "model_turns": row["model_turns"], "tool_calls": row["tool_calls"],
        "final_output_words": row["final_output_words"],
    } for row in case_rows]
    metadata = [{
        "candidate_id": profile.get("candidate_id"),
        "candidate_name": profile.get("candidate_name"),
        "model_entry": profile.get("model_entry"),
        "runtime": profile.get("server_executable"),
        "fork_revision": profile.get("fork_revision"),
        "context_tokens": profile.get("context_tokens"),
        "phase": phase,
        "shared_run": str(shared_run) if shared_run else None,
        "roles": ",".join(summary.get("roles", [])),
        "planned_cases": summary.get("planned_cases"),
        "completed_cases": summary.get("completed_cases"),
        "stopped": json.dumps(summary.get("stopped"), sort_keys=True),
        "qualification_status": summary.get("qualification_status"),
        "reviewer_status": summary.get("reviewer_status"),
        "raw_evidence_authoritative": True,
    }]
    package = {
        "schema_version": "flashnext-role-review-package:v1",
        "metadata": metadata[0],
        "role_summary": role_rows,
        "case_results": case_rows,
        "recovery": recovery_rows,
        "performance": performance_rows,
    }
    (output / "review-package.json").write_bytes(canonical_json_bytes(package) + b"\n")
    (output / "case-results.csv").write_bytes(_csv_bytes(case_rows))
    (output / "role-summary.csv").write_bytes(_csv_bytes(role_rows))
    workbook = output / "review-package.xlsx"
    _write_xlsx(workbook, [
        ("Model Summary", metadata),
        ("Role Scorecard", role_rows),
        ("Case Results", case_rows),
        ("Controller Recovery", recovery_rows),
        ("Performance", performance_rows),
    ])
    return {
        "directory": str(output),
        "json": str(output / "review-package.json"),
        "case_results_csv": str(output / "case-results.csv"),
        "role_summary_csv": str(output / "role-summary.csv"),
        "xlsx": str(workbook),
        "raw_evidence_authoritative": True,
    }
