from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


INSTRUMENT_DIR = Path(__file__).resolve().parent / "instruments"


class InstrumentIntegrityError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_manifest(name: str = "manifest_v1.json") -> dict[str, Any]:
    manifest_path = INSTRUMENT_DIR / name
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for entry in manifest.get("files", []):
        path = INSTRUMENT_DIR / entry["path"]
        if not path.is_file():
            raise InstrumentIntegrityError(f"Missing frozen instrument: {entry['path']}")
        if _sha256(path) != entry["sha256"]:
            raise InstrumentIntegrityError(f"Frozen instrument changed: {entry['path']}")
    return manifest


def load_json_instrument(filename: str) -> Any:
    load_manifest()
    return json.loads((INSTRUMENT_DIR / filename).read_text(encoding="utf-8"))


def load_text_instrument(filename: str) -> str:
    load_manifest()
    return (INSTRUMENT_DIR / filename).read_text(encoding="utf-8").strip()
