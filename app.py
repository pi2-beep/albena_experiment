from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template, request, send_file, session

from pdf_export import build_pdf, pdf_path_for
from result_store import ResultArchiveError, archive_pdf


ROOT = Path(__file__).resolve().parent
SESSION_DIR = ROOT / "data" / "sessions"
SESSION_DIR.mkdir(parents=True, exist_ok=True)
try:
    SESSION_LIMIT_SECONDS = max(1, int(os.environ.get("SESSION_LIMIT_SECONDS", "2700")))
except ValueError:
    SESSION_LIMIT_SECONDS = 2700
SESSION_LIMIT = timedelta(seconds=SESSION_LIMIT_SECONDS)

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "local-development-key-change-on-render"),
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("RENDER") == "true",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def deadline_iso() -> str:
    return (datetime.now(timezone.utc).astimezone() + SESSION_LIMIT).isoformat(timespec="seconds")


def time_limit_reached(record: dict[str, Any]) -> bool:
    value = record.get("deadline_at")
    if not isinstance(value, str):
        return False
    try:
        deadline = datetime.fromisoformat(value)
    except ValueError:
        return False
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= deadline.astimezone(timezone.utc)


def current_id() -> str | None:
    value = session.get("sid")
    return value if isinstance(value, str) and re.fullmatch(r"[a-f0-9]{32}", value) else None


def session_path(sid: str) -> Path:
    return SESSION_DIR / f"{sid}.json"


def load_record(sid: str) -> dict[str, Any]:
    path = session_path(sid)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_record(sid: str, record: dict[str, Any]) -> None:
    path = session_path(sid)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def validate_complete(data: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    consent = data.get("consent", {})
    for key in ("read_info", "voluntary", "recording", "no_sensitive", "participate"):
        if consent.get(key) is not True:
            errors.append("Всички декларации за информирано съгласие са задължителни.")
            break

    for section_name, label in (("baseline", "самостоятелната фаза"), ("after_ai", "фазата след ИИ")):
        section = data.get(section_name, {})
        required = ("preferred", "points_a", "points_b", "points_c", "confidence", "rationale")
        if any(section.get(key) in (None, "") for key in required):
            errors.append(f"Липсват задължителни данни в {label}.")
        try:
            total = sum(int(section.get(key, 0)) for key in ("points_a", "points_b", "points_c"))
        except (TypeError, ValueError):
            total = -1
        if total != 100:
            errors.append(f"Точките в {label} трябва да имат сбор 100.")

    interactions = data.get("interactions", [])
    if not isinstance(interactions, list) or len(interactions) < 3:
        errors.append("Необходими са минимум 3 взаимодействия с ИИ.")
    else:
        for index in range(3):
            item = interactions[index] if index < len(interactions) else {}
            if not item.get("prompt") or not item.get("response"):
                errors.append(f"Взаимодействие {index + 1} изисква prompt и отговор от ИИ.")
        for index in range(3, min(len(interactions), 5)):
            item = interactions[index]
            if bool(item.get("prompt")) != bool(item.get("response")):
                errors.append(f"Взаимодействие {index + 1} трябва да съдържа едновременно prompt и отговор.")

    after = data.get("after_ai", {})
    for key in (
        "influence",
        "understand",
        "compare",
        "new_arguments",
        "recommendation_help",
        "evidence_based",
        "reliable",
        "persuasive",
        "balanced",
        "verify_evidence",
        "final_preferred",
        "final_confidence",
    ):
        if after.get(key) in (None, ""):
            errors.append("Липсват задължителни оценки или окончателно решение след ИИ.")
            break

    experience = data.get("experience", {})
    for key in ("frequency", "text_work", "analysis", "options", "comparison", "recommendations", "ai_data", "age_group"):
        if experience.get(key) in (None, ""):
            errors.append("Моля, попълнете всички въпроси за опита с генеративен ИИ.")
            break
    return list(dict.fromkeys(errors))


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/health")
def health():
    return jsonify(status="ok")


@app.post("/api/login")
def login():
    payload = request.get_json(silent=True) or {}
    code = str(payload.get("participant_code", "")).strip()
    if not re.fullmatch(r"[A-Za-zА-Яа-я0-9_-]{2,40}", code):
        return jsonify(error="Кодът трябва да е между 2 и 40 знака и да съдържа само букви, цифри, _ или -."), 400

    sid = secrets.token_hex(16)
    session.clear()
    session["sid"] = sid
    record = {
        "participant_code": code,
        "created_at": now_iso(),
        "deadline_at": deadline_iso(),
        "updated_at": now_iso(),
        "interactions": [{"prompt": "", "response": ""} for _ in range(5)],
    }
    save_record(sid, record)
    return jsonify(record)


@app.get("/api/session")
def get_session():
    sid = current_id()
    if not sid:
        return jsonify(authenticated=False)
    record = load_record(sid)
    if not record:
        session.clear()
        return jsonify(authenticated=False)
    return jsonify(authenticated=True, data=record)


@app.put("/api/session")
def update_session():
    sid = current_id()
    if not sid:
        return jsonify(error="Сесията е изтекла."), 401
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Невалидни данни."), 400
    old = load_record(sid)
    if time_limit_reached(old):
        return jsonify(error="45-минутното време за попълване изтече.", time_limit_reached=True), 409
    participant_code = old.get("participant_code")
    created_at = old.get("created_at") or now_iso()
    deadline_at = old.get("deadline_at") or deadline_iso()
    payload["participant_code"] = participant_code
    payload["created_at"] = created_at
    payload["deadline_at"] = deadline_at
    payload["updated_at"] = now_iso()
    payload["interactions"] = (payload.get("interactions") or [])[:5]
    save_record(sid, payload)
    return jsonify(saved=True, updated_at=payload["updated_at"])


@app.post("/api/pdf")
def create_pdf():
    sid = current_id()
    if not sid:
        return jsonify(error="Сесията е изтекла."), 401
    record = load_record(sid)
    expired = time_limit_reached(record)
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        payload["participant_code"] = record.get("participant_code")
        payload["created_at"] = record.get("created_at") or now_iso()
        payload["deadline_at"] = record.get("deadline_at") or deadline_iso()
        payload["updated_at"] = now_iso()
        payload["interactions"] = (payload.get("interactions") or [])[:5]
        if expired:
            payload["time_limit_reached"] = True
            payload["time_limit_reached_at"] = now_iso()
        record = payload
        save_record(sid, record)
    errors = [] if expired else validate_complete(record)
    if errors:
        return jsonify(error="Формулярът не е завършен.", details=errors), 400
    record["completed_at"] = now_iso()
    save_record(sid, record)
    output = pdf_path_for(sid)
    build_pdf(record, output)
    code = re.sub(r"[^A-Za-zА-Яа-я0-9_-]", "-", str(record.get("participant_code", "participant")))
    archive_status = "disabled"
    try:
        if archive_pdf(output, record, sid):
            archive_status = "saved"
    except ResultArchiveError:
        app.logger.exception("The completed result could not be archived")
        archive_status = "failed"
    response = send_file(output, mimetype="application/pdf", as_attachment=True, download_name=f"rezultati-{code}.pdf")
    response.headers["X-Results-Archive"] = archive_status
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify(logged_out=True)


@app.errorhandler(413)
def too_large(_error):
    return jsonify(error="Данните са твърде големи. Максималният размер е 2 MB."), 413


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)
