import contextlib
import io
import unittest

from legacyapp.main import build_parser, produce


class MainTests(unittest.TestCase):
    def test_default_behavior(self):
        self.assertEqual(produce(["Ada"]), "Hello, Ada!")

    def test_legacy_option_is_not_supported(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                build_parser().parse_args(["Ada", "--legacy"])


if __name__ == "__main__":
    unittest.main()
