"""Filesystem helpers for Taxonomy Agent runs."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
import json
from pathlib import Path
from typing import Any


def jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    return value


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jsonable(value), ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(jsonable(row), ensure_ascii=False) + "\n")


def unique_run_dir(output_root: Path, run_id: str) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    candidate = output_root / run_id
    if not candidate.exists():
        return candidate
    suffix = 2
    while True:
        alternate = output_root / f"{run_id}_{suffix}"
        if not alternate.exists():
            return alternate
        suffix += 1


def ensure_run_tree(run_dir: Path) -> None:
    for rel in [
        "inputs",
        "observations",
        "merge",
        "selected",
        "logs",
        "audit",
    ]:
        (run_dir / rel).mkdir(parents=True, exist_ok=True)
