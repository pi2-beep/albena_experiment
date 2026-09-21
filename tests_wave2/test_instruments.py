from __future__ import annotations

import unittest

from wave2.instruments import load_json_instrument, load_manifest, load_text_instrument


class InstrumentTestCase(unittest.TestCase):
    def test_frozen_instrument_hashes_are_valid(self):
        manifest = load_manifest()
        self.assertEqual(manifest["manifest_version"], "wave2-instruments-v1")
        self.assertEqual(len(manifest["files"]), 4)

    def test_study_configuration_matches_the_protocol_draft(self):
        study = load_json_instrument("study_v1.json")
        self.assertEqual(study["planned_sample_size"], 204)
        self.assertEqual(study["maximum_sample_size"], 240)
        self.assertEqual(study["permuted_block_sizes"], [4, 6])
        self.assertEqual(study["intervention_seconds"], 720)

    def test_assigned_tasks_are_distinguishable_from_optional_behaviour(self):
        tasks = load_json_instrument("mandatory_tasks_v1.json")
        self.assertEqual([task["origin"] for task in tasks["tasks"]], ["assigned"] * 3)
        self.assertEqual(tasks["optional_participant_initiated_slots"], 2)

    def test_system_prompt_preserves_the_approved_meaning(self):
        prompt = load_text_instrument("ai_system_prompt_v1.txt")
        self.assertIn("Use only the supplied case and evidence.", prompt)
        self.assertIn("Do not invent facts, sources, legal requirements or numerical estimates.", prompt)


if __name__ == "__main__":
    unittest.main()
