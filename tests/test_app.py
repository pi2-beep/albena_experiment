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

    def test_health_and_page_expose_version(self):
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.get_json()["version"], study_app.APP_VERSION)
        page = self.client.get("/")
        self.assertIn(f"Версия v{study_app.APP_VERSION}".encode("utf-8"), page.data)
        self.assertIn(f"app.js?v={study_app.APP_VERSION}".encode("utf-8"), page.data)
        self.assertIn(f"styles.css?v={study_app.APP_VERSION}".encode("utf-8"), page.data)

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

    def test_pdf_splits_very_long_ai_response_across_pages(self):
        payload = complete_payload()
        payload["interactions"][0]["response"] = (
            "Подробен анализ на доказателствата и възможните последици. " * 2500
        ) + "КРАЙ НА ДЪЛГИЯ ОТГОВОР"
        payload["baseline"]["rationale"] = "Дълга самостоятелна обосновка. " * 120
        payload["after_ai"]["rationale"] = "Дълга окончателна обосновка. " * 120
        output = Path(self.temp_dir.name) / "long-result.pdf"
        study_app.build_pdf(payload, output)
        reader = PdfReader(io.BytesIO(output.read_bytes()))
        text = "\n".join((page.extract_text() or "") for page in reader.pages)
        self.assertGreater(len(reader.pages), 20)
        self.assertIn("КРАЙ НА ДЪЛГИЯ ОТГОВОР", " ".join(text.split()))

    def test_pdf_endpoint_rejects_incomplete_form(self):
        self.login()
        response = self.client.post("/api/pdf")
        self.assertEqual(response.status_code, 400)
        self.assertIn("details", response.get_json())

    def test_pdf_generation_failure_returns_json_diagnostic(self):
        self.login()
        with mock.patch.object(study_app, "build_pdf", side_effect=RuntimeError("layout failed")):
            response = self.client.post("/api/pdf", json=complete_payload())
        self.assertEqual(response.status_code, 500)
        self.assertEqual(response.mimetype, "application/json")
        result = response.get_json()
        self.assertEqual(result["stage"], "pdf-generation")
        self.assertRegex(result["diagnostic_id"], r"^[A-F0-9]{12}$")
        self.assertIn("локалната чернова", result["error"])

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

    def test_server_pdf_download_fallback_for_ios(self):
        self.login()
        output = Path(self.temp_dir.name) / "ios-result.pdf"
        with mock.patch.object(study_app, "pdf_path_for", return_value=output), mock.patch.object(
            study_app, "archive_pdf", return_value=None
        ):
            generated = self.client.post("/api/pdf", json=complete_payload())
            self.assertEqual(generated.status_code, 200)
            generated.close()
            fallback = self.client.get("/api/pdf/download")
        self.assertEqual(fallback.status_code, 200)
        self.assertEqual(fallback.mimetype, "application/pdf")
        self.assertEqual(fallback.headers["X-PDF-Download-Mode"], "server-fallback")
        self.assertEqual(fallback.headers["Cache-Control"], "no-store, private")
        self.assertTrue(fallback.data.startswith(b"%PDF"))
        self.assertGreater(len(fallback.data), 10_000)
        fallback.close()

    def test_archive_failure_does_not_block_pdf_download(self):
        self.login()
        output = Path(self.temp_dir.name) / "result.pdf"
        with mock.patch.object(study_app, "pdf_path_for", return_value=output), mock.patch.object(
            study_app, "archive_pdf", side_effect=study_app.ResultArchiveError("unavailable")
        ):
            response = self.client.post("/api/pdf", json=complete_payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Results-Archive"], "failed")
        self.assertRegex(response.headers["X-Results-Archive-Error-ID"], r"^[A-F0-9]{12}$")
        self.assertEqual(response.headers["X-Results-Archive-Error-Stage"], "ftps-upload")
        self.assertIn("X-Results-Generated-At", response.headers)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertEqual(response.headers["Cache-Control"], "no-store, private")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertTrue(response.data.startswith(b"%PDF"))
        self.assertGreater(len(response.data), 10_000)
        response.close()

    def test_partial_ftp_archive_is_reported_as_information(self):
        self.login()
        output = Path(self.temp_dir.name) / "partial.pdf"
        partial_archive = result_store.ArchiveResult(
            remote_directory="/albena-results/2026-09-01",
            pdf_filename="TEST-01.pdf",
            json_filename="TEST-01.json",
            pdf_saved=True,
            json_saved=False,
        )
        with mock.patch.object(study_app, "pdf_path_for", return_value=output), mock.patch.object(
            study_app, "archive_pdf", return_value=partial_archive
        ):
            response = self.client.post("/api/pdf", json=complete_payload())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Results-Archive"], "partial")
        self.assertEqual(response.headers["X-Results-PDF-Archive"], "saved")
        self.assertEqual(response.headers["X-Results-JSON-Archive"], "failed")
        self.assertEqual(response.headers["X-Results-Archive-Error-Stage"], "ftps-partial")
        self.assertTrue(response.data.startswith(b"%PDF"))
        response.close()

    def test_final_button_uses_generate_and_save_label(self):
        template = (study_app.ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        javascript = (study_app.ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn("Генерирай и запиши", template)
        self.assertIn('button.textContent = "Генерирай и запиши"', javascript)
        self.assertIn('window.location.assign("/api/pdf/download")', javascript)
        self.assertIn("filenameFromDisposition", javascript)
        self.assertNotIn("Подаване и локален запис на PDF", template)

    def test_long_reports_and_submission_guidance_are_visible(self):
        template = (study_app.ROOT / "templates" / "index.html").read_text(encoding="utf-8")
        javascript = (study_app.ROOT / "static" / "app.js").read_text(encoding="utf-8")
        self.assertIn('name="full_transcript" rows="10" maxlength="500000"', template)
        self.assertIn('maxlength="200000"', javascript)
        self.assertIn("автоматично ги разделя на необходимия брой страници", template)
        self.assertIn("не е необходимо да изпращате файла по имейл", template)
        self.assertIn("Докладът е подаден успешно.", javascript)

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

            def nlst(self):
                return list(uploads)

            def size(self, filename):
                return len(uploads[filename])

            def rename(self, source, destination):
                uploads[destination] = uploads.pop(source)

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
        payload = complete_payload()
        payload["completed_at"] = "2026-09-01T12:00:00+03:00"
        with mock.patch.dict(os.environ, environment, clear=True), mock.patch.object(
            result_store, "FTP_TLS", FakeFTPS
        ):
            remote_path = result_store.archive_pdf(pdf, payload, "a" * 32)

        self.assertEqual(remote_path.remote_directory, "/private/results/2026-09-01")
        self.assertTrue(remote_path.complete)
        self.assertTrue(remote_path.pdf_saved)
        self.assertTrue(remote_path.json_saved)
        self.assertEqual(next(value for key, value in uploads.items() if key.endswith(".pdf")), b"example-pdf")
        json_data = next(value for key, value in uploads.items() if key.endswith(".json")).decode("utf-8")
        self.assertIn('"participant_code": "TEST-01"', json_data)

    def test_one_successful_ftp_file_returns_partial_result(self):
        class FakeFTPS:
            def __init__(self, *args, **kwargs):
                pass

            def connect(self, *args, **kwargs):
                return None

            def login(self, *args, **kwargs):
                return None

            def prot_p(self):
                return None

            def set_pasv(self, _passive):
                return None

            def cwd(self, _directory):
                return None

            def mkd(self, _directory):
                return None

            def nlst(self):
                return []

            def quit(self):
                return None

            def close(self):
                return None

        pdf = Path(self.temp_dir.name) / "result.pdf"
        pdf.write_bytes(b"example-pdf")
        environment = {
            "RESULTS_ARCHIVE_BACKEND": "ftp",
            "RESULTS_FTP_HOST": "ftp.example.test",
            "RESULTS_FTP_USERNAME": "albena",
            "RESULTS_FTP_PASSWORD": "secret",
            "SECRET_KEY": "test-key",
        }
        with mock.patch.dict(os.environ, environment, clear=True), mock.patch.object(
            result_store, "FTP_TLS", FakeFTPS
        ), mock.patch.object(result_store, "_upload_ftp_item", side_effect=[True, False]):
            archive = result_store.archive_pdf(pdf, complete_payload(), "a" * 32)
        self.assertIsInstance(archive, result_store.ArchiveResult)
        self.assertTrue(archive.pdf_saved)
        self.assertFalse(archive.json_saved)
        self.assertFalse(archive.complete)

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
