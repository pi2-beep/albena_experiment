from __future__ import annotations

import unittest
from pathlib import Path


class SchemaTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.schema = (Path(__file__).parents[1] / "wave2" / "schema.sql").read_text(encoding="utf-8")

    def test_wave2_has_separate_invitation_and_session_records(self):
        self.assertIn("CREATE TABLE study_sessions", self.schema)
        self.assertIn("CREATE TABLE invitation_tokens", self.schema)

    def test_randomisation_uses_pre_generated_consumable_slots(self):
        self.assertIn("CREATE TABLE randomisation_slots", self.schema)
        self.assertIn("WHERE participant_id IS NULL", self.schema)
        self.assertIn("CREATE TABLE randomisation_assignments", self.schema)

    def test_raw_ai_messages_are_separate_from_participant_outcomes(self):
        self.assertIn("CREATE TABLE ai_messages", self.schema)
        self.assertIn("tool_name TEXT NOT NULL", self.schema)
        self.assertIn("response_pasted_at TIMESTAMPTZ", self.schema)
        self.assertNotIn("provider_request_id", self.schema)
        self.assertIn("CREATE TABLE immediate_post_judgements", self.schema)
        self.assertIn("CREATE TABLE final_judgements", self.schema)

    def test_all_allocations_have_database_total_constraints(self):
        self.assertIn("baseline_total_100", self.schema)
        self.assertIn("immediate_post_total_100", self.schema)
        self.assertIn("final_total_100", self.schema)


if __name__ == "__main__":
    unittest.main()
