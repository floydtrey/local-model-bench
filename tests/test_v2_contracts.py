from __future__ import annotations

import copy
import unittest

from localbench.v2.contracts import (
    EVIDENCE_SCHEMA_VERSION,
    EvidenceRef,
    SealedEvidence,
    canonical_json_bytes,
    seal_evidence,
    sha256_json,
)


class CanonicalJsonTests(unittest.TestCase):
    def test_object_key_order_does_not_change_digest(self):
        left = {"b": 2, "a": {"z": None, "x": 1}}
        right = {"a": {"x": 1, "z": None}, "b": 2}

        self.assertEqual(canonical_json_bytes(left), canonical_json_bytes(right))
        self.assertEqual(sha256_json(left), sha256_json(right))

    def test_null_is_preserved_as_explicit_unknown(self):
        encoded = canonical_json_bytes({"vram_bytes": None}).decode("utf-8")
        self.assertEqual(encoded, '{"vram_bytes":null}')

    def test_non_json_numeric_values_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "canonical JSON"):
            canonical_json_bytes({"bad": float("nan")})


class EvidenceContractTests(unittest.TestCase):
    def test_sealed_record_round_trips_and_reference_is_stable(self):
        sealed = seal_evidence(
            "host_profile",
            "new-tower",
            {
                "os": {"name": "Windows", "build": None},
                "memory": {"installed_bytes": 64 * 1024**3},
            },
        )

        restored = SealedEvidence.from_dict(sealed.to_dict())

        self.assertEqual(restored, sealed)
        self.assertEqual(restored.schema_version, EVIDENCE_SCHEMA_VERSION)
        self.assertEqual(restored.reference, sealed.reference)
        self.assertEqual(EvidenceRef.from_dict(sealed.reference.to_dict()), sealed.reference)

    def test_logical_id_is_not_the_cryptographic_identity(self):
        first = seal_evidence("runtime_profile", "ollama-local", {"version": "1"})
        second = seal_evidence("runtime_profile", "ollama-local", {"version": "2"})

        self.assertEqual(first.logical_id, second.logical_id)
        self.assertNotEqual(first.sha256, second.sha256)

    def test_record_type_is_bound_into_digest(self):
        payload = {"name": "candidate"}
        model = seal_evidence("model_identity", "candidate", payload)
        runtime = seal_evidence("runtime_profile", "candidate", payload)

        self.assertNotEqual(model.sha256, runtime.sha256)

    def test_tampering_is_rejected(self):
        sealed = seal_evidence("model_identity", "model-a", {"digest": "abc"})
        serialized = sealed.to_dict()
        serialized["payload"]["digest"] = "changed"

        with self.assertRaisesRegex(ValueError, "digest mismatch"):
            SealedEvidence.from_dict(serialized)

    def test_caller_mutation_does_not_change_sealed_payload(self):
        source = {"nested": {"values": [1, 2]}}
        original = copy.deepcopy(source)
        sealed = seal_evidence("benchmark_input", "suite-a", source)

        source["nested"]["values"].append(3)

        self.assertEqual(sealed.payload, original)
        self.assertEqual(SealedEvidence.from_dict(sealed.to_dict()), sealed)

    def test_invalid_record_type_and_id_fail_closed(self):
        with self.assertRaisesRegex(ValueError, "record type"):
            seal_evidence("unknown", "x", {})
        with self.assertRaisesRegex(ValueError, "logical_id"):
            seal_evidence("host_profile", "../escape", {})

    def test_reference_requires_lowercase_sha256(self):
        with self.assertRaisesRegex(ValueError, "lowercase"):
            EvidenceRef("host_profile", "host-a", "A" * 64)


if __name__ == "__main__":
    unittest.main()
