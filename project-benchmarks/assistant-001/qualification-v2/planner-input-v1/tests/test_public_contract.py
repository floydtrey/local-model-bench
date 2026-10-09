"""Candidate-visible examples; independent acceptance covers the full contract."""
import copy
import unittest
from assistant_journal import normalize_event

class PublicContractTests(unittest.TestCase):
    def event(self):
        return dict(event_id="evt-0001", source="observer", type="presence",
                    entity="dog_door", timestamp="2026-10-07T18:30:00Z",
                    confidence=0.94, data={"region": "left", "count": 1})

    def test_normalizes_without_changing_input(self):
        event = self.event(); before = copy.deepcopy(event)
        result = normalize_event(event)
        self.assertEqual(event, before)
        self.assertEqual(result["timestamp"], "2026-10-07T18:30:00.000000Z")
        self.assertEqual(result["ttl_seconds"], 300)

    def test_boolean_confidence_is_not_a_probability(self):
        event = self.event(); event["confidence"] = True
        with self.assertRaises(ValueError):
            normalize_event(event)

if __name__ == "__main__":
    unittest.main()
