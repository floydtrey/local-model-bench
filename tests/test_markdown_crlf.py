from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from localbench.suites import load_suite


class MarkdownLineEndingTests(unittest.TestCase):
    def test_crlf_markdown_case_headings_load_on_windows(self):
        content = (
            '<!-- localbench\r\n'
            '{"suite_id":"crlf-suite","name":"CRLF suite"}\r\n'
            '-->\r\n\r\n'
            '## Case: first-case\r\n'
            'First prompt.\r\n\r\n'
            '## Case: second-case\r\n'
            'Second prompt.\r\n'
        ).encode('utf-8')

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'crlf-suite.md'
            path.write_bytes(content)
            suite = load_suite(path)

        self.assertEqual(suite.id, 'crlf-suite')
        self.assertEqual([case.id for case in suite.cases], ['first-case', 'second-case'])
        self.assertEqual(suite.cases[0].messages[-1]['content'], 'First prompt.')
        self.assertEqual(suite.cases[1].messages[-1]['content'], 'Second prompt.')


if __name__ == '__main__':
    unittest.main()
