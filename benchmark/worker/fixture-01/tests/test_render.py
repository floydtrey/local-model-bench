import unittest

from reporting.config import ReportConfig
from reporting.render import render_report


class RenderReportTests(unittest.TestCase):
    def test_existing_default_output(self):
        self.assertEqual(
            render_report(["alpha", "beta"], ReportConfig()),
            "Report\n- alpha\n- beta\nTotal: 2",
        )

    def test_totals_can_be_disabled(self):
        self.assertEqual(
            render_report(["alpha"], ReportConfig(include_totals=False)),
            "Report\n- alpha",
        )


if __name__ == "__main__":
    unittest.main()
