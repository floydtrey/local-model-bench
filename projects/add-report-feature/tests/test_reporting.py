import unittest

from reporting.cli import produce
from reporting.domain import summarize


class ReportingTests(unittest.TestCase):
    def test_summary(self):
        self.assertEqual(
            summarize([2, 4]),
            {"count": 2, "total": 6, "average": 3.0},
        )

    def test_default_text_output_is_stable(self):
        self.assertEqual(produce(["2", "4"]), "count=2 total=6.0 average=3.0")


if __name__ == "__main__":
    unittest.main()
