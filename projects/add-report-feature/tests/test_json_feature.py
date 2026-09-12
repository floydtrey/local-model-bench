import json
import unittest

from reporting.cli import produce


class JsonFeatureTests(unittest.TestCase):
    def test_json_output(self):
        payload = json.loads(produce(["2", "3", "--json"]))
        self.assertEqual(
            payload,
            {"count": 2, "total": 5.0, "average": 2.5},
        )


if __name__ == "__main__":
    unittest.main()
