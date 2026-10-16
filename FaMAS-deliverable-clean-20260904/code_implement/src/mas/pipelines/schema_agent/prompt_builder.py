"""Prompt assembly for Schema Agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .sampler import SampleUnit


PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
NON_BINDING_SCHEMA_STANDARD_FILES = {
    "kg_schema_label_property_v2.json",
    "kg_schema_label_property_v2_note.md",
}


def _read_prompt(name: str, prompt_dir: Path | None = None) -> str:
    return ((prompt_dir or PROMPT_DIR) / name).read_text(encoding="utf-8")


def load_text_file(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def load_json_file(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON file must contain an object: {path}")
    return data


def load_standards(standards_dir: Path) -> list[dict[str, str]]:
    directory = Path(standards_dir)
    if not directory.exists():
        return []
    standards: list[dict[str, str]] = []
    for path in sorted(directory.iterdir(), key=lambda item: item.name):
        if path.name in NON_BINDING_SCHEMA_STANDARD_FILES:
            continue
        if path.is_file() and path.suffix.lower() in {".md", ".txt", ".json"}:
            standards.append({"file": path.name, "path": str(path.resolve()), "content": path.read_text(encoding="utf-8")})
    return standards


def _standards_block(standards: list[dict[str, str]]) -> str:
    if not standards:
        return "No shared standards files were provided."
    parts = ["SHARED STANDARDS"]
    for standard in standards:
        parts.append(f"## {standard['file']}\n{standard['content']}")
    return "\n\n".join(parts)


def build_observation_prompt(
    *,
    round_id: str,
    sample_units: list[SampleUnit],
    human_rules: str,
    base_schema: dict[str, Any],
    standards: list[dict[str, str]],
    prompt_dir: Path | None = None,
) -> dict[str, Any]:
    system_prompt = _read_prompt("schema_observation_system.txt", prompt_dir)
    template = _read_prompt("schema_observation_user_template.txt", prompt_dir)
    sample_json = json.dumps([sample.to_json() for sample in sample_units], ensure_ascii=False, indent=2)
    base_schema_json = json.dumps(base_schema, ensure_ascii=False, indent=2)
    return {
        "stage": "observation",
        "round_id": round_id,
        "system_prompt": system_prompt,
        "user_prompt": template.format(
            round_id=round_id,
            human_rules=human_rules,
            base_schema_json=base_schema_json,
            standards_block=_standards_block(standards),
            sample_units_json=sample_json,
        ),
        "template_version": "kg.schema.observation.prompt.v1",
        "metadata": {
            "sample_ids": [sample.sample_id for sample in sample_units],
            "standards_files": [standard["file"] for standard in standards],
        },
    }


def build_merge_prompt(
    *,
    observations: list[dict[str, Any]],
    human_rules: str,
    base_schema: dict[str, Any],
    standards: list[dict[str, str]],
    prompt_dir: Path | None = None,
) -> dict[str, Any]:
    system_prompt = _read_prompt("schema_merge_system.txt", prompt_dir)
    template = _read_prompt("schema_merge_user_template.txt", prompt_dir)
    return {
        "stage": "merge",
        "round_id": "merge",
        "system_prompt": system_prompt,
        "user_prompt": template.format(
            human_rules=human_rules,
            base_schema_json=json.dumps(base_schema, ensure_ascii=False, indent=2),
            standards_block=_standards_block(standards),
            observations_json=json.dumps(observations, ensure_ascii=False, indent=2),
        ),
        "template_version": "kg.schema.merge.prompt.v1",
        "metadata": {
            "observation_rounds": [str(item.get("round_id", "")) for item in observations],
            "standards_files": [standard["file"] for standard in standards],
        },
    }
