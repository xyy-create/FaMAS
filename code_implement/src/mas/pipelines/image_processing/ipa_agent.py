"""Mock and real model entry points for IPA."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from mas.pipelines.common.qwen_vl_provider import QwenVLImage, QwenVLProviderError, call_qwen_vl

from .output_auditor import ImageTag
from .prompt_builder import ImageTaxonomy, PromptPackage


class ModelNotConfiguredError(RuntimeError):
    """Raised when real model mode is requested before provider setup."""


@dataclass
class IPAResponse:
    batch_id: str
    round_name: str
    raw_response: str
    mock: bool
    status: str
    error: str = ""


def mock_round1_response(image_ids: list[str], taxonomy: ImageTaxonomy) -> str:
    if "math_expression_fragment" in taxonomy.type_ids:
        fallback_type = "math_expression_fragment"
    elif taxonomy.items:
        fallback_type = taxonomy.items[0].id
    else:
        fallback_type = "unknown_or_unreadable"

    images = []
    for image_id in image_ids:
        images.append(
            {
                "image_id": image_id,
                "image_type_id": fallback_type,
                "kg_value": "medium",
                "can_textualize": True,
                "confidence": 0.65,
                "reason": "mock classification uses the fixed IPA taxonomy",
                "needs_round2": True,
            }
        )
    return json.dumps({"schema_version": "ipa.round1.v1", "images": images}, ensure_ascii=False)


def mock_round2_response(image_id: str, can_textualize: bool = True) -> str:
    if can_textualize:
        payload = {
            "markdown_text": "Mock IPA textualization: image content requires real model review.",
            "uncertainty": "mock output",
        }
    else:
        payload = {
            "short_name": "Mock image",
            "short_description": "需真实模型复核的图片",
            "uncertainty": "mock output",
        }
    return json.dumps(payload, ensure_ascii=False)


def mock_verify_response(image_id: str, round_index: int) -> str:
    if round_index >= 2:
        payload = {"verdict": "accept", "issues": [], "revision_hint": ""}
    else:
        payload = {
            "verdict": "revise",
            "issues": [
                {
                    "aspect": "incompleteness",
                    "detail": "mock要求二轮复核",
                    "evidence_in_image": image_id,
                }
            ],
            "revision_hint": "仅保留图中确有内容并简化表述",
        }
    return json.dumps(payload, ensure_ascii=False)


def _images_from_prompt(prompt: PromptPackage) -> list[QwenVLImage]:
    images = prompt.metadata.get("images", [])
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


def _call_real(prompt: PromptPackage, model_config: dict[str, Any] | None) -> str:
    images = _images_from_prompt(prompt)
    image_anchors = {
        image.image_id: f"下面这张图对应 image_id={image.image_id}，请只描述这张图本身的可见内容。"
        for image in images
    }
    try:
        return call_qwen_vl(
            system_prompt=prompt.system_prompt,
            user_prompt=prompt.user_prompt,
            images=images,
            config=model_config,
            image_anchors=image_anchors,
        )
    except QwenVLProviderError as exc:
        raise ModelNotConfiguredError(str(exc)) from exc


def process_batch(
    prompt: PromptPackage,
    image_ids: list[str],
    taxonomy: ImageTaxonomy,
    *,
    mock: bool,
    model_config: dict[str, Any] | None = None,
) -> IPAResponse:
    if not mock:
        return IPAResponse(
            batch_id=prompt.batch_id,
            round_name=prompt.round_name,
            raw_response=_call_real(prompt, model_config),
            mock=False,
            status="ok",
        )
    return IPAResponse(
        batch_id=prompt.batch_id,
        round_name=prompt.round_name,
        raw_response=mock_round1_response(image_ids, taxonomy),
        mock=True,
        status="ok",
    )


def process_textualization(
    prompt: PromptPackage,
    tag: ImageTag,
    *,
    mock: bool,
    model_config: dict[str, Any] | None = None,
) -> IPAResponse:
    if not mock:
        return IPAResponse(
            batch_id=prompt.batch_id,
            round_name=prompt.round_name,
            raw_response=_call_real(prompt, model_config),
            mock=False,
            status="ok",
        )
    return IPAResponse(
        batch_id=prompt.batch_id,
        round_name=prompt.round_name,
        raw_response=mock_round2_response(tag.image_id, tag.can_textualize),
        mock=True,
        status="ok",
    )


def process_verification(
    prompt: PromptPackage,
    *,
    mock: bool,
    model_config: dict[str, Any] | None = None,
) -> IPAResponse:
    if not mock:
        return IPAResponse(
            batch_id=prompt.batch_id,
            round_name=prompt.round_name,
            raw_response=_call_real(prompt, model_config),
            mock=False,
            status="ok",
        )
    return IPAResponse(
        batch_id=prompt.batch_id,
        round_name=prompt.round_name,
        raw_response=mock_verify_response(
            str(prompt.metadata.get("image_id", "")),
            int(prompt.metadata.get("round_index", 1)),
        ),
        mock=True,
        status="ok",
    )
