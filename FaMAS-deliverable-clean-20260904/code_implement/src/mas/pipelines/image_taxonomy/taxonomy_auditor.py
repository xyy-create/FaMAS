"""Validate Taxonomy Agent model outputs before use."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mas.pipelines.common.json_recovery import extract_json_object


VALID_KG_VALUES = {"high", "medium", "low", "uncertain"}


@dataclass
class ObservationGroup:
    provisional_name: str
    visual_features: str
    kg_value_hint: str
    example_image_ids: list[str]
    boundary_notes: str


@dataclass
class BatchObservation:
    schema_version: str
    batch_id: str
    image_count: int
    observed_groups: list[ObservationGroup]
    low_value_patterns: list[str]
    uncertain_patterns: list[str]
    missing_or_failed_image_ids: list[str]


@dataclass
class ObservationAuditResult:
    status: str
    observation: BatchObservation | None
    warnings: list[str]
    dropped_groups: list[dict[str, Any]]
    filtered_example_image_ids: dict[str, list[str]]
    error: str


@dataclass
class EvidencePack:
    schema_version: str
    source_batches: list[str]
    total_images_observed: int
    group_evidence: list[dict[str, Any]]
    low_value_patterns: list[str]
    uncertain_patterns: list[str]
    conflict_notes: list[str]


def strict_json_loads(raw_response: str, label: str) -> dict[str, Any]:
    try:
        return extract_json_object(raw_response)
    except ValueError as exc:
        raise ValueError(f"{label} response must be strict JSON without surrounding text") from exc


def _string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return [str(item) for item in value]


def audit_observation_json(
    raw_response: str,
    expected_batch_id: str,
    expected_image_count: int,
    known_image_ids: set[str],
) -> BatchObservation:
    result = audit_observation_json_with_result(
        raw_response,
        expected_batch_id,
        expected_image_count,
        known_image_ids,
        tolerant=False,
    )
    if result.observation is None:
        raise ValueError(result.error)
    return result.observation


def audit_observation_json_with_result(
    raw_response: str,
    expected_batch_id: str,
    expected_image_count: int,
    known_image_ids: set[str],
    tolerant: bool = False,
) -> ObservationAuditResult:
    data = strict_json_loads(raw_response, "observation")
    if data.get("schema_version") != "ipa.taxonomy.observation.v1":
        raise ValueError("invalid observation schema_version")
    if data.get("batch_id") != expected_batch_id:
        raise ValueError("observation batch_id mismatch")
    image_count = int(data.get("image_count", -1))
    if image_count != expected_image_count:
        raise ValueError("observation image_count mismatch")
    groups_data = data.get("observed_groups")
    if not isinstance(groups_data, list):
        raise ValueError("observation missing observed_groups")

    groups: list[ObservationGroup] = []
    warnings: list[str] = []
    dropped_groups: list[dict[str, Any]] = []
    filtered_example_image_ids: dict[str, list[str]] = {}
    for item in groups_data:
        if not isinstance(item, dict):
            if tolerant:
                dropped_groups.append({"reason": "observed group must be an object", "group": item})
                warnings.append("dropped observed group because it was not an object")
                continue
            raise ValueError("observed group must be an object")
        kg_value_hint = str(item.get("kg_value_hint", ""))
        if kg_value_hint not in VALID_KG_VALUES:
            if tolerant:
                dropped_groups.append(
                    {
                        "reason": f"invalid kg_value_hint: {kg_value_hint}",
                        "group": {str(key): value for key, value in item.items()},
                    }
                )
                warnings.append(f"dropped observed group with invalid kg_value_hint: {kg_value_hint}")
                continue
            raise ValueError(f"invalid kg_value_hint: {kg_value_hint}")
        example_ids = _string_list(item.get("example_image_ids", []), "example_image_ids")
        unknown_ids = [image_id for image_id in example_ids if image_id not in known_image_ids]
        if unknown_ids:
            if tolerant:
                example_ids = [image_id for image_id in example_ids if image_id in known_image_ids]
                group_name = str(item.get("provisional_name", "")).strip() or "<unnamed>"
                filtered_example_image_ids[group_name] = unknown_ids
                warnings.append(f"filtered unknown example_image_ids for {group_name}: {unknown_ids}")
            else:
                raise ValueError(f"unknown example_image_ids: {unknown_ids}")
        provisional_name = str(item.get("provisional_name", "")).strip()
        visual_features = str(item.get("visual_features", "")).strip()
        if not provisional_name or not visual_features:
            if tolerant:
                dropped_groups.append(
                    {
                        "reason": "observed group requires provisional_name and visual_features",
                        "group": {str(key): value for key, value in item.items()},
                    }
                )
                warnings.append("dropped observed group missing provisional_name or visual_features")
                continue
            raise ValueError("observed group requires provisional_name and visual_features")
        groups.append(
            ObservationGroup(
                provisional_name=provisional_name,
                visual_features=visual_features,
                kg_value_hint=kg_value_hint,
                example_image_ids=example_ids,
                boundary_notes=str(item.get("boundary_notes", "")),
            )
        )

    missing = _string_list(data.get("missing_or_failed_image_ids", []), "missing_or_failed_image_ids")
    unknown_missing = [image_id for image_id in missing if image_id not in known_image_ids]
    if unknown_missing:
        if tolerant:
            missing = [image_id for image_id in missing if image_id in known_image_ids]
            warnings.append(f"filtered unknown missing_or_failed_image_ids: {unknown_missing}")
        else:
            raise ValueError(f"unknown missing_or_failed_image_ids: {unknown_missing}")
    if not groups:
        return ObservationAuditResult(
            status="failed",
            observation=None,
            warnings=warnings,
            dropped_groups=dropped_groups,
            filtered_example_image_ids=filtered_example_image_ids,
            error="no usable observed_groups",
        )
    observation = BatchObservation(
        schema_version="ipa.taxonomy.observation.v1",
        batch_id=expected_batch_id,
        image_count=image_count,
        observed_groups=groups,
        low_value_patterns=_string_list(data.get("low_value_patterns", []), "low_value_patterns"),
        uncertain_patterns=_string_list(data.get("uncertain_patterns", []), "uncertain_patterns"),
        missing_or_failed_image_ids=missing,
    )
    status = "repaired" if warnings or dropped_groups or filtered_example_image_ids else "passed"
    return ObservationAuditResult(
        status=status,
        observation=observation,
        warnings=warnings,
        dropped_groups=dropped_groups,
        filtered_example_image_ids=filtered_example_image_ids,
        error="",
    )


def _normalize_default_kg_value(value: str) -> str | None:
    tokens = [part.strip().lower() for part in str(value).split("|")] if "|" in str(value) else [str(value).strip().lower()]
    for token in tokens:
        if token in VALID_KG_VALUES:
            return token
    return None


def audit_merge_json(raw_response: str) -> dict[str, Any]:
    data = strict_json_loads(raw_response, "merge taxonomy")
    if data.get("schema_version") != "ipa.taxonomy.final.v1":
        raise ValueError("invalid merge taxonomy schema_version")
    taxonomy = data.get("taxonomy")
    kg_rules = data.get("kg_value_rules")
    default_values = data.get("default_kg_values")
    if not isinstance(taxonomy, dict) or not taxonomy:
        raise ValueError("merge taxonomy must be a non-empty object")
    if not isinstance(kg_rules, dict) or set(kg_rules) != VALID_KG_VALUES:
        raise ValueError("merge kg_value_rules must include high/medium/low/uncertain")
    if not isinstance(default_values, dict):
        raise ValueError("merge default_kg_values must be an object")
    missing_defaults = [type_id for type_id in taxonomy if type_id not in default_values]
    if missing_defaults:
        raise ValueError(f"merge missing default_kg_values for {missing_defaults}")

    risk_notes = _string_list(data.get("risk_notes", []), "risk_notes")
    items = []
    for key, label in taxonomy.items():
        category_id = str(key)
        raw_value = str(default_values.get(category_id, ""))
        normalized = _normalize_default_kg_value(raw_value)
        if normalized is None:
            normalized = "uncertain"
            risk_notes.append(f"default_kg_value 非法已降级: {category_id}={raw_value}")
        items.append(
            {
                "id": category_id,
                "label": str(label),
                "default_kg_value": normalized,
                "rule": str(label),
            }
        )
    result = {
        "version": "ipa.taxonomy.generated.v1",
        "items": items,
        "kg_value_rules": {str(key): str(value) for key, value in kg_rules.items()},
        "risk_notes": risk_notes,
    }
    audit_selected_taxonomy(result)
    return result


def audit_selected_taxonomy(data: dict[str, Any]) -> None:
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ValueError("selected taxonomy requires items")
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("selected taxonomy item must be an object")
        if not item.get("id") or not item.get("rule"):
            raise ValueError("selected taxonomy item requires id and rule")
        if item.get("default_kg_value") not in VALID_KG_VALUES:
            raise ValueError("selected taxonomy item has invalid default_kg_value")
