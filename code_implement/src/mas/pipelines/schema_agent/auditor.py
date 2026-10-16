"""Validate and merge Schema Agent v2 label/property outputs."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from mas.pipelines.common.json_recovery import extract_json_object


OBSERVATION_SCHEMA_VERSION = "kg.schema.observation.v2"
MERGE_SCHEMA_VERSION = "kg.schema.merge.v2"
FINAL_SCHEMA_VERSION = "kg.schema.label_property.v2"
ALLOWED_ROLES = {"node_label", "edge_label", "node_property", "edge_property", "evidence_property", "reject"}
PROPERTY_LIKE_CANDIDATES = {"rule_or_formula", "method_step", "quantity_relationship", "math_tool", "evidence"}
ABSENT_TEXT_MARKERS = {"", "none", "n/a", "na", "null"}


@dataclass
class ObservationAuditResult:
    status: str
    observation: dict[str, Any] | None
    warnings: list[str]
    dropped_candidates: list[dict[str, Any]]
    error: str


def strict_json_loads(raw_response: str, label: str) -> dict[str, Any]:
    try:
        return extract_json_object(raw_response)
    except ValueError as exc:
        raise ValueError(f"{label} response must be strict JSON without surrounding text") from exc


def _string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be a list")
    return [str(item) for item in value]


def _property_names(properties: Any) -> set[str]:
    if not isinstance(properties, list):
        return set()
    return {str(item.get("name", "")) for item in properties if isinstance(item, dict)}


def _nullable_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if text.lower() in ABSENT_TEXT_MARKERS:
        return None
    return text


def _valid_property(item: Any) -> tuple[bool, str]:
    if not isinstance(item, dict):
        return False, "property must be an object"
    for field in ["name", "value_type", "required"]:
        if field not in item:
            return False, f"property missing {field}"
    if not str(item.get("name", "")).strip():
        return False, "property name is required"
    if not str(item.get("value_type", "")).strip():
        return False, "property value_type is required"
    if not isinstance(item.get("required"), bool):
        return False, "property required must be boolean"
    return True, ""


def _clean_properties(value: Any, owner: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(value, list):
        return [], [{"field": owner, "reason": "properties must be a list", "candidate": value}]
    usable: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        valid, reason = _valid_property(item)
        name = str(item.get("name", "")) if isinstance(item, dict) else ""
        if not valid:
            dropped.append({"field": owner, "id": name, "reason": reason, "candidate": item})
            continue
        if name in seen:
            dropped.append({"field": owner, "id": name, "reason": "duplicate property", "candidate": item})
            continue
        usable.append({"name": name, "value_type": str(item["value_type"]), "required": bool(item["required"])})
        seen.add(name)
    return usable, dropped


def _valid_role_decision(item: Any) -> tuple[bool, str]:
    if not isinstance(item, dict):
        return False, "role decision must be an object"
    for field in ["candidate", "role"]:
        if field not in item:
            return False, f"role decision missing {field}"
    candidate = _nullable_text(item.get("candidate")) or ""
    role = _nullable_text(item.get("role")) or ""
    if not candidate:
        return False, "role decision candidate is required"
    if role not in ALLOWED_ROLES:
        return False, f"invalid role: {role}"
    if role == "node_property" and (
        not _nullable_text(item.get("owner_label")) or not _nullable_text(item.get("property_name"))
    ):
        return False, "node_property requires owner_label and property_name"
    if role == "edge_property" and (
        not _nullable_text(item.get("owner_edge_label")) or not _nullable_text(item.get("property_name"))
    ):
        return False, "edge_property requires owner_edge_label and property_name"
    if role == "node_label" and candidate in PROPERTY_LIKE_CANDIDATES and not _nullable_text(item.get("promotion_reason")):
        return False, f"property-like candidate {candidate} requires promotion_reason for node_label"
    if role == "edge_label" and not str(item.get("promotion_reason", "")).strip():
        # Edge labels need source/target validation in edge_label_candidates; a reason is still enough here.
        pass
    return True, ""


def _clean_role_decisions(value: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(value, list):
        return [], [{"field": "ontology_role_decisions", "reason": "must be a list", "candidate": value}]
    usable: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for item in value:
        valid, reason = _valid_role_decision(item)
        candidate = str(item.get("candidate", "")) if isinstance(item, dict) else ""
        if not valid:
            dropped.append({"field": "ontology_role_decisions", "id": candidate, "reason": reason, "candidate": item})
            continue
        usable.append(
            {
                "candidate": _nullable_text(item.get("candidate")) or "",
                "role": _nullable_text(item.get("role")) or "",
                "owner_label": _nullable_text(item.get("owner_label")) or ("KnowledgePoint" if _nullable_text(item.get("role")) == "node_label" else None),
                "owner_edge_label": _nullable_text(item.get("owner_edge_label")),
                "property_name": _nullable_text(item.get("property_name")),
                "reason": _nullable_text(item.get("reason")) or "",
                "promotion_reason": _nullable_text(item.get("promotion_reason")),
            }
        )
    return usable, dropped


def _valid_node_label(item: Any) -> tuple[bool, str]:
    if not isinstance(item, dict):
        return False, "node label must be an object"
    for field in ["label_id", "label_zh", "description", "identity_rule", "properties"]:
        if field not in item:
            return False, f"node label missing {field}"
    if not str(item.get("label_id", "")).strip():
        return False, "node label label_id is required"
    props, dropped = _clean_properties(item.get("properties"), f"node_label:{item.get('label_id', '')}")
    if dropped:
        return False, dropped[0]["reason"]
    names = _property_names(props)
    if "evidence" not in names or "confidence" not in names:
        return False, "node label requires evidence and confidence properties"
    return True, ""


def _clean_node_labels(value: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(value, list):
        return [], [{"field": "node_label_candidates", "reason": "must be a list", "candidate": value}]
    usable: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for item in value:
        valid, reason = _valid_node_label(item)
        label_id = str(item.get("label_id", "")) if isinstance(item, dict) else ""
        if not valid:
            dropped.append({"field": "node_label_candidates", "id": label_id, "reason": reason, "candidate": item})
            continue
        props, _ = _clean_properties(item["properties"], f"node_label:{label_id}")
        usable.append(
            {
                "label_id": label_id,
                "label_zh": str(item["label_zh"]),
                "description": str(item["description"]),
                "identity_rule": str(item["identity_rule"]),
                "properties": props,
                "positive_examples": [str(value) for value in item.get("positive_examples", [])]
                if isinstance(item.get("positive_examples"), list)
                else [],
                "negative_examples": [str(value) for value in item.get("negative_examples", [])]
                if isinstance(item.get("negative_examples"), list)
                else [],
            }
        )
    return usable, dropped


def _valid_edge_label(item: Any) -> tuple[bool, str]:
    if not isinstance(item, dict):
        return False, "edge label must be an object"
    for field in [
        "predicate_id",
        "label_zh",
        "source_label",
        "target_label",
        "definition",
        "properties",
    ]:
        if field not in item:
            return False, f"edge label missing {field}"
    if not str(item.get("predicate_id", "")).strip():
        return False, "edge label predicate_id is required"
    if not str(item.get("source_label", "")).strip() or not str(item.get("target_label", "")).strip():
        return False, "edge label requires source_label and target_label"
    props, dropped = _clean_properties(item.get("properties"), f"edge_label:{item.get('predicate_id', '')}")
    if dropped:
        return False, dropped[0]["reason"]
    names = _property_names(props)
    if "evidence" not in names or "confidence" not in names:
        return False, "edge label requires evidence and confidence properties"
    return True, ""


def _clean_edge_labels(value: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(value, list):
        return [], [{"field": "edge_label_candidates", "reason": "must be a list", "candidate": value}]
    usable: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for item in value:
        valid, reason = _valid_edge_label(item)
        predicate_id = str(item.get("predicate_id", "")) if isinstance(item, dict) else ""
        if not valid:
            dropped.append({"field": "edge_label_candidates", "id": predicate_id, "reason": reason, "candidate": item})
            continue
        props, _ = _clean_properties(item["properties"], f"edge_label:{predicate_id}")
        usable.append(
            {
                "predicate_id": predicate_id,
                "label_zh": str(item["label_zh"]),
                "source_label": str(item["source_label"]),
                "target_label": str(item["target_label"]),
                "definition": str(item["definition"]),
                "properties": props,
                "positive_examples": [str(value) for value in item.get("positive_examples", [])]
                if isinstance(item.get("positive_examples"), list)
                else [],
                "negative_examples": [str(value) for value in item.get("negative_examples", [])]
                if isinstance(item.get("negative_examples"), list)
                else [],
            }
        )
    return usable, dropped


def _clean_shared_property_types(value: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(value, list):
        return [], [{"field": "shared_property_type_candidates", "reason": "must be a list", "candidate": value}]
    usable: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict) or not item.get("type_id") or not isinstance(item.get("fields"), list):
            dropped.append({"field": "shared_property_type_candidates", "reason": "requires type_id and fields", "candidate": item})
            continue
        fields, field_drops = _clean_properties(item["fields"], f"shared_property_type:{item['type_id']}")
        if field_drops:
            dropped.extend(field_drops)
            continue
        usable.append({"type_id": str(item["type_id"]), "description": str(item.get("description", "")), "fields": fields})
    return usable, dropped


def audit_observation_json_with_result(
    raw_response: str,
    expected_round_id: str,
    known_sample_ids: set[str],
    tolerant: bool = True,
) -> ObservationAuditResult:
    data = strict_json_loads(raw_response, "observation")
    if data.get("schema_version") != OBSERVATION_SCHEMA_VERSION:
        raise ValueError("invalid observation schema_version")
    if data.get("round_id") != expected_round_id:
        raise ValueError("observation round_id mismatch")
    sample_ids = _string_list(data.get("sample_ids", []), "sample_ids")
    unknown_sample_ids = [sample_id for sample_id in sample_ids if sample_id not in known_sample_ids]
    if unknown_sample_ids and not tolerant:
        raise ValueError(f"unknown sample_ids: {unknown_sample_ids}")
    warnings: list[str] = []
    if unknown_sample_ids:
        sample_ids = [sample_id for sample_id in sample_ids if sample_id in known_sample_ids]
        warnings.append(f"filtered unknown sample_ids: {unknown_sample_ids}")

    role_decisions, dropped_roles = _clean_role_decisions(data.get("ontology_role_decisions"))
    if not role_decisions:
        return ObservationAuditResult(
            status="failed",
            observation=None,
            warnings=warnings,
            dropped_candidates=dropped_roles,
            error="no usable ontology_role_decisions; role decisions are required",
        )
    node_labels, dropped_nodes = _clean_node_labels(data.get("node_label_candidates", []))
    edge_labels, dropped_edges = _clean_edge_labels(data.get("edge_label_candidates", []))
    shared_types, dropped_shared = _clean_shared_property_types(data.get("shared_property_type_candidates", []))
    dropped = dropped_roles + dropped_nodes + dropped_edges + dropped_shared
    observation = {
        "schema_version": data["schema_version"],
        "round_id": expected_round_id,
        "sample_ids": sample_ids,
        "ontology_role_decisions": role_decisions,
        "node_label_candidates": node_labels,
        "edge_label_candidates": edge_labels,
        "shared_property_type_candidates": shared_types,
        "risks": _string_list(data.get("risks", []), "risks"),
        "missing_points": _string_list(data.get("missing_points", []), "missing_points"),
    }
    status = "repaired" if warnings or dropped else "passed"
    return ObservationAuditResult(
        status=status,
        observation=observation,
        warnings=warnings + ([f"dropped {len(dropped)} invalid candidates"] if dropped else []),
        dropped_candidates=dropped,
        error="",
    )


def audit_merge_json(raw_response: str) -> dict[str, Any]:
    data = strict_json_loads(raw_response, "merge")
    if data.get("schema_version") != MERGE_SCHEMA_VERSION:
        raise ValueError("invalid merge schema_version")
    extensions = data.get("schema_extensions")
    if not isinstance(extensions, dict):
        raise ValueError("merge response missing schema_extensions")
    for field in ["ontology_role_decisions", "node_labels", "edge_labels", "shared_property_types"]:
        if not isinstance(extensions.get(field, []), list):
            raise ValueError(f"schema_extensions.{field} must be a list")
    return data


def _copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _merge_properties(base_props: list[dict[str, Any]], extension_props: list[dict[str, Any]], audit: dict[str, Any], owner: str) -> list[dict[str, Any]]:
    merged = list(base_props)
    existing = {str(prop.get("name")) for prop in merged if isinstance(prop, dict)}
    for prop in extension_props:
        name = str(prop.get("name", ""))
        if name in existing:
            audit["conflicts"].append({"field": "properties", "id": name, "owner": owner, "policy": "base_property_preserved"})
            continue
        valid, reason = _valid_property(prop)
        if not valid:
            audit["dropped_extensions"].append({"field": "properties", "id": name, "owner": owner, "reason": reason})
            continue
        merged.append(prop)
        existing.add(name)
    return merged


def _merge_node_labels(base_schema: dict[str, Any], extensions: dict[str, Any], audit: dict[str, Any]) -> list[dict[str, Any]]:
    merged = _copy_json(base_schema.get("node_labels", []))
    by_id = {str(item.get("label_id")): item for item in merged if isinstance(item, dict)}
    for label in extensions.get("node_labels", []):
        label_id = str(label.get("label_id", "")) if isinstance(label, dict) else ""
        if label_id in by_id:
            props, prop_drops = _clean_properties(label.get("properties", []), f"node_label:{label_id}")
            if prop_drops:
                audit["dropped_extensions"].extend(prop_drops)
                continue
            by_id[label_id]["properties"] = _merge_properties(
                by_id[label_id].get("properties", []),
                props,
                audit,
                f"node_label:{label_id}",
            )
            audit["conflicts"].append({"field": "node_labels", "id": label_id, "policy": "base_label_preserved"})
            continue
        valid, reason = _valid_node_label(label)
        if not valid:
            audit["dropped_extensions"].append({"field": "node_labels", "id": label_id, "reason": reason})
            continue
        cleaned, _ = _clean_node_labels([label])
        item = cleaned[0]
        merged.append(item)
        by_id[label_id] = item
    return merged


def _merge_edge_labels(base_schema: dict[str, Any], extensions: dict[str, Any], audit: dict[str, Any]) -> list[dict[str, Any]]:
    merged = _copy_json(base_schema.get("edge_labels", []))
    by_id = {str(item.get("predicate_id")): item for item in merged if isinstance(item, dict)}
    for label in extensions.get("edge_labels", []):
        predicate_id = str(label.get("predicate_id", "")) if isinstance(label, dict) else ""
        if predicate_id in by_id:
            props, prop_drops = _clean_properties(label.get("properties", []), f"edge_label:{predicate_id}")
            if prop_drops:
                audit["dropped_extensions"].extend(prop_drops)
                continue
            by_id[predicate_id]["properties"] = _merge_properties(
                by_id[predicate_id].get("properties", []),
                props,
                audit,
                f"edge_label:{predicate_id}",
            )
            audit["conflicts"].append({"field": "edge_labels", "id": predicate_id, "policy": "base_predicate_preserved"})
            continue
        valid, reason = _valid_edge_label(label)
        if not valid:
            audit["dropped_extensions"].append({"field": "edge_labels", "id": predicate_id, "reason": reason})
            continue
        cleaned, _ = _clean_edge_labels([label])
        item = cleaned[0]
        merged.append(item)
        by_id[predicate_id] = item
    return merged


def _merge_shared_types(base_schema: dict[str, Any], extensions: dict[str, Any], audit: dict[str, Any]) -> list[dict[str, Any]]:
    merged = _copy_json(base_schema.get("shared_property_types", []))
    existing = {str(item.get("type_id")) for item in merged if isinstance(item, dict)}
    cleaned, dropped = _clean_shared_property_types(extensions.get("shared_property_types", []))
    audit["dropped_extensions"].extend(dropped)
    for item in cleaned:
        if item["type_id"] in existing:
            audit["possible_duplicates"].append({"field": "shared_property_types", "id": item["type_id"]})
            continue
        merged.append(item)
        existing.add(item["type_id"])
    return merged


def merge_base_and_extensions(base_schema: dict[str, Any], extensions: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    final_schema = _copy_json(base_schema)
    final_schema["schema_version"] = FINAL_SCHEMA_VERSION
    audit: dict[str, Any] = {"conflicts": [], "dropped_extensions": [], "possible_duplicates": []}
    role_decisions, dropped_roles = _clean_role_decisions(extensions.get("ontology_role_decisions", []))
    audit["dropped_extensions"].extend(dropped_roles)
    final_schema["ontology_role_decisions"] = _copy_json(base_schema.get("ontology_role_decisions", [])) + role_decisions
    final_schema["node_labels"] = _merge_node_labels(base_schema, extensions, audit)
    final_schema["edge_labels"] = _merge_edge_labels(base_schema, extensions, audit)
    final_schema["shared_property_types"] = _merge_shared_types(base_schema, extensions, audit)
    base_node_count = len(base_schema.get("node_labels", []))
    base_edge_count = len(base_schema.get("edge_labels", []))
    base_prop_count = sum(len(item.get("properties", [])) for item in base_schema.get("node_labels", []) if isinstance(item, dict))
    final_prop_count = sum(len(item.get("properties", [])) for item in final_schema.get("node_labels", []) if isinstance(item, dict))
    final_schema["schema_extensions"] = {
        "node_label_count": max(0, len(final_schema["node_labels"]) - base_node_count),
        "edge_label_count": max(0, len(final_schema["edge_labels"]) - base_edge_count),
        "property_count": max(0, final_prop_count - base_prop_count),
    }
    final_schema["audit_summary"] = audit
    return final_schema, audit
