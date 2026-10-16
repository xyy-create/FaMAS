"""Mock and future model entry points for Image Taxonomy Agent."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from mas.pipelines.common.qwen_vl_provider import QwenVLImage, QwenVLProviderError, call_qwen_vl


class ModelNotConfiguredError(RuntimeError):
    """Raised when real model mode is requested before provider setup."""


@dataclass
class TaxonomyAgentResponse:
    batch_id: str
    stage: str
    raw_response: str
    mock: bool
    status: str
    error: str = ""


ITA_STAGE_MAX_TOKENS = 4096


def mock_observation_response(batch_id: str, image_ids: list[str]) -> str:
    examples = image_ids[: min(3, len(image_ids))]
    payload = {
        "schema_version": "ipa.taxonomy.observation.v1",
        "batch_id": batch_id,
        "image_count": len(image_ids),
        "observed_groups": [
            {
                "provisional_name": "几何图形关系图",
                "visual_features": "包含线段、角、面积分割、对称轴等数学结构",
                "kg_value_hint": "high",
                "example_image_ids": examples,
                "boundary_notes": "必须含数学关系；不要把普通装饰形状归入此类",
            },
            {
                "provisional_name": "题号或活动图标",
                "visual_features": "小型编号、箭头、栏目图标或活动提示符号",
                "kg_value_hint": "low",
                "example_image_ids": examples[:1],
                "boundary_notes": "只起导航作用时不应进入高价值 KG 图片",
            },
        ],
        "low_value_patterns": ["题号图标", "纯装饰卡通人物"],
        "uncertain_patterns": ["裁剪残缺", "过小不可读"],
        "missing_or_failed_image_ids": [],
    }
    return json.dumps(payload, ensure_ascii=False)


def mock_merge_response() -> str:
    payload = {
        "schema_version": "ipa.taxonomy.final.v1",
        "taxonomy": {
            "math_expression_fragment": "算式、公式、数学文字截图；若正文已完整表达，KG 价值通常不应高估。",
            "math_diagram_geometry": "包含几何关系、图形结构、面积、角、对称等数学信息的图片。",
            "table_or_structured_data": "表格、统计图、票据或可抽取字段的结构化数据图片。",
            "word_problem_context": "与应用题数量关系相关的现实或插画场景。",
            "decorative_character": "只起装饰或引导作用、无新增数学信息的人物或卡通图。",
            "section_marker_or_icon": "题号、栏目、活动标记、箭头等导航或版式图标。",
            "unknown_or_unreadable": "缺失、模糊、过小或上下文不足，无法可靠判断的图片。",
        },
        "default_kg_values": {
            "math_expression_fragment": "medium",
            "math_diagram_geometry": "high",
            "table_or_structured_data": "high",
            "word_problem_context": "medium",
            "decorative_character": "low",
            "section_marker_or_icon": "low",
            "unknown_or_unreadable": "uncertain",
        },
        "kg_value_rules": {
            "high": "图中含正文未完整表达的数学结构、关系、步骤或数据。",
            "medium": "对理解题目或教学活动有帮助，但未必直接形成 KG 结构。",
            "low": "装饰、引导、编号，或重复正文且无新增知识。",
            "uncertain": "缺失、裁剪残缺、上下文不足、无法可靠判断。",
        },
        "risk_notes": ["类别较保守，细粒度信息可在 IPA 文本化阶段补充。"],
    }
    return json.dumps(payload, ensure_ascii=False)


def _images_from_prompt_metadata(prompt: dict[str, Any]) -> list[QwenVLImage]:
    metadata = prompt.get("metadata") if isinstance(prompt.get("metadata"), dict) else {}
    images = metadata.get("images", [])
    if not isinstance(images, list):
        return []
    qwen_images: list[QwenVLImage] = []
    for item in images:
        if not isinstance(item, dict):
            continue
        if not item.get("image_exists", False):
            continue
        image_id = str(item.get("image_id", ""))
        image_path = str(item.get("image_path", ""))
        if image_id and image_path:
            qwen_images.append(QwenVLImage(image_id=image_id, path=Path(image_path)))
    return qwen_images


def _call_real(prompt: dict[str, Any], images: list[QwenVLImage], model_config: dict[str, Any] | None) -> str:
    config = dict(model_config or {})
    config["max_tokens"] = ITA_STAGE_MAX_TOKENS
    try:
        return call_qwen_vl(
            system_prompt=str(prompt.get("system_prompt", "")),
            user_prompt=str(prompt.get("user_prompt", "")),
            images=images,
            config=config,
        )
    except QwenVLProviderError as exc:
        raise ModelNotConfiguredError(str(exc)) from exc


def process_observation_batch(
    prompt: dict[str, Any],
    image_ids: list[str],
    *,
    mock: bool,
    model_config: dict[str, Any] | None = None,
) -> TaxonomyAgentResponse:
    if not mock:
        batch_id = str(prompt.get("batch_id", ""))
        raw_response = _call_real(prompt, _images_from_prompt_metadata(prompt), model_config)
        return TaxonomyAgentResponse(
            batch_id=batch_id,
            stage="observation",
            raw_response=raw_response,
            mock=False,
            status="ok",
        )
    batch_id = str(prompt.get("batch_id", ""))
    return TaxonomyAgentResponse(
        batch_id=batch_id,
        stage="observation",
        raw_response=mock_observation_response(batch_id, image_ids),
        mock=True,
        status="ok",
    )


def process_merge(
    prompt: dict[str, Any],
    *,
    mock: bool,
    model_config: dict[str, Any] | None = None,
) -> TaxonomyAgentResponse:
    if not mock:
        raw_response = _call_real(prompt, [], model_config)
        return TaxonomyAgentResponse(
            batch_id="merge",
            stage="merge",
            raw_response=raw_response,
            mock=False,
            status="ok",
        )
    return TaxonomyAgentResponse(
        batch_id="merge",
        stage="merge",
        raw_response=mock_merge_response(),
        mock=True,
        status="ok",
    )
