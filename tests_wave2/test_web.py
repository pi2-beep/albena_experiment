from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from wave2.web import create_app


def judgement(preferred="B", a=20, b=60, c=20, confidence=70):
    return {
        "preferred": preferred,
        "points_a": str(a),
        "points_b": str(b),
        "points_c": str(c),
        "confidence": str(confidence),
        "rationale": "Професионална обосновка.",
        "mismatch_confirmed": False,
    }


class Wave2WebTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "wave2-test-key",
                "WAVE2_DB_PATH": str(Path(self.temp_dir.name) / "wave2.sqlite3"),
                "WAVE2_RANDOMISATION_SEED": "wave2-test-seed-that-is-at-least-32-characters",
                "WAVE2_INTERVENTION_SECONDS": 0,
            }
        )
        self.client = self.app.test_client()
        started = self.client.post("/api/start", json={"session_code": "IPA-01"})
        self.assertEqual(started.status_code, 201)
        result = started.get_json()
        self.csrf = result["csrf_token"]
        self.participant_id = result["data"]["participant_id"]
        self.headers = {"X-CSRF-Token": self.csrf}

    def tearDown(self):
        self.temp_dir.cleanup()

    def consent_and_qualify(self):
        consent = self.client.post(
            "/api/consent",
            headers=self.headers,
            json={
                "read_information": True,
                "voluntary": True,
                "research_use": True,
                "withdrawal_understood": True,
                "pseudonymisation": True,
            },
        )
        self.assertEqual(consent.status_code, 200)
        eligible = self.client.post(
            "/api/eligibility",
            headers=self.headers,
            json={
                "age_18_plus": True,
                "professional_relevance": True,
                "no_previous_same_case_pilot": True,
            },
        )
        self.assertEqual(eligible.status_code, 200)
        self.assertEqual(eligible.get_json()["data"]["state"], "baseline_draft")

    def lock_and_start(self):
        self.consent_and_qualify()
        baseline = self.client.post(
            "/api/baseline/lock",
            headers=self.headers,
            json={"judgement": judgement(), "mismatch_confirmed": False},
        )
        self.assertEqual(baseline.status_code, 200)
        data = baseline.get_json()["data"]
        self.assertIn(data["assignment"], {"ai", "control"})
        self.assertEqual(data["state"], "randomised")
        intervention = self.client.post("/api/intervention/start", headers=self.headers, json={})
        self.assertEqual(intervention.status_code, 200)
        return intervention.get_json()["data"]

    def test_page_is_a_separate_wave2_prototype(self):
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Албена - Wave 2".encode(), page.data)
        self.assertIn("Локален Wave 2 прототип".encode(), page.data)

    def test_mutating_endpoints_require_csrf(self):
        response = self.client.post("/api/consent", json={})
        self.assertEqual(response.status_code, 403)

    def test_participant_can_withdraw_and_cannot_resume(self):
        response = self.client.post("/api/withdraw", headers=self.headers, json={})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["data"]["state"], "withdrawn")
        consent = self.client.post("/api/consent", headers=self.headers, json={})
        self.assertEqual(consent.status_code, 400)

    def test_ineligible_participant_is_terminal(self):
        self.client.post(
            "/api/consent",
            headers=self.headers,
            json={
                "read_information": True,
                "voluntary": True,
                "research_use": True,
                "withdrawal_understood": True,
                "pseudonymisation": True,
            },
        )
        response = self.client.post(
            "/api/eligibility",
            headers=self.headers,
            json={
                "age_18_plus": True,
                "professional_relevance": False,
                "no_previous_same_case_pilot": True,
            },
        )
        self.assertEqual(response.get_json()["data"]["state"], "ineligible")

    def test_baseline_is_locked_and_randomised_once(self):
        self.lock_and_start()
        second = self.client.post(
            "/api/baseline/lock",
            headers=self.headers,
            json={"judgement": judgement(preferred="C", a=10, b=20, c=70), "mismatch_confirmed": False},
        )
        self.assertEqual(second.status_code, 400)
        state = self.client.get("/api/state").get_json()["data"]
        self.assertEqual(state["baseline"]["preferred"], "B")

    def test_complete_zero_cost_naturalistic_flow(self):
        active = self.lock_and_start()
        self.assertEqual(active["state"], "intervention_active")
        post = self.client.post("/api/post", headers=self.headers, json=judgement(preferred="C", a=10, b=30, c=60, confidence=82))
        self.assertEqual(post.status_code, 200)
        review = self.client.post(
            "/api/review",
            headers=self.headers,
            json={
                "requested_review": True,
                "evaluation": {
                    "perceived_influence": "65",
                    "process_helpfulness": "6",
                    "used_ai_during_intervention": "yes",
                },
            },
        )
        self.assertEqual(review.status_code, 200)
        final = self.client.post(
            "/api/final",
            headers=self.headers,
            json={
                "judgement": judgement(preferred="C", a=10, b=25, c=65, confidence=85),
                "evaluation": review.get_json()["data"]["evaluation"],
            },
        )
        self.assertEqual(final.status_code, 200)
        result = final.get_json()["data"]
        self.assertEqual(result["state"], "completed")
        self.assertEqual(result["revision_score"], 40.0)


if __name__ == "__main__":
    unittest.main()
