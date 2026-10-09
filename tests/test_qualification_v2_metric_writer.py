"""Writer parity and no-fabrication regression for the T13 metric projection."""
from __future__ import annotations
import csv
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from localbench.v2.flashnext_review import write_review_package


class MetricWriterTests(unittest.TestCase):
    def test_legacy_package_remains_usable_and_new_metrics_are_unscored(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            result = write_review_package(
                output_dir=out, phase="screen", shared_run=None,
                profile={"candidate_id": "C01", "candidate_name": "example"},
                summary={"results": [
                    {"role": "tester", "case_id": "tester-case-c", "status": "success",
                     "human_review_required": True, "deterministic_passed": True,
                     "evidence_directory": str(out / "evidence")},
                    {"role": "worker", "case_id": "task2", "status": "blocked",
                     "execution_status": "prerequisite_blocked"},
                ], "roles": ["tester", "worker"], "planned_cases": 2,
                    "completed_cases": 1, "stopped": None})
            self.assertTrue(Path(result["xlsx"]).exists())
            self.assertTrue(Path(result["metric_summary_csv"]).exists())
            package = json.loads(Path(result["json"]).read_text(encoding="utf-8"))
            self.assertEqual(package["schema_version"], "flashnext-role-review-package:v1")
            self.assertEqual(len(package["case_results"]), 2)
            metrics = package["qualification_v2_metrics"]
            self.assertIsNone(metrics["universal_intelligence_score"])
            self.assertFalse(metrics["automatic_role_assignment"])
            self.assertTrue(all(x["percentage"] is None for x in metrics["metrics"]))
            vision = next(x for x in metrics["metrics"] if x["metric_id"] == "vision")
            self.assertEqual(vision["status"], "not_tested")
            with Path(result["metric_summary_csv"]).open(newline="", encoding="utf-8") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), len(metrics["metrics"]))
            self.assertEqual(next(r for r in rows if r["metric_id"] == "vision")["percentage"], "")
            with zipfile.ZipFile(result["xlsx"]) as z:
                self.assertIn("xl/worksheets/sheet6.xml", z.namelist())
            self.assertEqual(package["case_results"][1]["execution_status"], "prerequisite_blocked")


class ExportParityTests(unittest.TestCase):
    def test_relative_evidence_remains_resolvable_after_reexport(self):
        import test_qualification_v2_metrics as fixtures
        from localbench.v2.report_adapter import write_normalized_review
        h=fixtures.MetricProjectionTests(); h.setUp(); self.addCleanup(h.doCleanups)
        row=h.case('code-diagnosis',suite_id='shared-l0-core',suite_version='1.0.0',
                   rubric_id='shared-l0-deterministic',rubric_version='1.0.0')
        row['evidence_refs'][0]['path']=Path(row['assessment_file']).name
        output=write_review_package(output_dir=h.root,summary={'results':[row]},profile={},shared_run=None,phase='fixture')
        exported=write_normalized_review(Path(output['json']),h.root/'reexport')
        data=json.loads(Path(exported['json']).read_text())['qualification_v2_metrics']
        measured=next(m for m in data['metrics'] if m['metric_id']=='coding' and m['suite_id']=='shared-l0-core')
        self.assertEqual(measured['percentage'],100)

    def test_large_evidence_cells_are_lossless_and_excel_sized(self):
        from localbench.v2.flashnext_review import _flat_rows, _sheet_xml
        from xml.etree import ElementTree as ET
        value=[{'evidence':'x'*2000} for _ in range(80)]
        flat=_flat_rows([{'refs':value}])[0]
        encoded=flat['refs']
        for i in range(2,len(flat)+1): encoded+=flat[f'refs__part{i}']
        self.assertEqual(json.loads(encoded),value)
        self.assertTrue(all(len(v.encode('utf-16-le'))//2<=32767 for v in flat.values()))
        ET.fromstring(_sheet_xml([flat]))

    def test_scored_and_excluded_rows_have_exact_json_csv_xlsx_linkage(self):
        import test_qualification_v2_metrics as fixtures
        from xml.etree import ElementTree as ET
        from localbench.v2.report_adapter import normalize_legacy_report
        h=fixtures.MetricProjectionTests(); h.setUp(); self.addCleanup(h.doCleanups)
        def shared(case, passed=True, **changes):
            return h.case(case,passed,suite_id='shared-l0-core',suite_version='1.0.0',
                rubric_id='shared-l0-deterministic',rubric_version='1.0.0',**changes)
        rows=[shared('contradiction-detection'),shared('dependency-plan',False),
              shared('code-diagnosis',human_review_required=True,human_review_status='pending')]
        other=shared('contradiction-detection',model_digest='f'*64)
        rows.append(other)
        out=write_review_package(output_dir=h.root,summary={'results':rows,'roles':[]},
                                 profile={},shared_run=None,phase='fixture')
        package=json.loads(Path(out['json']).read_text())
        metrics=package['qualification_v2_metrics']
        reasoning=[m for m in metrics['metrics'] if m['metric_id']=='reasoning']
        scored=next(m for m in reasoning if m['denominator']==2)
        self.assertEqual((scored['numerator'],scored['percentage']),(1,50))
        self.assertEqual(len(metrics['case_details']),4)
        with Path(out['metric_summary_csv']).open(newline='',encoding='utf-8') as f:
            csv_metrics=list(csv.DictReader(f))
        self.assertEqual(len(csv_metrics),len(metrics['metrics']))
        for source,flat in zip(metrics['metrics'],csv_metrics):
            self.assertEqual(json.loads(flat['case_refs_json']),source['case_refs'])
            self.assertEqual(json.loads(flat['excluded_json']),source['excluded'])
            self.assertEqual(json.loads(flat['membership']),source['membership'])
            self.assertEqual(flat['numerator'],'' if source['numerator'] is None else str(source['numerator']))
        ns={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        with zipfile.ZipFile(out['xlsx']) as z:
            for sheet,key in [(6,'metric_summary_csv'),(7,'normalized_cases_csv'),(8,'metric_cases_csv'),(9,'metric_comparisons_csv')]:
                with Path(out[key]).open(newline='',encoding='utf-8') as f:
                    expected=list(csv.reader(f))
                root=ET.fromstring(z.read(f'xl/worksheets/sheet{sheet}.xml'))
                actual=[]
                for row in root.findall('s:sheetData/s:row',ns):
                    cells=[]
                    for c in row.findall('s:c',ns):
                        text=''.join(c.itertext())
                        if c.get('t')=='b': text='True' if text=='1' else 'False'
                        cells.append(text)
                    actual.append(cells)
                self.assertEqual(actual,expected)
        before=Path(out['json']).read_bytes()
        loaded=normalize_legacy_report(Path(out['json']))
        self.assertEqual(len(loaded['cases']),4)
        self.assertEqual(Path(out['json']).read_bytes(),before)
        self.assertEqual(loaded['cases'][0]['evidence_refs'],rows[0]['evidence_refs'])


if __name__ == "__main__":
    unittest.main()
