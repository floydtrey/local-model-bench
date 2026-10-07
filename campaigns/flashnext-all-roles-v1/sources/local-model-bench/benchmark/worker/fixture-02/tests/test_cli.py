import contextlib
import io
import unittest

from inventory.cli import main


class InventoryCliTests(unittest.TestCase):
    def test_list_command_preserves_existing_output(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = main(["list"])

        self.assertEqual(code, 0)
        self.assertEqual(stderr.getvalue(), "")
        self.assertEqual(
            stdout.getvalue(),
            "A-100\tWidget\t4\ttrue\nC-300\tCable\t7\ttrue\n",
        )

    def test_unknown_command_is_rejected(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                main(["unknown"])

        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("invalid choice", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
