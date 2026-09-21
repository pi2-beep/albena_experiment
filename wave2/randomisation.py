from __future__ import annotations

import hashlib
import hmac
import random
from dataclasses import asdict, dataclass


ARMS = ("ai", "control")
ALLOWED_BLOCK_SIZES = (4, 6)


@dataclass(frozen=True)
class AllocationSlot:
    stratum: str
    sequence: int
    block_id: int
    block_size: int
    block_position: int
    assignment: str

    def as_dict(self) -> dict[str, str | int]:
        return asdict(self)


def normalise_stratum(session_code: str | None, baseline_preferred: str) -> str:
    session = (session_code or "NO_SESSION").strip().upper()
    preferred = baseline_preferred.strip().upper()
    if preferred not in {"A", "B", "C"}:
        raise ValueError("baseline_preferred must be A, B or C")
    if not session or len(session) > 64:
        raise ValueError("session_code must contain between 1 and 64 characters")
    return f"{session}|{preferred}"


def _stratum_seed(master_seed: str, stratum: str) -> int:
    if len(master_seed) < 32:
        raise ValueError("master_seed must contain at least 32 characters")
    digest = hmac.new(master_seed.encode("utf-8"), stratum.encode("utf-8"), hashlib.sha256).digest()
    return int.from_bytes(digest, "big")


def generate_schedule(*, stratum: str, capacity: int, master_seed: str) -> list[AllocationSlot]:
    """Generate concealed balanced blocks; full final blocks are retained."""
    if capacity < 1:
        raise ValueError("capacity must be positive")
    rng = random.Random(_stratum_seed(master_seed, stratum))
    slots: list[AllocationSlot] = []
    block_id = 0
    while len(slots) < capacity:
        block_id += 1
        block_size = rng.choice(ALLOWED_BLOCK_SIZES)
        assignments = ["ai"] * (block_size // 2) + ["control"] * (block_size // 2)
        rng.shuffle(assignments)
        for position, assignment in enumerate(assignments, start=1):
            slots.append(
                AllocationSlot(
                    stratum=stratum,
                    sequence=len(slots) + 1,
                    block_id=block_id,
                    block_size=block_size,
                    block_position=position,
                    assignment=assignment,
                )
            )
    return slots
