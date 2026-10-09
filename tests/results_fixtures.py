"""Synthetic outputs written by the accepted T13 writer, never model execution."""
import json
from pathlib import Path

from localbench.v2.flashnext_review import write_review_package
from localbench.v2.report_adapter import file_reference

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "docs/qualification-v2/METRIC_CATALOG_V1.json").read_text())


class ReportFixture:
    def __init__(self, root, model="fixture-model"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.model = model
        self.rows = []

    def case(self, case_id="code-diagnosis", *, metric="coding", source_index=0, **changes):
        definition = next(m for m in CATALOG["metrics"] if m["id"] == metric)
        source = definition["sources"][source_index]
        index = len(self.rows) + 1
        row = {k: source[k] for k in ("suite_id", "suite_version", "rubric_id", "rubric_version")}
        row.update(case_id=case_id, model_identity={"name": self.model, "digest": self.model + "-digest", "quantization": "synthetic"},
            runtime_identity={"name": "fixture", "version": "1", "transport": "injected"},
            context_tokens=4096, effective_settings={"temperature": 0, "seed": 1},
            runtime_compatibility="supported", track="controlled_role_qualification",
            comparison_protocol="fixture:v1", authority_assumptions="no-execution-authority",
            assessor_version="fixture:1", evidence_version="fixture:1",
            run_id=self.root.name, trial_id=f"trial-{case_id}", attempt_id=f"attempt-{index}", attempt_index=1,
            execution_status="completed", assessed_outcome="PASS", human_review_required=False,
            human_review_status="not_required", input_sha256="b" * 64, reference_sha256="c" * 64,
            rubric_sha256="d" * 64, candidate_sha256="e" * 64)
        row.update(changes)
        if row.get("human_review_status") == "recorded":
            row["human_adjudication"] = {**{k: row[k] for k in ("input_sha256", "candidate_sha256", "rubric_sha256")},
                "review_origin": "human_declared", "reviewer": "synthetic-reviewer", "reviewed_at": "2026-10-09T00:00:00Z"}
        path = self.root / f"assessment-{index}.json"
        path.write_text(json.dumps({k: row.get(k) for k in ("case_id", "assessed_outcome", "input_sha256",
            "candidate_sha256", "rubric_sha256", "human_adjudication")}), encoding="utf-8")
        row.setdefault("evidence_refs", [file_reference(path, "assessment")])
        row["assessment_file"] = str(path)
        self.rows.append(row)
        return row

    def write(self):
        result = write_review_package(output_dir=self.root, summary={"results": self.rows}, profile={}, shared_run=None, phase="synthetic")
        return Path(result["json"])
