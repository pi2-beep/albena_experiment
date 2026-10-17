from __future__ import annotations

from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


class Wave1PostgresStore:
    """Durable Wave 1 session storage for the IPA deployment."""

    def __init__(self, database_url: str):
        self.database_url = database_url
        self.initialise()

    def connect(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)

    def initialise(self) -> None:
        with self.connect() as connection:
            connection.execute("SELECT pg_advisory_xact_lock(hashtext('wave1-runtime-schema-v1'))")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS wave1_runtime_sessions (
                    session_id TEXT PRIMARY KEY,
                    participant_code TEXT NOT NULL,
                    record_json JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                    completed_at TIMESTAMPTZ
                );
                CREATE INDEX IF NOT EXISTS wave1_sessions_participant_code_idx
                    ON wave1_runtime_sessions(participant_code);
                CREATE INDEX IF NOT EXISTS wave1_sessions_updated_at_idx
                    ON wave1_runtime_sessions(updated_at);
                """
            )

    def load(self, session_id: str) -> dict[str, Any]:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT record_json FROM wave1_runtime_sessions WHERE session_id = %s",
                (session_id,),
            ).fetchone()
        return dict(row["record_json"]) if row else {}

    def save(self, session_id: str, record: dict[str, Any]) -> None:
        participant_code = str(record.get("participant_code", "NO_CODE"))[:40]
        completed_at = record.get("completed_at")
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO wave1_runtime_sessions
                    (session_id, participant_code, record_json, created_at, updated_at, completed_at)
                VALUES (%s, %s, %s, COALESCE(%s::timestamptz, now()), now(), %s::timestamptz)
                ON CONFLICT (session_id) DO UPDATE SET
                    participant_code = EXCLUDED.participant_code,
                    record_json = EXCLUDED.record_json,
                    updated_at = now(),
                    completed_at = EXCLUDED.completed_at
                """,
                (
                    session_id,
                    participant_code,
                    Jsonb(record),
                    record.get("created_at"),
                    completed_at,
                ),
            )
