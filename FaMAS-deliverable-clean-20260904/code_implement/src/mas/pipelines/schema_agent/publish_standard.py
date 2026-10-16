"""Publish clean Schema Agent final schemas into the shared standards pool."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from mas.pipelines.common.standards_registry import write_standard_slot


SCHEMA_STANDARD_JSON = "kg_schema_label_property_v2.json"
SCHEMA_STANDARD_NOTE = "kg_schema_label_property_v2_note.md"
EXPECTED_SCHEMA_VERSION = "kg.schema.label_property.v2"
ALLOWED_TOP_LEVEL_KEYS = {
    "schema_version",
    "textbook_profile",
    "node_labels",
    "edge_labels",
    "shared_property_types",
    "evidence_policy",
    "confidence_policy",
    "extraction_boundaries",
}
REQUIRED_TOP_LEVEL_KEYS = {
    "schema_version",
    "node_labels",
    "edge_labels",
    "shared_property_types",
    "evidence_policy",
    "confidence_policy",
    "extraction_boundaries",
}
FORBIDDEN_TOP_LEVEL_KEYS = {
    "ontology_role_decisions",
    "source_inputs",
    "audit_summary",
    "experiment_guidance",
    "adaptive_quality_guidance",
    "schema_extensions",
    "human_rules_summary",
}
ABSENT_MARKER_STRINGS = {"none", "n/a"}


class PublishValidationError(ValueError):
    """Raised when a final schema is not safe to publish as a shared standard."""


def _load_json(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PublishValidationError(f"JSON file must contain an object: {path}")
    return data


def _find_absent_marker(value: Any, path: str = "$") -> tuple[str, str] | None:
    if isinstance(value, str):
        if value.strip().lower() in ABSENT_MARKER_STRINGS:
            return path, value
        return None
    if isinstance(value, list):
        for index, item in enumerate(value):
            found = _find_absent_marker(item, f"{path}[{index}]")
            if found is not None:
                return found
        return None
    if isinstance(value, dict):
        for key, item in value.items():
            found = _find_absent_marker(item, f"{path}.{key}")
            if found is not None:
                return found
    return None


def validate_publishable_schema(final_schema: dict[str, Any], manifest: dict[str, Any]) -> None:
    if manifest.get("mock") is True:
        raise PublishValidationError("mock Schema Agent runs cannot be published to standards")
    if final_schema.get("schema_version") != EXPECTED_SCHEMA_VERSION:
        raise PublishValidationError(f"schema_version must be {EXPECTED_SCHEMA_VERSION}")
    extra_keys = sorted(set(final_schema) - ALLOWED_TOP_LEVEL_KEYS)
    if extra_keys:
        raise PublishValidationError(f"final schema contains non-contract top-level keys: {', '.join(extra_keys)}")
    forbidden = sorted(FORBIDDEN_TOP_LEVEL_KEYS.intersection(final_schema))
    if forbidden:
        raise PublishValidationError(f"final schema contains forbidden process fields: {', '.join(forbidden)}")
    missing = sorted(REQUIRED_TOP_LEVEL_KEYS - set(final_schema))
    if missing:
        raise PublishValidationError(f"final schema missing required top-level keys: {', '.join(missing)}")
    for field in ["node_labels", "edge_labels", "shared_property_types"]:
        if not isinstance(final_schema.get(field), list) or not final_schema[field]:
            raise PublishValidationError(f"{field} must be a non-empty list")
    marker = _find_absent_marker(final_schema)
    if marker is not None:
        path, value = marker
        raise PublishValidationError(f"final schema contains string absent marker {value!r} at {path}")


def _label_ids(items: Any, key: str) -> list[str]:
    if not isinstance(items, list):
        return []
    return [str(item.get(key, "")) for item in items if isinstance(item, dict) and item.get(key)]


def render_schema_standard_note(final_schema: dict[str, Any], manifest: dict[str, Any]) -> str:
    node_labels = _label_ids(final_schema.get("node_labels"), "label_id")
    edge_labels = _label_ids(final_schema.get("edge_labels"), "predicate_id")
    shared_types = _label_ids(final_schema.get("shared_property_types"), "type_id")
    boundaries = final_schema.get("extraction_boundaries", [])
    boundary_text = "\n".join(f"- {item}" for item in boundaries) if isinstance(boundaries, list) else "- N/A"
    return f"""# KG Schema Label/Property v2 Standard

## 标准来源

- 来源 run：`{manifest.get('run_id', '')}`
- schema_version：`{final_schema.get('schema_version', '')}`
- schema_contract：`{manifest.get('schema_contract', '')}`
- model：`{manifest.get('model', '')}`
- mock：`{manifest.get('mock', '')}`

## 机器可读文件

同目录下的 `{SCHEMA_STANDARD_JSON}` 是正式 KG schema contract。后续 Node Extraction 和 Edge Extraction 必须以该 JSON 为准。

## Node Labels

{chr(10).join(f"- `{item}`" for item in node_labels)}

## Edge Labels

{chr(10).join(f"- `{item}`" for item in edge_labels)}

## Shared Property Types

{chr(10).join(f"- `{item}`" for item in shared_types)}

## Evidence And Confidence Policy

- evidence policy 来自 JSON 的 `evidence_policy`。
- confidence policy 来自 JSON 的 `confidence_policy`。
- IPA note 仍按 `ipa_enhanced_markdown_note_v1.md` 处理：IPA note 是 metadata/evidence，不是教材正文。

## Extraction Boundaries

{boundary_text}

## 使用规则

- Node Extraction 只能创建 `node_labels` 中定义的节点标签。
- Edge Extraction 只能创建 `edge_labels` 中定义的谓词边。
- `shared_property_types` 是属性值结构模板，不是 node label。
- `ontology_role_decisions`、audit、source_inputs、experiment guidance 都不是 final schema contract，不应进入下游抽取 prompt 的 schema 主体。
"""


def publish_schema_standard(output_dir: Path, standards_dir: Path) -> dict[str, Any]:
    output_dir = Path(output_dir)
    standards_dir = Path(standards_dir)
    final_schema = _load_json(output_dir / "final_schema.json")
    manifest = _load_json(output_dir / "schema_package_manifest.json")
    validate_publishable_schema(final_schema, manifest)
    slot_result = write_standard_slot(
        "schema_agent",
        {
            SCHEMA_STANDARD_JSON: json.dumps(final_schema, ensure_ascii=False, indent=2),
            SCHEMA_STANDARD_NOTE: render_schema_standard_note(final_schema, manifest),
        },
        standards_dir,
    )
    schema_path = Path(slot_result["files"][SCHEMA_STANDARD_JSON])
    note_path = Path(slot_result["files"][SCHEMA_STANDARD_NOTE])
    return {
        "published": True,
        "schema_json": str(schema_path.resolve()),
        "schema_note": str(note_path.resolve()),
        "slot_id": slot_result["slot_id"],
        "owner_agent": slot_result["owner_agent"],
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish a clean Schema Agent final schema into shared standards.")
    parser.add_argument("--schema-output-dir", required=True, help="Schema Agent output run directory.")
    parser.add_argument(
        "--standards-dir",
        default=str(Path("code_implement") / "data" / "standards"),
        help="Shared standards directory.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    result = publish_schema_standard(Path(args.schema_output_dir), Path(args.standards_dir))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
