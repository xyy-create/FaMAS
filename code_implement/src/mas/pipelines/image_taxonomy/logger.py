"""Small JSONL logger for Image Taxonomy Agent runs."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaxonomyLogRecord:
    run_id: str
    timestamp: str
    stage: str
    batch_id: str = ""
    status: str = "ok"
    message: str = ""
    metadata: dict[str, Any] | None = None


class JsonlLogger:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, record: TaxonomyLogRecord) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
