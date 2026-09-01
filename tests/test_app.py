from __future__ import annotations

import io
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import app as study_app
import result_store
from pypdf import PdfReader


def complete_payload() -> dict:
    return {
        "participant_code": "TEST-01",
        "consent": {
            "read_info": True,
            "voluntary": True,
            "recording": True,
            "no_sensitive": True,
            "participate": True,
            "date": "2026-08-31",
        },
        "baseline": {
            "preferred": "B",
            "points_a": "20",
            "points_b": "60",
            "points_c": "20",
            "confidence": "70",
            "rationale": "Баланс между стимули и разходи.",
        },
        "interactions": [
            {"prompt": f"Prompt {index}", "response": f"Отговор {index}"}
            for index in range(1, 4)
        ] + [{"prompt": "", "response": ""}, {"prompt": "", "response": ""}],
        "full_transcript": "Пълен разговор с ИИ.",
        "after_ai": {
            "preferred": "C",
            "points_a": "10",
            "points_b": "30",
            "points_c": "60",
            "confidence": "82",
            "rationale": "По-целенасочена подкрепа.",
            "influence": "65",
            "understand": "6",
            "compare": "7",
            "new_arguments": "6",
            "recommendation_help": "5",
            "evidence_based": "6",
            "reliable": "5",
            "persuasive": "5",
            "balanced": "6",
            "verify_evidence": "yes",
            "final_preferred": "C",
            "final_confidence": "85",
        },
        "experience": {
            "frequency": "Често",
            "text_work": "yes",
            "analysis": "yes",
            "options": "yes",
            "comparison": "yes",
            "recommendations": "no",
            "ai_data": "yes",
            "age_group": "До 35 години",
        },
    }


