"""Build Taxonomy Agent prompt payloads and merge observations."""

from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
from typing import Any

from .sampler import SampledImage
from .taxonomy_auditor import BatchObservation, EvidencePack


PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


def _read_prompt(name: str, prompt_dir: Path | None = None) -> str:
    return ((prompt_dir or PROMPT_DIR) / name).read_text(encoding="utf-8")


def build_observation_prompt(
    *,
    batch_id: str,
    images: list[SampledImage],
    prompt_dir: Path | None = None,
) -> dict[str, Any]:
    system_prompt = _read_prompt("taxonomy_observation_system.txt", prompt_dir)
    template = _read_prompt("taxonomy_observation_user_template.txt", prompt_dir)
    images_json = json.dumps([image.to_json() for image in images], ensure_ascii=False, indent=2)
    return {
        "batch_id": batch_id,
        "stage": "observation",
        "system_prompt": system_prompt,
        "user_prompt": template.format(batch_id=batch_id, image_count=len(images), images_json=images_json),
        "template_version": "ipa.taxonomy.observation.prompt.v1",
        "metadata": {
            "image_ids": [image.image_id for image in images],
            "images": [
                {
                    "image_id": image.image_id,
                    "image_path": image.resolved_path,
                    "image_exists": image.exists,
                }
                for image in images
            ],
        },
    }


def build_merge_prompt(
    *,
    evidence_pack: EvidencePack,
    prompt_dir: Path | None = None,
) -> dict[str, Any]:
    system_prompt = _read_prompt("taxonomy_merge_system.txt", prompt_dir)
    template = _read_prompt("taxonomy_merge_user_template.txt", prompt_dir)
    evidence_json = json.dumps(asdict(evidence_pack), ensure_ascii=False, indent=2)
    return {
        "batch_id": "merge",
        "stage": "merge",
        "system_prompt": system_prompt,
        "user_prompt": template.format(evidence_json=evidence_json),
        "template_version": "ipa.taxonomy.merge.prompt.v1",
        "metadata": {},
    }


def _unique_extend(target: list[str], values: list[str], limit: int | None = None) -> None:
    for value in values:
        if value and value not in target:
            target.append(value)
        if limit is not None and len(target) >= limit:
            return


def build_evidence_pack(observations: list[BatchObservation]) -> EvidencePack:
    grouped: dict[str, dict[str, Any]] = {}
    low_value_patterns: list[str] = []
    uncertain_patterns: list[str] = []
    conflict_notes: list[str] = []

    for observation in observations:
        _unique_extend(low_value_patterns, observation.low_value_patterns)
        _unique_extend(uncertain_patterns, observation.uncertain_patterns)
        for group in observation.observed_groups:
            item = grouped.setdefault(
                group.provisional_name,
                {
                    "candidate_phrase": group.provisional_name,
                    "seen_in_batches": [],
                    "visual_features": [],
                    "example_image_ids": [],
                    "kg_value_hints": [],
                    "boundary_notes": [],
                },
            )
            _unique_extend(item["seen_in_batches"], [observation.batch_id])
            _unique_extend(item["visual_features"], [group.visual_features])
            _unique_extend(item["example_image_ids"], group.example_image_ids, limit=10)
            _unique_extend(item["kg_value_hints"], [group.kg_value_hint])
            _unique_extend(item["boundary_notes"], [group.boundary_notes])

    for item in grouped.values():
        if len(set(item["kg_value_hints"])) > 1:
            conflict_notes.append(
                f"kg_value_hint conflict for {item['candidate_phrase']}: {', '.join(item['kg_value_hints'])}"
            )

    group_evidence = sorted(grouped.values(), key=lambda item: (-len(item["seen_in_batches"]), item["candidate_phrase"]))
    return EvidencePack(
        schema_version="ipa.taxonomy.evidence_pack.v1",
        source_batches=[observation.batch_id for observation in observations],
        total_images_observed=sum(observation.image_count for observation in observations),
        group_evidence=group_evidence,
        low_value_patterns=low_value_patterns,
        uncertain_patterns=uncertain_patterns,
        conflict_notes=conflict_notes,
    )
