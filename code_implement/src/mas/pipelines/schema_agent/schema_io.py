"""Filesystem helpers for Schema Agent runs."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
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


def make_run_id(mock: bool, label: str | None = None, now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    prefix = "schema_mock" if mock else "schema_real"
    suffix = f"_{label}" if label else ""
    return f"{prefix}_{stamp}{suffix}"


def unique_run_dir(root: Path, run_id: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    candidate = root / run_id
    if not candidate.exists():
        return candidate
    suffix = 2
    while True:
        alternate = root / f"{run_id}_{suffix}"
        if not alternate.exists():
            return alternate
        suffix += 1


def ensure_work_tree(run_dir: Path) -> None:
    for rel in ["inputs", "observations", "merge", "audit", "logs"]:
        (run_dir / rel).mkdir(parents=True, exist_ok=True)


def ensure_output_tree(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)


def write_input_snapshot(
    *,
    run_dir: Path,
    section_contexts: list[Any],
    sample_units: list[Any],
    standards: list[dict[str, str]],
) -> None:
    write_json(run_dir / "inputs" / "section_contexts.json", [context.to_json() for context in section_contexts])
    write_jsonl(run_dir / "inputs" / "sample_units.jsonl", [sample.to_json() for sample in sample_units])
    write_json(
        run_dir / "inputs" / "standards_manifest.json",
        [{"file": item["file"], "path": item["path"], "chars": len(item["content"])} for item in standards],
    )


def write_final_package(output_dir: Path, final_schema: dict[str, Any], report: str, manifest: dict[str, Any]) -> None:
    ensure_output_tree(output_dir)
    write_json(output_dir / "final_schema.json", final_schema)
    (output_dir / "schema_design_report.md").write_text(report, encoding="utf-8")
    write_json(output_dir / "schema_package_manifest.json", manifest)
