from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .domain import DomainValidationError, StudyState, lock_judgement, require_transition, utc_now_iso
from .randomisation import generate_schedule, normalise_stratum


class PostgresWave2Store:
    """Transactional PostgreSQL store used by the production deployment."""

    def __init__(self, dsn: str, *, randomisation_seed: str, intervention_seconds: int = 720):
        if not dsn.startswith(("postgresql://", "postgres://")):
            raise ValueError("DATABASE_URL must be a PostgreSQL connection string")
        self.dsn = dsn
        self.randomisation_seed = randomisation_seed
        self.intervention_seconds = intervention_seconds
        self.initialise()

    def connect(self):
        return psycopg.connect(self.dsn, row_factory=dict_row, connect_timeout=10)

    def initialise(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS wave2_runtime_participants (
                    participant_id UUID PRIMARY KEY,
                    session_code TEXT NOT NULL,
                    state TEXT NOT NULL,
                    assignment TEXT,
                    record_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    intervention_started_at TIMESTAMPTZ,
                    intervention_deadline_at TIMESTAMPTZ
                );
                CREATE TABLE IF NOT EXISTS wave2_runtime_randomisation_slots (
                    slot_id UUID PRIMARY KEY,
                    stratum TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    block_id INTEGER NOT NULL,
                    block_size INTEGER NOT NULL CHECK (block_size IN (4, 6)),
                    block_position INTEGER NOT NULL,
                    assignment TEXT NOT NULL CHECK (assignment IN ('ai', 'control')),
                    participant_id UUID UNIQUE REFERENCES wave2_runtime_participants(participant_id),
                    assigned_at TIMESTAMPTZ,
                    UNIQUE (stratum, sequence)
                );
                CREATE TABLE IF NOT EXISTS wave2_runtime_audit_events (
                    event_id UUID PRIMARY KEY,
                    participant_id UUID NOT NULL REFERENCES wave2_runtime_participants(participant_id),
                    event_type TEXT NOT NULL,
                    occurred_at TIMESTAMPTZ NOT NULL,
                    payload_json JSONB NOT NULL
                );
                CREATE INDEX IF NOT EXISTS wave2_randomisation_available_idx
                    ON wave2_runtime_randomisation_slots(stratum, sequence)
                    WHERE participant_id IS NULL;
                CREATE INDEX IF NOT EXISTS wave2_audit_participant_time_idx
                    ON wave2_runtime_audit_events(participant_id, occurred_at);
                """
            )

    @staticmethod
    def _iso(value: Any) -> str | None:
        if value is None or isinstance(value, str):
            return value
        return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")

    def _audit(self, connection, participant_id: str, event_type: str, payload: Any) -> None:
        connection.execute(
            "INSERT INTO wave2_runtime_audit_events VALUES (%s, %s, %s, %s, %s)",
            (str(uuid.uuid4()), participant_id, event_type, utc_now_iso(), Jsonb(payload)),
        )

    def create_participant(self, session_code: str | None = None) -> dict[str, Any]:
        participant_id = str(uuid.uuid4())
        session = (session_code or "NO_SESSION").strip().upper() or "NO_SESSION"
        if len(session) > 64:
            raise DomainValidationError("session code is too long")
        now = utc_now_iso()
        record = {
            "participant_id": participant_id,
            "study_version": "wave2-draft-1",
            "session_code": session,
            "state": StudyState.STARTED.value,
            "created_at": now,
        }
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO wave2_runtime_participants
                    (participant_id, session_code, state, assignment, record_json, created_at, updated_at)
                VALUES (%s, %s, %s, NULL, %s, %s, %s)
                """,
                (participant_id, session, StudyState.STARTED.value, Jsonb(record), now, now),
            )
            self._audit(connection, participant_id, "participant_started", {"session_code": session})
        return record

    def get(self, participant_id: str) -> dict[str, Any] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT * FROM wave2_runtime_participants WHERE participant_id = %s", (participant_id,)
            ).fetchone()
        if row is None:
            return None
        record = dict(row["record_json"])
        record.update(
            state=row["state"],
            assignment=row["assignment"],
            intervention_started_at=self._iso(row["intervention_started_at"]),
            intervention_deadline_at=self._iso(row["intervention_deadline_at"]),
        )
        return record

    def _transition(
        self,
        connection,
        participant_id: str,
        target: StudyState,
        *,
        patch: Mapping[str, Any] | None = None,
        event_type: str,
    ) -> dict[str, Any]:
        row = connection.execute(
            "SELECT state, record_json FROM wave2_runtime_participants WHERE participant_id = %s FOR UPDATE",
            (participant_id,),
        ).fetchone()
        if row is None:
            raise DomainValidationError("participant not found")
        require_transition(StudyState(row["state"]), target)
        record = dict(row["record_json"])
        if patch:
            record.update(patch)
        now = utc_now_iso()
        record["state"] = target.value
        record["updated_at"] = now
        connection.execute(
            """
            UPDATE wave2_runtime_participants
            SET state = %s, record_json = %s, updated_at = %s
            WHERE participant_id = %s
            """,
            (target.value, Jsonb(record), now, participant_id),
        )
        self._audit(connection, participant_id, event_type, dict(patch or {}))
        return record

    def record_consent(self, participant_id: str, consent: Mapping[str, Any]) -> dict[str, Any]:
        required = ("read_information", "voluntary", "research_use", "withdrawal_understood", "pseudonymisation")
        if any(consent.get(key) is not True for key in required):
            raise DomainValidationError("all consent declarations are required")
        with self.connect() as connection:
            return self._transition(
                connection,
                participant_id,
                StudyState.CONSENTED,
                patch={"consent": {**dict(consent), "consented_at": utc_now_iso()}},
                event_type="consent_recorded",
            )

    def withdraw(self, participant_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            return self._transition(
                connection,
                participant_id,
                StudyState.WITHDRAWN,
                patch={"withdrawn_at": utc_now_iso()},
                event_type="participant_withdrew",
            )

    def record_eligibility(self, participant_id: str, eligibility: Mapping[str, Any]) -> dict[str, Any]:
        fields = ("age_18_plus", "professional_relevance", "no_previous_same_case_pilot")
        eligible = all(eligibility.get(key) is True for key in fields)
        payload = {"eligibility": {**dict(eligibility), "eligible": eligible, "assessed_at": utc_now_iso()}}
        with self.connect() as connection:
            record = self._transition(
                connection,
                participant_id,
                StudyState.ELIGIBLE if eligible else StudyState.INELIGIBLE,
                patch=payload,
                event_type="eligibility_assessed",
            )
            if eligible:
                record = self._transition(
                    connection,
                    participant_id,
                    StudyState.BASELINE_DRAFT,
                    event_type="baseline_opened",
                )
            return record

    def _ensure_slots(self, connection, stratum: str) -> None:
        connection.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"wave2:{stratum}",))
        count = connection.execute(
            "SELECT COUNT(*) AS count FROM wave2_runtime_randomisation_slots WHERE stratum = %s", (stratum,)
        ).fetchone()["count"]
        if count:
            return
        with connection.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO wave2_runtime_randomisation_slots
                    (slot_id, stratum, sequence, block_id, block_size, block_position, assignment)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    (
                        str(uuid.uuid4()),
                        slot.stratum,
                        slot.sequence,
                        slot.block_id,
                        slot.block_size,
                        slot.block_position,
                        slot.assignment,
                    )
                    for slot in generate_schedule(
                        stratum=stratum, capacity=240, master_seed=self.randomisation_seed
                    )
                ],
            )

    def lock_baseline_and_randomise(
        self,
        participant_id: str,
        baseline: Mapping[str, Any],
        *,
        mismatch_confirmed: bool,
    ) -> dict[str, Any]:
        locked = lock_judgement(baseline, mismatch_confirmed=mismatch_confirmed)
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT state, session_code, record_json
                FROM wave2_runtime_participants
                WHERE participant_id = %s
                FOR UPDATE
                """,
                (participant_id,),
            ).fetchone()
            if row is None or row["state"] != StudyState.BASELINE_DRAFT.value:
                raise DomainValidationError("baseline is unavailable or already locked")
            stratum = normalise_stratum(row["session_code"], locked.preferred)
            self._ensure_slots(connection, stratum)
            slot = connection.execute(
                """
                SELECT * FROM wave2_runtime_randomisation_slots
                WHERE stratum = %s AND participant_id IS NULL
                ORDER BY sequence
                LIMIT 1
                FOR UPDATE SKIP LOCKED
                """,
                (stratum,),
            ).fetchone()
            if slot is None:
                raise DomainValidationError("randomisation schedule is exhausted")
            now = utc_now_iso()
            connection.execute(
                """
                UPDATE wave2_runtime_randomisation_slots
                SET participant_id = %s, assigned_at = %s
                WHERE slot_id = %s AND participant_id IS NULL
                """,
                (participant_id, now, slot["slot_id"]),
            )
            record = dict(row["record_json"])
            record["baseline"] = {
                "preferred": locked.preferred,
                "points_a": locked.points_a,
                "points_b": locked.points_b,
                "points_c": locked.points_c,
                "confidence": locked.confidence,
                "rationale": locked.rationale,
                "mismatch_confirmed": locked.mismatch_confirmed,
                "locked_at": locked.locked_at,
                "snapshot_sha256": locked.snapshot_sha256,
            }
            record["randomisation"] = {
                "stratum": stratum,
                "assignment": slot["assignment"],
                "schedule_version": "wave2-blocks-v1",
                "assigned_at": now,
            }
            record["assignment"] = slot["assignment"]
            record["state"] = StudyState.RANDOMISED.value
            record["updated_at"] = now
            connection.execute(
                """
                UPDATE wave2_runtime_participants
                SET state = %s, assignment = %s, record_json = %s, updated_at = %s
                WHERE participant_id = %s
                """,
                (StudyState.RANDOMISED.value, slot["assignment"], Jsonb(record), now, participant_id),
            )
            self._audit(connection, participant_id, "baseline_locked", {"snapshot_sha256": locked.snapshot_sha256})
            self._audit(
                connection,
                participant_id,
                "randomisation_assigned",
                {"stratum": stratum, "assignment": slot["assignment"], "slot_id": str(slot["slot_id"])},
            )
            return record

    def start_intervention(self, participant_id: str) -> dict[str, Any]:
        started = datetime.now(timezone.utc)
        deadline = started + timedelta(seconds=self.intervention_seconds)
        started_iso = started.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        deadline_iso = deadline.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        with self.connect() as connection:
            record = self._transition(
                connection,
                participant_id,
                StudyState.INTERVENTION_ACTIVE,
                patch={"intervention": {"started_at": started_iso, "deadline_at": deadline_iso, "entries": []}},
                event_type="intervention_started",
            )
            connection.execute(
                """
                UPDATE wave2_runtime_participants
                SET intervention_started_at = %s, intervention_deadline_at = %s
                WHERE participant_id = %s
                """,
                (started_iso, deadline_iso, participant_id),
            )
            return record

    def save_intervention(self, participant_id: str, intervention: Mapping[str, Any]) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT state, intervention_deadline_at, record_json
                FROM wave2_runtime_participants
                WHERE participant_id = %s
                FOR UPDATE
                """,
                (participant_id,),
            ).fetchone()
            if row is None or row["state"] != StudyState.INTERVENTION_ACTIVE.value:
                raise DomainValidationError("intervention is not active")
            if datetime.now(timezone.utc) > row["intervention_deadline_at"]:
                raise DomainValidationError("intervention time has ended")
            record = dict(row["record_json"])
            record["intervention"] = {
                **record.get("intervention", {}),
                **dict(intervention),
                "updated_at": utc_now_iso(),
            }
            now = utc_now_iso()
            connection.execute(
                """
                UPDATE wave2_runtime_participants SET record_json = %s, updated_at = %s
                WHERE participant_id = %s
                """,
                (Jsonb(record), now, participant_id),
            )
            self._audit(
                connection,
                participant_id,
                "intervention_saved",
                {"entry_count": len(intervention.get("entries", []))},
            )
            return record

    def submit_post(self, participant_id: str, post: Mapping[str, Any]) -> dict[str, Any]:
        validated = lock_judgement(post, mismatch_confirmed=bool(post.get("mismatch_confirmed")))
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT state, intervention_deadline_at
                FROM wave2_runtime_participants
                WHERE participant_id = %s
                FOR UPDATE
                """,
                (participant_id,),
            ).fetchone()
            if row is None or row["state"] != StudyState.INTERVENTION_ACTIVE.value:
                raise DomainValidationError("immediate post measure is unavailable")
            if datetime.now(timezone.utc) < row["intervention_deadline_at"]:
                raise DomainValidationError("the 12-minute intervention is still active")
            return self._transition(
                connection,
                participant_id,
                StudyState.IMMEDIATE_POST_COMPLETE,
                patch={"immediate_post": {**validated.__dict__, "submitted_at": utc_now_iso()}},
                event_type="immediate_post_submitted",
            )

    def record_review(self, participant_id: str, review: Mapping[str, Any]) -> dict[str, Any]:
        if review.get("requested_review") not in {True, False}:
            raise DomainValidationError("review decision is required")
        evaluation = review.get("evaluation", {})
        try:
            influence = int(evaluation.get("perceived_influence"))
            helpfulness = int(evaluation.get("process_helpfulness"))
        except (TypeError, ValueError) as error:
            raise DomainValidationError("experience evaluation is incomplete") from error
        if not 0 <= influence <= 100 or not 1 <= helpfulness <= 7:
            raise DomainValidationError("experience evaluation is outside the allowed range")
        if evaluation.get("used_ai_during_intervention") not in {"yes", "no"}:
            raise DomainValidationError("AI use confirmation is required")
        with self.connect() as connection:
            return self._transition(
                connection,
                participant_id,
                StudyState.REVIEW_DECIDED,
                patch={
                    "review": {"requested_review": review["requested_review"], "decided_at": utc_now_iso()},
                    "evaluation": {**dict(evaluation), "submitted_at": utc_now_iso()},
                },
                event_type="review_decided",
            )

    def submit_final(
        self, participant_id: str, final: Mapping[str, Any], evaluation: Mapping[str, Any]
    ) -> dict[str, Any]:
        validated = lock_judgement(final, mismatch_confirmed=bool(final.get("mismatch_confirmed")))
        try:
            influence = int(evaluation.get("perceived_influence"))
        except (TypeError, ValueError) as error:
            raise DomainValidationError("perceived influence must be between 0 and 100") from error
        if not 0 <= influence <= 100:
            raise DomainValidationError("perceived influence must be between 0 and 100")
        with self.connect() as connection:
            record = self._transition(
                connection,
                participant_id,
                StudyState.FINAL_COMPLETE,
                patch={
                    "final": {**validated.__dict__, "submitted_at": utc_now_iso()},
                    "evaluation": {**dict(evaluation), "submitted_at": utc_now_iso()},
                },
                event_type="final_submitted",
            )
            return self._transition(
                connection,
                participant_id,
                StudyState.COMPLETED,
                patch={"completed_at": utc_now_iso()},
                event_type="participant_completed",
            )
