from __future__ import annotations

import unittest

from wave2.domain import (
    DomainValidationError,
    StudyState,
    lock_judgement,
    require_transition,
    revision_score,
    validate_judgement,
)


def judgement(preferred="B", a=20, b=60, c=20, confidence=70):
    return {
        "preferred": preferred,
        "points_a": a,
        "points_b": b,
        "points_c": c,
        "confidence": confidence,
        "rationale": "Кратка професионална обосновка.",
    }


class DomainTestCase(unittest.TestCase):
    def test_valid_study_transition(self):
        require_transition(StudyState.BASELINE_LOCKED, StudyState.RANDOMISED)

    def test_skipping_randomisation_is_rejected(self):
        with self.assertRaises(DomainValidationError):
            require_transition(StudyState.BASELINE_LOCKED, StudyState.INTERVENTION_ACTIVE)

    def test_allocations_must_total_exactly_one_hundred(self):
        with self.assertRaises(DomainValidationError):
            validate_judgement(judgement(c=19))

    def test_no_default_or_missing_preferred_option_is_accepted(self):
        with self.assertRaises(DomainValidationError):
            validate_judgement(judgement(preferred=""))

    def test_preferred_allocation_mismatch_requires_confirmation(self):
        mismatched = judgement(preferred="A", a=20, b=60, c=20)
        with self.assertRaises(DomainValidationError):
            lock_judgement(mismatched, mismatch_confirmed=False)
        locked = lock_judgement(
            mismatched,
            mismatch_confirmed=True,
            locked_at="2026-09-21T10:00:00.000Z",
        )
        self.assertTrue(locked.mismatch_confirmed)
        self.assertRegex(locked.snapshot_sha256, r"^[a-f0-9]{64}$")

    def test_tied_highest_allocation_is_not_a_mismatch(self):
        result = validate_judgement(judgement(preferred="A", a=40, b=40, c=20))
        self.assertFalse(result["preferred_allocation_mismatch"])

    def test_primary_revision_score(self):
        baseline = judgement(preferred="B", a=20, b=60, c=20)
        post = judgement(preferred="C", a=10, b=30, c=60)
        self.assertEqual(revision_score(baseline, post), 40.0)


if __name__ == "__main__":
    unittest.main()
