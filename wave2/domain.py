from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping


class StudyState(str, Enum):
    STARTED = "started"
    CONSENTED = "consented"
    ELIGIBLE = "eligible"
    BASELINE_DRAFT = "baseline_draft"
    BASELINE_LOCKED = "baseline_locked"
    RANDOMISED = "randomised"
    INTERVENTION_ACTIVE = "intervention_active"
    IMMEDIATE_POST_COMPLETE = "immediate_post_complete"
    REVIEW_DECIDED = "review_decided"
    FINAL_COMPLETE = "final_complete"
    COMPLETED = "completed"
    INELIGIBLE = "ineligible"
    WITHDRAWN = "withdrawn"


ALLOWED_TRANSITIONS: dict[StudyState, frozenset[StudyState]] = {
    StudyState.STARTED: frozenset({StudyState.CONSENTED, StudyState.WITHDRAWN}),
    StudyState.CONSENTED: frozenset({StudyState.ELIGIBLE, StudyState.INELIGIBLE, StudyState.WITHDRAWN}),
    StudyState.ELIGIBLE: frozenset({StudyState.BASELINE_DRAFT, StudyState.WITHDRAWN}),
    StudyState.BASELINE_DRAFT: frozenset({StudyState.BASELINE_LOCKED, StudyState.WITHDRAWN}),
    StudyState.BASELINE_LOCKED: frozenset({StudyState.RANDOMISED, StudyState.WITHDRAWN}),
    StudyState.RANDOMISED: frozenset({StudyState.INTERVENTION_ACTIVE, StudyState.WITHDRAWN}),
    StudyState.INTERVENTION_ACTIVE: frozenset({StudyState.IMMEDIATE_POST_COMPLETE, StudyState.WITHDRAWN}),
    StudyState.IMMEDIATE_POST_COMPLETE: frozenset({StudyState.REVIEW_DECIDED, StudyState.WITHDRAWN}),
    StudyState.REVIEW_DECIDED: frozenset({StudyState.FINAL_COMPLETE, StudyState.WITHDRAWN}),
    StudyState.FINAL_COMPLETE: frozenset({StudyState.COMPLETED}),
    StudyState.COMPLETED: frozenset(),
    StudyState.INELIGIBLE: frozenset(),
    StudyState.WITHDRAWN: frozenset(),
}


class DomainValidationError(ValueError):
    pass


@dataclass(frozen=True)
class LockedJudgement:
    preferred: str
    points_a: int
    points_b: int
    points_c: int
    confidence: int
    rationale: str
    mismatch_confirmed: bool
    locked_at: str
    snapshot_sha256: str

    def allocations(self) -> dict[str, int]:
        return {"A": self.points_a, "B": self.points_b, "C": self.points_c}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def can_transition(current: StudyState, target: StudyState) -> bool:
    return target in ALLOWED_TRANSITIONS[current]


def require_transition(current: StudyState, target: StudyState) -> None:
    if not can_transition(current, target):
        raise DomainValidationError(f"Invalid study transition: {current.value} -> {target.value}")


def _integer(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise DomainValidationError(f"{label} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise DomainValidationError(f"{label} must be an integer") from error
    if str(value).strip() not in {str(parsed), f"+{parsed}"}:
        raise DomainValidationError(f"{label} must be an integer")
    return parsed


def validate_judgement(data: Mapping[str, Any]) -> dict[str, Any]:
    preferred = str(data.get("preferred", "")).strip().upper()
    if preferred not in {"A", "B", "C"}:
        raise DomainValidationError("preferred must be A, B or C")

    allocations = {
        option: _integer(data.get(f"points_{option.lower()}"), f"points_{option.lower()}")
        for option in ("A", "B", "C")
    }
    if any(value < 0 or value > 100 for value in allocations.values()):
        raise DomainValidationError("allocation values must be between 0 and 100")
    if sum(allocations.values()) != 100:
        raise DomainValidationError("allocation values must total exactly 100")

    confidence = _integer(data.get("confidence"), "confidence")
    if confidence < 0 or confidence > 100:
        raise DomainValidationError("confidence must be between 0 and 100")
    rationale = str(data.get("rationale", "")).strip()
    if not rationale:
        raise DomainValidationError("rationale is required")

    highest = max(allocations.values())
    mismatch = allocations[preferred] != highest
    return {
        "preferred": preferred,
        "points_a": allocations["A"],
        "points_b": allocations["B"],
        "points_c": allocations["C"],
        "confidence": confidence,
        "rationale": rationale,
        "preferred_allocation_mismatch": mismatch,
    }


def lock_judgement(
    data: Mapping[str, Any],
    *,
    mismatch_confirmed: bool,
    locked_at: str | None = None,
) -> LockedJudgement:
    validated = validate_judgement(data)
    if validated["preferred_allocation_mismatch"] and not mismatch_confirmed:
        raise DomainValidationError("preferred/allocation mismatch requires explicit confirmation")
    timestamp = locked_at or utc_now_iso()
    snapshot = {
        **validated,
        "mismatch_confirmed": bool(mismatch_confirmed),
        "locked_at": timestamp,
    }
    digest = hashlib.sha256(
        json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return LockedJudgement(
        preferred=validated["preferred"],
        points_a=validated["points_a"],
        points_b=validated["points_b"],
        points_c=validated["points_c"],
        confidence=validated["confidence"],
        rationale=validated["rationale"],
        mismatch_confirmed=bool(mismatch_confirmed),
        locked_at=timestamp,
        snapshot_sha256=digest,
    )


def revision_score(baseline: Mapping[str, Any], post: Mapping[str, Any]) -> float:
    before = validate_judgement(baseline)
    after = validate_judgement(post)
    distance = sum(
        abs(after[f"points_{option}"] - before[f"points_{option}"])
        for option in ("a", "b", "c")
    )
    return distance / 2