class AppTestCase(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        study_app.SESSION_DIR = Path(self.temp_dir.name) / "sessions"
        study_app.SESSION_DIR.mkdir()
        study_app.app.config.update(TESTING=True, SECRET_KEY="test-key")
        self.client = study_app.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def login(self):
        response = self.client.post("/api/login", json={"participant_code": "TEST-01"})
        self.assertEqual(response.status_code, 200)

    def test_login_and_session_save(self):
        self.login()
        payload = complete_payload()
        response = self.client.put("/api/session", json=payload)
        self.assertEqual(response.status_code, 200)
        restored = self.client.get("/api/session").get_json()
        self.assertTrue(restored["authenticated"])
        self.assertEqual(restored["data"]["baseline"]["preferred"], "B")

    def test_three_interactions_are_required(self):
        payload = complete_payload()
        payload["interactions"][2]["response"] = ""
        errors = study_app.validate_complete(payload)
        self.assertTrue(any("Взаимодействие 3" in error for error in errors))

    def test_optional_interaction_must_have_pair(self):
        payload = complete_payload()
        payload["interactions"][3]["prompt"] = "Само prompt"
        errors = study_app.validate_complete(payload)
        self.assertTrue(any("Взаимодействие 4" in error for error in errors))

    def test_allocations_must_total_one_hundred(self):
        payload = complete_payload()
        payload["baseline"]["points_c"] = "19"
        errors = study_app.validate_complete(payload)
        self.assertTrue(any("сбор 100" in error for error in errors))

    def test_pdf_contains_cyrillic_data(self):
        payload = complete_payload()
        output = Path(self.temp_dir.name) / "result.pdf"
        study_app.build_pdf(payload, output)
        self.assertGreater(output.stat().st_size, 10_000)
        text = "\n".join((page.extract_text() or "") for page in PdfReader(io.BytesIO(output.read_bytes())).pages)
        self.assertIn("Самостоятелна преценка", text)
        self.assertIn("Работа с ИИ", text)
        self.assertIn("Отговор 3", text)

    def test_pdf_endpoint_rejects_incomplete_form(self):
        self.login()
        response = self.client.post("/api/pdf")
        self.assertEqual(response.status_code, 400)
        self.assertIn("details", response.get_json())

    def test_completed_pdf_is_downloaded_and_archived(self):
        self.login()
        output = Path(self.temp_dir.name) / "result.pdf"
        with mock.patch.object(study_app, "pdf_path_for", return_value=output), mock.patch.object(
            study_app, "archive_pdf", return_value="results/2026-08-31/TEST-01-example.pdf"
        ) as archive:
            response = self.client.post("/api/pdf", json=complete_payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Results-Archive"], "saved")
        self.assertEqual(response.mimetype, "application/pdf")
        archive.assert_called_once()
        response.close()

    def test_archive_failure_does_not_block_pdf_download(self):
        self.login()
        output = Path(self.temp_dir.name) / "result.pdf"
        with mock.patch.object(study_app, "pdf_path_for", return_value=output), mock.patch.object(
            study_app, "archive_pdf", side_effect=study_app.ResultArchiveError("unavailable")
        ):
            response = self.client.post("/api/pdf", json=complete_payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Results-Archive"], "failed")
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertEqual(response.headers["Cache-Control"], "no-store, private")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertTrue(response.data.startswith(b"%PDF"))
        self.assertGreater(len(response.data), 10_000)
        response.close()

    def test_expired_session_accepts_partial_pdf_and_blocks_edits(self):
        self.login()
        with self.client.session_transaction() as browser_session:
            sid = browser_session["sid"]
        record = study_app.load_record(sid)
        record["deadline_at"] = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
        study_app.save_record(sid, record)

        update = self.client.put("/api/session", json={"baseline": {"rationale": "Незавършен отговор"}})
        self.assertEqual(update.status_code, 409)
        self.assertTrue(update.get_json()["time_limit_reached"])

        output = Path(self.temp_dir.name) / "expired.pdf"
        partial = {"baseline": {"rationale": "Незавършен отговор"}, "interactions": []}
        with mock.patch.object(study_app, "pdf_path_for", return_value=output), mock.patch.object(
            study_app, "archive_pdf", return_value=None
        ):
            response = self.client.post("/api/pdf", json=partial)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Results-Archive"], "disabled")
        self.assertGreater(len(response.data), 10_000)
        response.close()

    def test_github_host_keys_are_available_without_network_lookup(self):
        self.assertIn("github.com ssh-ed25519", result_store.GITHUB_KNOWN_HOSTS)
        self.assertIn("github.com ecdsa-sha2-nistp256", result_store.GITHUB_KNOWN_HOSTS)

    def test_ftps_archive_uploads_pdf_and_json(self):
        uploads: dict[str, bytes] = {}

        class FakeFTPS:
            def __init__(self, *args, **kwargs):
                self.connected = False

            def connect(self, host, port, timeout):
                self.connected = (host, port, timeout)

            def login(self, username, password):
                self.credentials = (username, password)

            def prot_p(self):
                self.protected = True

            def set_pasv(self, passive):
                self.passive = passive

            def cwd(self, _directory):
                return None

            def mkd(self, _directory):
                return None

            def storbinary(self, command, stream):
                uploads[command.removeprefix("STOR ")] = stream.read()

            def quit(self):
                return None

            def close(self):
                return None

            def delete(self, filename):
                uploads.pop(filename, None)

        pdf = Path(self.temp_dir.name) / "result.pdf"
        pdf.write_bytes(b"example-pdf")
        environment = {
            "RESULTS_ARCHIVE_BACKEND": "ftp",
            "RESULTS_FTP_HOST": "ftp.example.test",
            "RESULTS_FTP_USERNAME": "albena",
            "RESULTS_FTP_PASSWORD": "secret",
            "RESULTS_FTP_DIRECTORY": "/private/results",
            "RESULTS_FTP_TLS": "true",
            "RESULTS_FTP_TLS_SERVER_NAME": "ftp.hosting.example",
            "SECRET_KEY": "test-key",
        }
        with mock.patch.dict(os.environ, environment, clear=True), mock.patch.object(
            result_store, "FTP_TLS", FakeFTPS
        ):
            remote_path = result_store.archive_pdf(pdf, complete_payload(), "a" * 32)

        self.assertTrue(remote_path.startswith("/private/results/"))
        self.assertTrue(remote_path.endswith(".pdf"))
        self.assertEqual(next(value for key, value in uploads.items() if key.endswith(".pdf")), b"example-pdf")
        json_data = next(value for key, value in uploads.items() if key.endswith(".json")).decode("utf-8")
        self.assertIn('"participant_code": "TEST-01"', json_data)

    def test_ftp_archive_requires_private_credentials(self):
        pdf = Path(self.temp_dir.name) / "result.pdf"
        pdf.write_bytes(b"example-pdf")
        with mock.patch.dict(os.environ, {"RESULTS_ARCHIVE_BACKEND": "ftp"}, clear=True):
            with self.assertRaises(result_store.ResultArchiveError):
                result_store.archive_pdf(pdf, complete_payload(), "a" * 32)

    def test_ftp_backend_never_calls_github_archive(self):
        pdf = Path(self.temp_dir.name) / "result.pdf"
        pdf.write_bytes(b"example-pdf")
        with mock.patch.dict(os.environ, {"RESULTS_ARCHIVE_BACKEND": "ftp"}, clear=True), mock.patch.object(
            result_store, "_archive_to_ftp", return_value="/albena-results/result.pdf"
        ) as ftp_archive, mock.patch.object(result_store, "_archive_to_github") as github_archive:
            result = result_store.archive_pdf(pdf, complete_payload(), "a" * 32)
        self.assertEqual(result, "/albena-results/result.pdf")
        ftp_archive.assert_called_once()
        github_archive.assert_not_called()


if __name__ == "__main__":
    unittest.main()
