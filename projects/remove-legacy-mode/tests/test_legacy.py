import unittest

from legacyapp.legacy import legacy_format


class LegacyTests(unittest.TestCase):
    def test_legacy_format(self):
        self.assertEqual(legacy_format("Ada"), "HELLO::ADA")


if __name__ == "__main__":
    unittest.main()
