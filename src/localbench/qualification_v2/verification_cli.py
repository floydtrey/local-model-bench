"""Offline T11/T12 preparation and human adjudication; no execution command."""
import argparse
import json
from pathlib import Path

from .verification_packet import load_cases, prepare
from .verification import assess_run


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("validate", "prepare", "assess", "calibrate"))
    parser.add_argument("--case")
    parser.add_argument("--output-root", type=Path)
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--review-file", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.action == "validate":
            from .verification_packet import build_packet
            cases = load_cases()
            for case in cases:
                build_packet(case["case_id"])
            print(json.dumps({"cases": len(cases), "human_review": "pending", "model_runs": 0}))
        elif args.action == "calibrate":
            from .verification_calibration import calibrate
            result = calibrate()
            print(json.dumps(result, indent=2))
            return 0 if result["passed"] else 1
        elif args.action == "prepare":
            if not args.case or not args.output_root:
                raise ValueError("prepare requires --case and --output-root")
            print("RUN_DIR=" + str(prepare(args.case, args.output_root)))
        else:
            if not args.run_dir:
                raise ValueError("assess requires --run-dir")
            target, result = assess_run(args.run_dir, review_file=args.review_file)
            print(f"ASSESSMENT_DIR={target}\nROLE_OUTCOME={result['assessed_outcome']}")
        return 0
    except (ValueError, OSError, KeyError, TypeError, StopIteration) as exc:
        print(f"BLOCKED: {type(exc).__name__}: {exc}")
        return 2
