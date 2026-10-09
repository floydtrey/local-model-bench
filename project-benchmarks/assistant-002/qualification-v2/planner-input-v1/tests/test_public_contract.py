"""Visible validation examples. Additional scenario files disclose everyday cases."""
import json
from pathlib import Path
import unittest
from assistant_simulator import normalize_scenario, scenario_digest

class PublicContractTests(unittest.TestCase):
    def raw(self):
        return json.loads((Path(__file__).resolve().parents[1] / 'scenarios/door-reconnect.json').read_text(encoding='utf-8'))

    def test_explicit_defaults(self):
        normalized = normalize_scenario(self.raw())
        self.assertEqual(normalized['events'][0]['delay_ms'], 0)
        self.assertIs(normalized['events'][0]['drop'], False)

    def test_identity_does_not_depend_on_object_key_order(self):
        raw = self.raw()
        self.assertEqual(scenario_digest(raw), scenario_digest(dict(reversed(list(raw.items())))))

    def test_boolean_duration_is_invalid(self):
        raw = self.raw(); raw['duration_ms'] = True
        with self.assertRaises(ValueError): normalize_scenario(raw)
