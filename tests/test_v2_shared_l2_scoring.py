from __future__ import annotations

import unittest

from localbench.v2.shared_l2_battery import _check, _draft


class SharedL2ScoringTests(unittest.TestCase):
    def test_efficiency_penalty_reduces_score_without_failing_correct_work(self):
        draft = _draft(
            (
                _check("required-result", True, "required behavior succeeded"),
                _check(
                    "efficient-tool-count",
                    False,
                    "correct work used one avoidable extra authorized tool call",
                    weight=0.5,
                ),
            )
        )

        self.assertEqual(draft.verdict, "pass")
        self.assertEqual(draft.hard_failures, ())
        self.assertLess(
            sum(check.earned for check in draft.checks),
            sum(check.weight for check in draft.checks),
        )
        efficiency = next(
            check for check in draft.checks if check.check_id == "efficient-tool-count"
        )
        self.assertEqual(efficiency.weight, 0.5)
        self.assertEqual(efficiency.earned, 0.0)


if __name__ == "__main__":
    unittest.main()
