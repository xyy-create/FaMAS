"""Filesystem helpers for KG Extraction MAS."""

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Sequence

from .models import jsonable


CODE_ROOT = Path(__file__).resolve().parents[4]


def make_run_id(prefix: str, label: str | None = None) -> str:
    """Create a timestamped run ID.

    Args:
        prefix: Run type prefix.
        label: Optional user suffix.

    Returns:
        Timestamped run ID.
    """

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = f"_{label}" if label else ""
    return f"{prefix}_{stamp}{suffix}"


def _unique(path: Path) -> Path:
    if not path.exists():
        return path
    counter = 2
    while True:
        candidate = path.parent / f"{path.name}_{counter}"
        if not candidate.exists():
            return candidate
        counter += 1


def prepare_run_tree(run_id: str, *, work_root: Path | None = None, output_root: Path | None = None) -> dict[str, Path]:
    """Create intermediate and output directories for one run.

    Args:
        run_id: Current KG extraction run ID.
        work_root: Optional intermediate root.
        output_root: Optional final output root.

    Returns:
        Mapping of logical directory names to paths.
    """

    work_base = Path(work_root or (CODE_ROOT / "data" / "intermediate" / "kg_extraction_outputs"))
    output_base = Path(output_root or (CODE_ROOT / "data" / "output" / "kg_extraction_outputs"))
    work_dir = _unique(work_base / run_id)
    output_dir = _unique(output_base / work_dir.name)
    paths = {
        "work_dir": work_dir,
        "output_dir": output_dir,
        "node": work_dir / "node_outputs",
        "edge": work_dir / "edge_outputs",
        "validation": work_dir / "validation_outputs",
        "standard": work_dir / "standard_outputs",
        "final_standard": output_dir / "standard_outputs",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    for stage in ["node", "edge", "validation", "standard"]:
        for rel in ["inputs", "prompts", "responses", "audit"]:
            (paths[stage] / rel).mkdir(parents=True, exist_ok=True)
    return paths


def write_json(path: Path, value: Any) -> None:
    """Write JSON with UTF-8 encoding.

    Args:
        path: Output file path.
        value: JSON-serializable value.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(jsonable(value), ensure_ascii=False, indent=2), encoding="utf-8")


def write_report(path: Path, title: str, lines: Sequence[str]) -> None:
    """Write a Markdown report.

    Args:
        path: Output file path.
        title: Report title.
        lines: Markdown body lines.
    """

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("# " + title + "\n\n" + "\n".join(lines), encoding="utf-8")


def assert_no_secret_leak(
    output_paths: Sequence[Path],
    secret_values: Sequence[str],
) -> None:
    """Fail if an output file contains an API key value.

    Args:
        output_paths: Files to scan.
        secret_values: Secret strings to check. Empty strings are ignored.

    Raises:
        AssertionError: If a secret value is found.
    """

    secrets = [secret for secret in secret_values if secret]
    if not secrets:
        return
    for path in output_paths:
        p = Path(path)
        if not p.exists() or not p.is_file():
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        for secret in secrets:
            if secret in text:
                raise AssertionError(f"secret value leaked into {p}")
