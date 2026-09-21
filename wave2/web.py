from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any, Callable

from flask import Flask, jsonify, render_template, request, send_from_directory, session

from .domain import DomainValidationError, revision_score
from .instruments import load_json_instrument, load_text_instrument
from .store import Wave2Store


ROOT = Path(__file__).resolve().parents[1]


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(ROOT / "templates_wave2"),
        static_folder=str(ROOT / "static_wave2"),
        static_url_path="/wave2/static",
    )
    app.config.update(
        SECRET_KEY=os.environ.get("WAVE2_SECRET_KEY", "wave2-local-development-key"),
        WAVE2_DB_PATH=os.environ.get("WAVE2_DB_PATH", str(ROOT / "data" / "wave2" / "prototype.sqlite3")),
        WAVE2_RANDOMISATION_SEED=os.environ.get(
            "WAVE2_RANDOMISATION_SEED", "local-wave2-randomisation-seed-change-before-pilot"
        ),
        WAVE2_INTERVENTION_SECONDS=int(os.environ.get("WAVE2_INTERVENTION_SECONDS", "720")),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("RENDER") == "true",
        MAX_CONTENT_LENGTH=2 * 1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    if not app.config.get("TESTING") and os.environ.get("RENDER") == "true":
        raise RuntimeError("Wave 2 SQLite prototype must not be deployed to Render.")
    store = Wave2Store(
        Path(app.config["WAVE2_DB_PATH"]),
        randomisation_seed=app.config["WAVE2_RANDOMISATION_SEED"],
        intervention_seconds=int(app.config["WAVE2_INTERVENTION_SECONDS"]),
    )
    app.extensions["wave2_store"] = store

    def current_participant_id() -> str | None:
        value = session.get("wave2_participant_id")
        return value if isinstance(value, str) else None

    def csrf_ok() -> bool:
        expected = session.get("wave2_csrf")
        supplied = request.headers.get("X-CSRF-Token")
        return bool(expected and supplied and secrets.compare_digest(expected, supplied))

    def participant_required(handler: Callable):
        def wrapped(*args, **kwargs):
            participant_id = current_participant_id()
            if not participant_id:
                return jsonify(error="Няма активна Wave 2 сесия."), 401
            if request.method != "GET" and not csrf_ok():
                return jsonify(error="Невалиден защитен токен."), 403
            return handler(participant_id, *args, **kwargs)

        wrapped.__name__ = handler.__name__
        return wrapped

    def json_payload() -> dict[str, Any]:
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise DomainValidationError("invalid JSON payload")
        return payload

    @app.errorhandler(DomainValidationError)
    def domain_error(error):
        return jsonify(error=str(error)), 400

    @app.get("/")
    def index():
        return render_template(
            "index.html",
            study=load_json_instrument("study_v1.json"),
            case=load_json_instrument("case_ev_v1.json"),
            tasks=load_json_instrument("mandatory_tasks_v1.json"),
            system_prompt=load_text_instrument("ai_system_prompt_v1.txt"),
        )

    @app.get("/wave2/assets/<path:filename>")
    def shared_asset(filename):
        return send_from_directory(ROOT / "static" / "img", filename)

    @app.get("/health")
    def health():
        return jsonify(status="ok", wave="2", mode="prototype", deployed=False)

    @app.post("/api/start")
    def start():
        payload = json_payload()
        record = store.create_participant(payload.get("session_code"))
        session.clear()
        session["wave2_participant_id"] = record["participant_id"]
        session["wave2_csrf"] = secrets.token_urlsafe(24)
        return jsonify(data=record, csrf_token=session["wave2_csrf"]), 201

    @app.get("/api/state")
    @participant_required
    def state(participant_id):
        record = store.get(participant_id)
        if not record:
            session.clear()
            return jsonify(error="Сесията не е намерена."), 404
        return jsonify(data=record, csrf_token=session["wave2_csrf"])

    @app.post("/api/consent")
    @participant_required
    def consent(participant_id):
        return jsonify(data=store.record_consent(participant_id, json_payload()))

    @app.post("/api/eligibility")
    @participant_required
    def eligibility(participant_id):
        return jsonify(data=store.record_eligibility(participant_id, json_payload()))

    @app.post("/api/withdraw")
    @participant_required
    def withdraw(participant_id):
        return jsonify(data=store.withdraw(participant_id))

    @app.post("/api/baseline/lock")
    @participant_required
    def baseline(participant_id):
        payload = json_payload()
        record = store.lock_baseline_and_randomise(
            participant_id,
            payload.get("judgement", {}),
            mismatch_confirmed=payload.get("mismatch_confirmed") is True,
        )
        return jsonify(data=record)

    @app.post("/api/intervention/start")
    @participant_required
    def intervention_start(participant_id):
        return jsonify(data=store.start_intervention(participant_id))

    @app.put("/api/intervention")
    @participant_required
    def intervention_save(participant_id):
        return jsonify(data=store.save_intervention(participant_id, json_payload()))

    @app.post("/api/post")
    @participant_required
    def immediate_post(participant_id):
        payload = json_payload()
        return jsonify(data=store.submit_post(participant_id, payload))

    @app.post("/api/review")
    @participant_required
    def review(participant_id):
        return jsonify(data=store.record_review(participant_id, json_payload()))

    @app.post("/api/final")
    @participant_required
    def final(participant_id):
        payload = json_payload()
        record = store.submit_final(
            participant_id,
            payload.get("judgement", {}),
            payload.get("evaluation", {}),
        )
        record["revision_score"] = revision_score(record["baseline"], record["immediate_post"])
        return jsonify(data=record)

    return app
