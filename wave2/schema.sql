-- Wave 2 PostgreSQL draft schema. Apply through versioned migrations, not manually.

CREATE TABLE instrument_versions (
    instrument_version TEXT PRIMARY KEY,
    manifest_sha256 CHAR(64) NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('draft', 'frozen', 'retired')),
    created_at TIMESTAMPTZ NOT NULL,
    frozen_at TIMESTAMPTZ
);

CREATE TABLE study_sessions (
    session_code TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE invitation_tokens (
    token_hash CHAR(64) PRIMARY KEY,
    session_code TEXT NOT NULL REFERENCES study_sessions(session_code),
    issued_at TIMESTAMPTZ NOT NULL,
    redeemed_at TIMESTAMPTZ,
    revoked_at TIMESTAMPTZ,
    participant_id UUID UNIQUE
);

CREATE TABLE participants (
    participant_id UUID PRIMARY KEY,
    study_version TEXT NOT NULL,
    instrument_version TEXT NOT NULL,
    session_code TEXT NOT NULL,
    state TEXT NOT NULL,
    invitation_token_hash TEXT UNIQUE,
    created_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    withdrawn_at TIMESTAMPTZ,
    CONSTRAINT participant_state_valid CHECK (state IN (
        'started', 'consented', 'eligible', 'baseline_draft', 'baseline_locked',
        'randomised', 'intervention_active', 'immediate_post_complete',
        'review_decided', 'final_complete', 'completed', 'ineligible', 'withdrawn'
    ))
);

ALTER TABLE invitation_tokens
    ADD CONSTRAINT invitation_participant_fk
    FOREIGN KEY (participant_id) REFERENCES participants(participant_id);

CREATE TABLE consent_records (
    participant_id UUID PRIMARY KEY REFERENCES participants(participant_id),
    consent_version TEXT NOT NULL,
    voluntary BOOLEAN NOT NULL,
    research_use BOOLEAN NOT NULL,
    withdrawal_understood BOOLEAN NOT NULL,
    pseudonymisation_understood BOOLEAN NOT NULL,
    consented_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE eligibility_records (
    participant_id UUID PRIMARY KEY REFERENCES participants(participant_id),
    age_18_plus BOOLEAN NOT NULL,
    professional_relevance BOOLEAN NOT NULL,
    no_previous_same_case_pilot BOOLEAN NOT NULL,
    eligible BOOLEAN NOT NULL,
    assessed_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE baseline_judgements (
    participant_id UUID PRIMARY KEY REFERENCES participants(participant_id),
    preferred CHAR(1) NOT NULL CHECK (preferred IN ('A', 'B', 'C')),
    points_a SMALLINT NOT NULL CHECK (points_a BETWEEN 0 AND 100),
    points_b SMALLINT NOT NULL CHECK (points_b BETWEEN 0 AND 100),
    points_c SMALLINT NOT NULL CHECK (points_c BETWEEN 0 AND 100),
    confidence SMALLINT NOT NULL CHECK (confidence BETWEEN 0 AND 100),
    rationale TEXT NOT NULL,
    mismatch_confirmed BOOLEAN NOT NULL,
    snapshot_sha256 CHAR(64) NOT NULL,
    locked_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT baseline_total_100 CHECK (points_a + points_b + points_c = 100)
);

CREATE TABLE randomisation_slots (
    slot_id UUID PRIMARY KEY,
    stratum TEXT NOT NULL,
    assignment TEXT NOT NULL CHECK (assignment IN ('ai', 'control')),
    schedule_version TEXT NOT NULL,
    block_id INTEGER NOT NULL,
    block_size SMALLINT NOT NULL CHECK (block_size IN (4, 6)),
    block_position SMALLINT NOT NULL,
    allocation_sequence INTEGER NOT NULL,
    participant_id UUID UNIQUE REFERENCES participants(participant_id),
    reserved_at TIMESTAMPTZ,
    UNIQUE (stratum, schedule_version, allocation_sequence)
);

CREATE TABLE randomisation_assignments (
    participant_id UUID PRIMARY KEY REFERENCES participants(participant_id),
    slot_id UUID NOT NULL UNIQUE REFERENCES randomisation_slots(slot_id),
    stratum TEXT NOT NULL,
    assignment TEXT NOT NULL CHECK (assignment IN ('ai', 'control')),
    schedule_version TEXT NOT NULL,
    assigned_at TIMESTAMPTZ NOT NULL,
    audit_payload_sha256 CHAR(64) NOT NULL
);

CREATE TABLE intervention_sessions (
    participant_id UUID PRIMARY KEY REFERENCES participants(participant_id),
    assignment TEXT NOT NULL CHECK (assignment IN ('ai', 'control')),
    started_at TIMESTAMPTZ NOT NULL,
    deadline_at TIMESTAMPTZ NOT NULL,
    ended_at TIMESTAMPTZ,
    completion_reason TEXT,
    CONSTRAINT intervention_deadline_after_start CHECK (deadline_at > started_at)
);

CREATE TABLE intervention_tasks (
    task_id UUID PRIMARY KEY,
    participant_id UUID NOT NULL REFERENCES participants(participant_id),
    sequence SMALLINT NOT NULL CHECK (sequence BETWEEN 1 AND 5),
    task_origin TEXT NOT NULL CHECK (task_origin IN ('assigned', 'participant_optional')),
    mandatory_task_id TEXT,
    participant_input TEXT NOT NULL,
    reflection_text TEXT,
    opened_at TIMESTAMPTZ,
    submitted_at TIMESTAMPTZ,
    UNIQUE (participant_id, sequence)
);

CREATE TABLE ai_messages (
    message_id UUID PRIMARY KEY,
    participant_id UUID NOT NULL REFERENCES participants(participant_id),
    task_id UUID NOT NULL REFERENCES intervention_tasks(task_id),
    prompt_text TEXT NOT NULL,
    response_text TEXT NOT NULL,
    tool_name TEXT NOT NULL,
    access_plan TEXT NOT NULL CHECK (access_plan IN ('free', 'paid', 'unknown')),
    browsing_used TEXT NOT NULL CHECK (browsing_used IN ('yes', 'no', 'unknown')),
    self_reported_model TEXT,
    prompt_copied_at TIMESTAMPTZ,
    response_pasted_at TIMESTAMPTZ,
    character_length INTEGER,
    UNIQUE (participant_id, task_id)
);

CREATE TABLE immediate_post_judgements (
    participant_id UUID PRIMARY KEY REFERENCES participants(participant_id),
    preferred CHAR(1) NOT NULL CHECK (preferred IN ('A', 'B', 'C')),
    points_a SMALLINT NOT NULL CHECK (points_a BETWEEN 0 AND 100),
    points_b SMALLINT NOT NULL CHECK (points_b BETWEEN 0 AND 100),
    points_c SMALLINT NOT NULL CHECK (points_c BETWEEN 0 AND 100),
    confidence SMALLINT NOT NULL CHECK (confidence BETWEEN 0 AND 100),
    rationale TEXT NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT immediate_post_total_100 CHECK (points_a + points_b + points_c = 100)
);

CREATE TABLE experience_evaluations (
    participant_id UUID PRIMARY KEY REFERENCES participants(participant_id),
    perceived_influence SMALLINT NOT NULL CHECK (perceived_influence BETWEEN 0 AND 100),
    responses JSONB NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL
);

CREATE TABLE review_decisions (
    participant_id UUID PRIMARY KEY REFERENCES participants(participant_id),
    requested_review BOOLEAN NOT NULL,
    decided_at TIMESTAMPTZ NOT NULL,
    review_opened_at TIMESTAMPTZ,
    review_completed_at TIMESTAMPTZ
);

CREATE TABLE final_judgements (
    participant_id UUID PRIMARY KEY REFERENCES participants(participant_id),
    preferred CHAR(1) NOT NULL CHECK (preferred IN ('A', 'B', 'C')),
    points_a SMALLINT NOT NULL CHECK (points_a BETWEEN 0 AND 100),
    points_b SMALLINT NOT NULL CHECK (points_b BETWEEN 0 AND 100),
    points_c SMALLINT NOT NULL CHECK (points_c BETWEEN 0 AND 100),
    confidence SMALLINT NOT NULL CHECK (confidence BETWEEN 0 AND 100),
    rationale TEXT NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL,
    CONSTRAINT final_total_100 CHECK (points_a + points_b + points_c = 100)
);

CREATE TABLE audit_events (
    event_id UUID PRIMARY KEY,
    participant_id UUID REFERENCES participants(participant_id),
    event_type TEXT NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    request_id TEXT,
    payload JSONB NOT NULL,
    payload_sha256 CHAR(64) NOT NULL
);

CREATE INDEX audit_events_participant_time_idx ON audit_events(participant_id, occurred_at);
CREATE INDEX ai_messages_participant_idx ON ai_messages(participant_id);
CREATE INDEX randomisation_slots_available_idx
    ON randomisation_slots(stratum, schedule_version, allocation_sequence)
    WHERE participant_id IS NULL;
