"""JSON and JSONL logging helpers for IPA."""

from __future__ import annotations

from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any


@dataclass
class JSONLRecord:
    run_id: str
    timestamp: str
    round: str
    section_md: str
    image_id: str
    image_link: str
    image_path: str
    image_exists: bool
    image_type_id: str
    kg_value: str
    status: str
    audit_status: str
    inserted: bool
    mock: bool
    prompt: str
    raw_response: str
    error: str
    prompt_template_version: str
    batch_id: str = ""
    taxonomy_version: str = ""


class JsonlLogger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8")

    def write(self, record: JSONLRecord | dict[str, Any]) -> None:
        payload = asdict(record) if is_dataclass(record) else record
        self._handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        self._handle.flush()

    def close(self) -> None:
        self._handle.close()


def utc_timestamp() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
