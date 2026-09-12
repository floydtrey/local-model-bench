from __future__ import annotations

import unittest

from localbench.v2.compatibility import (
    COMPATIBILITY_DIMENSIONS,
    COMPATIBILITY_OBSERVATION_VERSION,
    COMPATIBILITY_STATUSES,
    CompatibilityDimension,
    ToolCompatibilityObservation,
    compatibility_observation,
    seal_compatibility_observation,
    validate_compatibility_observation_evidence,
)
from localbench.v2.contracts import EvidenceRef, SealedEvidence


INTERFACE_REF = EvidenceRef(
    "execution_interface_identity",
    "interface-test",
    "a" * 64,
)
TRACE_REF = EvidenceRef(
    "tool_execution_trace",
    "trace-test",
    "b" * 64,
)


def sample_observation() -> ToolCompatibilityObservation:
    return compatibility_observation(
        case_id="read-only-evidence-answer",
        turn=1,
        execution_interface=INTERFACE_REF,
        semantic_tool_selection=CompatibilityDimension(
            "pass",
            "read_file was selected",
            (TRACE_REF,),
        ),
        argument_correctness=CompatibilityDimension(
            "pass",
            "facts.txt was selected",
            (TRACE_REF,),
        ),
        protocol_parser_compatibility=CompatibilityDimension(
            "fail",
            "tool-shaped content was not promoted to a structured tool call",
            (TRACE_REF,),
        ),
        end_to_end_success=CompatibilityDimension(
            "fail",
            "no executable normalized ToolCall reached BL-6",
            (TRACE_REF,),
        ),
        diagnostic_metadata={"provider_finish_reason": "stop"},
    )


class CompatibilityObservationTests(unittest.TestCase):
    def test_observation_keeps_four_dimensions_independent(self):
        payload = sample_observation().to_dict()
        self.assertEqual(
            payload["observation_version"],
            COMPATIBILITY_OBSERVATION_VERSION,
        )
        self.assertEqual(set(payload["dimensions"]), set(COMPATIBILITY_DIMENSIONS))
        self.assertEqual(
            payload["dimensions"]["semantic_tool_selection"]["status"], "pass"
        )
        self.assertEqual(
            payload["dimensions"]["argument_correctness"]["status"], "pass"
        )
        self.assertEqual(
            payload["dimensions"]["protocol_parser_compatibility"]["status"],
            "fail",
        )
        self.assertEqual(
            payload["dimensions"]["end_to_end_success"]["status"], "fail"
        )
        self.assertTrue(payload["diagnostic_only"])
        self.assertEqual(payload["execution_authority"], "none")

    def test_observation_has_no_tool_call_conversion_or_execution_hook(self):
        observation = ToolCompatibilityObservation(
            case_id="case-a",
            turn=1,
            execution_interface=INTERFACE_REF,
            semantic_tool_selection=CompatibilityDimension("unknown"),
            argument_correctness=CompatibilityDimension("unknown"),
            protocol_parser_compatibility=CompatibilityDimension("unknown"),
            end_to_end_success=CompatibilityDimension("unknown"),
        )
        self.assertFalse(hasattr(observation, "to_tool_call"))
        self.assertFalse(hasattr(observation, "execute"))
        self.assertFalse(hasattr(observation, "authorize"))

    def test_observation_can_be_sealed_as_content_addressed_evidence(self):
        sealed = seal_compatibility_observation(
            "read-only-evidence-answer-turn-1-compatibility",
            sample_observation(),
        )
        self.assertIsInstance(sealed, SealedEvidence)
        self.assertEqual(sealed.record_type, "tool_compatibility_observation")
        self.assertTrue(sealed.payload["diagnostic_only"])
        self.assertEqual(sealed.payload["execution_authority"], "none")
        validate_compatibility_observation_evidence(sealed)

    def test_sealing_is_deterministic(self):
        first = seal_compatibility_observation("compatibility-a", sample_observation())
        second = seal_compatibility_observation("compatibility-a", sample_observation())
        self.assertEqual(first.sha256, second.sha256)
        self.assertEqual(first.to_dict(), second.to_dict())

    def test_sealed_evidence_cannot_claim_execution_authority(self):
        sealed = seal_compatibility_observation("compatibility-a", sample_observation())
        tampered = dict(sealed.payload)
        tampered["execution_authority"] = "bl6"
        from localbench.v2.contracts import seal_evidence

        invalid = seal_evidence("tool_compatibility_observation", "compatibility-b", tampered)
        with self.assertRaises(ValueError):
            validate_compatibility_observation_evidence(invalid)

    def test_invalid_status_is_rejected(self):
        with self.assertRaises(ValueError):
            CompatibilityDimension("maybe")

    def test_execution_interface_ref_type_is_enforced(self):
        wrong = EvidenceRef("runtime_profile", "runtime-test", "c" * 64)
        with self.assertRaises(ValueError):
            ToolCompatibilityObservation(
                case_id="case-a",
                turn=1,
                execution_interface=wrong,
                semantic_tool_selection=CompatibilityDimension("unknown"),
                argument_correctness=CompatibilityDimension("unknown"),
                protocol_parser_compatibility=CompatibilityDimension("unknown"),
                end_to_end_success=CompatibilityDimension("unknown"),
            )

    def test_duplicate_evidence_references_are_rejected(self):
        with self.assertRaises(ValueError):
            CompatibilityDimension("pass", evidence=(TRACE_REF, TRACE_REF))

    def test_public_status_set_is_narrow(self):
        self.assertEqual(
            COMPATIBILITY_STATUSES,
            frozenset({"pass", "fail", "unknown", "not_applicable"}),
        )


if __name__ == "__main__":
    unittest.main()
