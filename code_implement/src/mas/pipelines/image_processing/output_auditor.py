"""Audit IPA model outputs before downstream use."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from mas.pipelines.common.json_recovery import extract_json_object

from .prompt_builder import ImageTaxonomy


VALID_KG_VALUES = {"high", "medium", "low", "uncertain"}


@dataclass
class ImageTag:
    image_id: str
    image_type_id: str
    kg_value: str
    can_textualize: bool
    confidence: float
    reason: str
    needs_round2: bool
    can_describe: bool = False
    audit_status: str = "passed"
    error: str = ""

    @property
    def is_valuable(self) -> bool:
        return self.kg_value in {"high", "medium"} and self.audit_status == "passed"


@dataclass
class TextualizationResult:
    image_id: str
    can_textualize: bool
    markdown_text: str
    short_name: str
    short_description: str
    uncertainty: str
    audit_status: str = "passed"
    error: str = ""
    processing_status: str = "accepted"
    skip_reason: str = ""
    degraded_reason: str = ""
    fallback_reason: str = ""


@dataclass
class VerificationResult:
    image_id: str
    verdict: str
    issues: list[dict[str, Any]]
    revision_hint: str
    audit_status: str = "passed"
    error: str = ""


def _strict_json_loads(raw_response: str) -> dict[str, Any]:
    try:
        return extract_json_object(raw_response)
    except ValueError as exc:
        raise ValueError("round1 response must be strict JSON without surrounding text") from exc


def audit_round1_json(raw_response: str, expected_image_ids: list[str], taxonomy: ImageTaxonomy) -> list[ImageTag]:
    data = _strict_json_loads(raw_response)
    images = data.get("images")
    if not isinstance(images, list):
        raise ValueError("round1 response missing images array")

    def _failed_tag(image_id: str, error: str) -> ImageTag:
        return ImageTag(
            image_id=image_id,
            image_type_id="unknown_or_unreadable",
            kg_value="uncertain",
            can_textualize=False,
            confidence=0.0,
            reason="round1 audit downgraded this image",
            needs_round2=False,
            audit_status="failed",
            error=error,
        )

    items_by_id: dict[str, dict[str, Any]] = {}
    seen_extra_ids: list[str] = []
    invalid_id_items = 0
    expected_set = set(expected_image_ids)
    for item in images:
        if not isinstance(item, dict):
            invalid_id_items += 1
            continue
        image_id = str(item.get("image_id", ""))
        if not image_id:
            invalid_id_items += 1
            continue
        if image_id not in expected_set:
            seen_extra_ids.append(image_id)
            continue
        items_by_id.setdefault(image_id, item)

    tags: list[ImageTag] = []
    for expected_id in expected_image_ids:
        item = items_by_id.get(expected_id)
        if item is None:
            tags.append(_failed_tag(expected_id, "round1 missing from model response"))
            continue
        try:
            image_type_id = str(item.get("image_type_id", ""))
            if image_type_id not in taxonomy.type_ids:
                raise ValueError(f"unknown image_type_id: {image_type_id}")
            kg_value = str(item.get("kg_value", ""))
            if kg_value not in VALID_KG_VALUES:
                raise ValueError(f"invalid kg_value: {kg_value}")
            if image_type_id == "unknown_or_unreadable":
                kg_value = "uncertain"
            if not isinstance(item.get("can_textualize"), bool):
                raise ValueError("can_textualize must be boolean")
            confidence = float(item.get("confidence", 0.0))
            if confidence < 0 or confidence > 1:
                raise ValueError("confidence must be between 0 and 1")
            can_textualize = bool(item["can_textualize"])
            needs_round2 = bool(item.get("needs_round2", kg_value in {"high", "medium"}))
            can_describe = False
            if image_type_id == "unknown_or_unreadable":
                needs_round2 = False
                can_textualize = False
            elif kg_value in {"low", "uncertain"}:
                needs_round2 = True
                can_textualize = False
                can_describe = True
            elif not can_textualize:
                can_describe = True
            tag = ImageTag(
                image_id=expected_id,
                image_type_id=image_type_id,
                kg_value=kg_value,
                can_textualize=can_textualize,
                confidence=confidence,
                reason=str(item.get("reason", "")),
                needs_round2=needs_round2,
                can_describe=can_describe,
            )
            audit_notes = []
            if seen_extra_ids:
                audit_notes.append(f"ignored extra image_ids: {', '.join(seen_extra_ids[:5])}")
            if invalid_id_items:
                audit_notes.append(f"ignored invalid image items: {invalid_id_items}")
            if audit_notes:
                tag.error = "; ".join(audit_notes)
            tags.append(tag)
        except (TypeError, ValueError) as exc:
            tags.append(_failed_tag(expected_id, str(exc)))
    return tags


def audit_round2_json(raw_response: str, image_id: str, *, can_textualize: bool) -> TextualizationResult:
    data = _strict_json_loads(raw_response)
    markdown_text = str(data.get("markdown_text", ""))
    short_name = str(data.get("short_name", ""))
    short_description = str(data.get("short_description", ""))
    if can_textualize and not markdown_text.strip():
        if short_name.strip() and short_description.strip():
            return TextualizationResult(
                image_id=image_id,
                can_textualize=False,
                markdown_text="",
                short_name=short_name,
                short_description=short_description,
                uncertainty=str(data.get("uncertainty", "")),
                processing_status="accepted",
            )
        raise ValueError("textualized round2 response missing markdown_text")
    if not can_textualize and (not short_name.strip() or not short_description.strip()):
        raise ValueError("non-textual round2 response missing short_name or short_description")
    return TextualizationResult(
        image_id=image_id,
        can_textualize=can_textualize,
        markdown_text=markdown_text,
        short_name=short_name,
        short_description=short_description,
        uncertainty=str(data.get("uncertainty", "")),
        processing_status="accepted",
    )


def audit_verify_json(raw_response: str, image_id: str) -> VerificationResult:
    data = _strict_json_loads(raw_response)
    verdict = str(data.get("verdict", ""))
    if verdict not in {"accept", "revise"}:
        raise ValueError(f"invalid verification verdict: {verdict}")
    issues = data.get("issues")
    if not isinstance(issues, list):
        raise ValueError("verification response missing issues array")
    normalized_issues: list[dict[str, Any]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            raise ValueError("verification issue must be an object")
        aspect = str(issue.get("aspect", ""))
        if aspect not in {"fabrication", "context_leak", "incompleteness", "wrong_structure"}:
            raise ValueError(f"invalid verification issue aspect: {aspect}")
        normalized_issues.append(
            {
                "aspect": aspect,
                "detail": str(issue.get("detail", ""))[:120],
                "evidence_in_image": str(issue.get("evidence_in_image", ""))[:120],
            }
        )
    if verdict == "accept" and normalized_issues:
        raise ValueError("accept verification must not include issues")
    if verdict == "revise" and not normalized_issues:
        raise ValueError("revise verification must include at least one issue")
    return VerificationResult(
        image_id=image_id,
        verdict=verdict,
        issues=normalized_issues,
        revision_hint=str(data.get("revision_hint", ""))[:180],
    )


def distill_verification_feedback(result: VerificationResult) -> str:
    parts = []
    for issue in result.issues:
        parts.append(
            f"{issue.get('aspect', '')}: {issue.get('detail', '')}; 图中依据: {issue.get('evidence_in_image', '')}"
        )
    if result.revision_hint.strip():
        parts.append(f"修订方向: {result.revision_hint.strip()}")
    if not parts:
        return ""
    return "核实方蒸馏意见（只按图中可见内容修订，不复制原始核实响应）：" + "；".join(parts)
