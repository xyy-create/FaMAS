"""Mock and real model entry points for Schema Agent."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from mas.pipelines.common.qwen_text_provider import QwenTextProviderError, call_qwen_text

from .sampler import SampleUnit


class ModelNotConfiguredError(RuntimeError):
    """Raised when real model mode cannot call the configured provider."""


@dataclass
class SchemaAgentResponse:
    stage: str
    round_id: str
    raw_response: str
    mock: bool
    status: str
    error: str = ""


SCHEMA_STAGE_MAX_TOKENS = 16384


def _property(name: str, value_type: str, required: bool = False) -> dict[str, Any]:
    return {"name": name, "value_type": value_type, "required": required}


def mock_observation_response(round_id: str, sample_units: list[SampleUnit]) -> str:
    payload = {
        "schema_version": "kg.schema.observation.v2",
        "round_id": round_id,
        "sample_ids": [sample.sample_id for sample in sample_units],
        "ontology_role_decisions": [
            {
                "candidate": "method_step",
                "role": "node_property",
                "owner_label": "KnowledgePoint",
                "owner_edge_label": "",
                "property_name": "methods",
                "reason": "方法步骤描述知识点或题目的内部结构，默认不独立成 node label。",
                "promotion_reason": "",
            },
            {
                "candidate": "quantity_relationship",
                "role": "node_property",
                "owner_label": "KnowledgePoint",
                "owner_edge_label": "",
                "property_name": "quantity_relationships",
                "reason": "数量关系通常是知识点内部可结构化描述。",
                "promotion_reason": "",
            },
        ],
        "node_label_candidates": [
            {
                "label_id": "Activity",
                "label_zh": "学习活动",
                "description": "教材中要求学生动手、讨论或探究的任务。",
                "identity_rule": "有明确活动指令和可追溯出处。",
                "properties": [
                    _property("name", "string", True),
                    _property("description", "string", False),
                    _property("steps", "list[MethodStep]", False),
                    _property("evidence", "list[EvidenceRef]", True),
                    _property("confidence", "float", True),
                ],
                "positive_examples": ["做卡片活动"],
                "negative_examples": ["普通计算题"],
            }
        ],
        "edge_label_candidates": [
            {
                "predicate_id": "uses_method",
                "label_zh": "使用方法",
                "source_label": "Problem",
                "target_label": "KnowledgePoint",
                "definition": "题目使用某知识点中的方法或步骤。",
                "properties": [
                    _property("relation_label", "string", False),
                    _property("rationale", "string", False),
                    _property("evidence", "list[EvidenceRef]", True),
                    _property("confidence", "float", True),
                ],
                "positive_examples": ["题目使用列表策略"],
                "negative_examples": ["同页出现但无方法关系"],
            }
        ],
        "shared_property_type_candidates": [
            {
                "type_id": "QuantityRelationship",
                "description": "知识点内部的数量关系结构。",
                "fields": [
                    _property("statement", "string", True),
                    _property("variable_definitions", "object", False),
                ],
            }
        ],
        "risks": ["mock observation only for tests"],
        "missing_points": [],
    }
    return json.dumps(payload, ensure_ascii=False)


def mock_merge_response(observations: list[dict[str, Any]], base_schema: dict[str, Any]) -> str:
    role_decisions: list[dict[str, Any]] = []
    node_labels: list[dict[str, Any]] = []
    edge_labels: list[dict[str, Any]] = []
    shared_property_types: list[dict[str, Any]] = []
    for observation in observations:
        role_decisions.extend(observation.get("ontology_role_decisions", []))
        node_labels.extend(observation.get("node_label_candidates", []))
        edge_labels.extend(observation.get("edge_label_candidates", []))
        shared_property_types.extend(observation.get("shared_property_type_candidates", []))
    payload = {
        "schema_version": "kg.schema.merge.v2",
        "schema_extensions": {
            "ontology_role_decisions": role_decisions,
            "node_labels": node_labels,
            "edge_labels": edge_labels,
            "shared_property_types": shared_property_types,
        },
        "schema_design_report": (
            "# Schema Design Report\n\n"
            "本报告由 mock Schema Agent v2 生成，用于验证 label/property contract。"
            "人工 base schema 保持最高优先级，方法、数量关系和证据默认作为属性。"
        ),
        "audit_notes": [f"base node labels: {len(base_schema.get('node_labels', []))}"],
    }
    return json.dumps(payload, ensure_ascii=False)


def _call_real(prompt: dict[str, Any], model_config: dict[str, Any] | None) -> str:
    config = dict(model_config or {})
    config.setdefault("max_tokens", SCHEMA_STAGE_MAX_TOKENS)
    try:
        return call_qwen_text(
            system_prompt=str(prompt.get("system_prompt", "")),
            user_prompt=str(prompt.get("user_prompt", "")),
            config=config,
        )
    except QwenTextProviderError as exc:
        raise ModelNotConfiguredError(str(exc)) from exc


def process_observation(
    prompt: dict[str, Any],
    sample_units: list[SampleUnit],
    *,
    mock: bool,
    model_config: dict[str, Any] | None = None,
) -> SchemaAgentResponse:
    round_id = str(prompt.get("round_id", ""))
    if mock:
        return SchemaAgentResponse(
            stage="observation",
            round_id=round_id,
            raw_response=mock_observation_response(round_id, sample_units),
            mock=True,
            status="ok",
        )
    raw_response = _call_real(prompt, model_config)
    return SchemaAgentResponse("observation", round_id, raw_response, False, "ok")


def process_merge(
    prompt: dict[str, Any],
    observations: list[dict[str, Any]],
    base_schema: dict[str, Any],
    *,
    mock: bool,
    model_config: dict[str, Any] | None = None,
) -> SchemaAgentResponse:
    if mock:
        return SchemaAgentResponse(
            stage="merge",
            round_id="merge",
            raw_response=mock_merge_response(observations, base_schema),
            mock=True,
            status="ok",
        )
    raw_response = _call_real(prompt, model_config)
    return SchemaAgentResponse("merge", "merge", raw_response, False, "ok")
