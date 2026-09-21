from __future__ import annotations

import unittest
from collections import Counter, defaultdict

from wave2.randomisation import generate_schedule, normalise_stratum


class RandomisationTestCase(unittest.TestCase):
    MASTER_SEED = "wave2-test-seed-that-is-longer-than-32-characters"

    def test_stratum_uses_controlled_session_and_baseline_option(self):
        self.assertEqual(normalise_stratum(" ipa-01 ", "b"), "IPA-01|B")
        self.assertEqual(normalise_stratum(None, "C"), "NO_SESSION|C")

    def test_schedule_is_reproducible_for_a_fixed_secret_seed(self):
        first = generate_schedule(stratum="IPA-01|A", capacity=40, master_seed=self.MASTER_SEED)
        second = generate_schedule(stratum="IPA-01|A", capacity=40, master_seed=self.MASTER_SEED)
        self.assertEqual(first, second)

    def test_each_variable_block_is_balanced(self):
        schedule = generate_schedule(stratum="IPA-01|B", capacity=240, master_seed=self.MASTER_SEED)
        blocks = defaultdict(list)
        for slot in schedule:
            blocks[slot.block_id].append(slot)
        self.assertGreaterEqual(len(schedule), 240)
        for slots in blocks.values():
            self.assertIn(len(slots), {4, 6})
            self.assertEqual(Counter(slot.assignment for slot in slots)["ai"], len(slots) // 2)
            self.assertEqual(Counter(slot.assignment for slot in slots)["control"], len(slots) // 2)

    def test_different_strata_receive_independent_sequences(self):
        first = generate_schedule(stratum="IPA-01|A", capacity=30, master_seed=self.MASTER_SEED)
        second = generate_schedule(stratum="IPA-01|B", capacity=30, master_seed=self.MASTER_SEED)
        self.assertNotEqual(
            [slot.assignment for slot in first],
            [slot.assignment for slot in second],
        )


if __name__ == "__main__":
    unittest.main()
