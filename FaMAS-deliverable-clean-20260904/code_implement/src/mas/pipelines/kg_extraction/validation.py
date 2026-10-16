"""Validation helpers for KG Extraction MAS."""

from __future__ import annotations

import json
from pathlib import Path
import re
import unicodedata
from typing import Any, Sequence

from mas.pipelines.common.json_recovery import extract_json_object

from .models import ExtractionSectionContext, ValidationFeedback


LATEX_COMMAND_RE = re.compile(r"\\[A-Za-z]+")


def _node_label_map(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["label_id"]: item for item in schema.get("node_labels", []) if isinstance(item, dict)}


def _edge_label_map(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["predicate_id"]: item for item in schema.get("edge_labels", []) if isinstance(item, dict)}


def _required_props(label_or_edge: dict[str, Any]) -> set[str]:
    return {
        item["name"]
        for item in label_or_edge.get("properties", [])
        if isinstance(item, dict) and item.get("required") and item.get("name")
    }


def _evidence_required_fields(schema: dict[str, Any]) -> set[str]:
    for item in schema.get("shared_property_types", []):
        if item.get("type_id") == "EvidenceRef":
            return {
                field["name"]
                for field in item.get("fields", [])
                if isinstance(field, dict) and field.get("required") and field.get("name")
            }
    return {"source_path", "section", "quote_or_summary"}


def _issue(
    *,
    target_type: str,
    target_id: str,
    source_context_id: str,
    issue_type: str,
    field_path: str,
    reason: str,
    expected_fix: str,
    evidence_hint: str,
    original_item: dict[str, Any],
) -> dict[str, Any]:
    return {
        "target_type": target_type,
        "target_id": target_id,
        "source_context_id": source_context_id,
        "issue_type": issue_type,
        "field_path": field_path,
        "reason": reason,
        "expected_fix": expected_fix,
        "evidence_hint": evidence_hint,
        "original_item": original_item,
    }


def validate_nodes_hard(
    node_package: dict[str, Any],
    schema: dict[str, Any],
    contexts: Sequence[ExtractionSectionContext],
) -> list[dict[str, Any]]:
    """Validate node candidates with deterministic hard rules.

    Args:
        node_package: NEA node candidate package.
        schema: Published KG schema.
        contexts: Source contexts for evidence checks.

    Returns:
        List of issue dicts. Empty list means hard rules passed.
    """

    label_map = _node_label_map(schema)
    evidence_fields = _evidence_required_fields(schema)
    context_ids = {context.source_context_id for context in contexts}
    issues: list[dict[str, Any]] = []
    for node in node_package.get("nodes", []):
        target_id = str(node.get("node_id", ""))
        source_context_id = str(node.get("source_context_id", ""))
        label = str(node.get("label", ""))
        properties = node.get("properties", {})
        if label not in label_map:
            issues.append(
                _issue(
                    target_type="node",
                    target_id=target_id,
                    source_context_id=source_context_id,
                    issue_type="illegal_node_label",
                    field_path="label",
                    reason=f"Node label {label} is not in schema node_labels.",
                    expected_fix="Use only schema node_labels[].label_id.",
                    evidence_hint="Check kg_schema_label_property_v2.json.",
                    original_item=node,
                )
            )
        required = _required_props(label_map.get(label, {})) | {"evidence", "confidence"}
        for prop in sorted(required):
            if prop not in properties:
                issues.append(
                    _issue(
                        target_type="node",
                        target_id=target_id,
                        source_context_id=source_context_id,
                        issue_type="missing_required_property",
                        field_path=f"properties.{prop}",
                        reason=f"Required property {prop} is missing.",
                        expected_fix=f"Add schema-compatible properties.{prop}.",
                        evidence_hint="Use textbook body or eligible IPA-generated text.",
                        original_item=node,
                    )
                )
        issues.extend(_validate_common_item(node, "node", target_id, source_context_id, properties, evidence_fields, context_ids))
    return issues


def normalize_candidate_sources(
    *,
    stage: str,
    candidate_package: dict[str, Any],
    contexts: Sequence[ExtractionSectionContext],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Normalize model-emitted source fields when they uniquely match a context.

    Args:
        stage: `node` or `edge`.
        candidate_package: NEA or EEA candidate package.
        contexts: Source contexts used by the current run.

    Returns:
        Tuple of normalized package and audit entries. Ambiguous or unmatched
        source fields are left unchanged for hard-rule validation.
    """

    item_key = "nodes" if stage == "node" else "edges"
    normalized = json.loads(json.dumps(candidate_package, ensure_ascii=False))
    context_by_exact_id = {context.source_context_id: context for context in contexts}
    context_by_norm_id = _unique_context_index(contexts, lambda context: _normalize_source_key(context.source_context_id))
    context_by_norm_path = _unique_context_index(contexts, lambda context: _normalize_source_key(str(context.markdown_path)))
    context_by_norm_file = _unique_context_index(contexts, lambda context: _normalize_source_key(context.markdown_file))
    context_by_section_id = _unique_context_index(contexts, lambda context: context.section_id)
    audit: list[dict[str, Any]] = []

    for item in normalized.get(item_key, []):
        if not isinstance(item, dict):
            continue
        context = _resolve_context_for_item(
            item,
            context_by_exact_id=context_by_exact_id,
            context_by_norm_id=context_by_norm_id,
            context_by_norm_path=context_by_norm_path,
            context_by_norm_file=context_by_norm_file,
            context_by_section_id=context_by_section_id,
        )
        if context is None:
            continue
        before = _source_snapshot(item)
        _apply_context_to_item_sources(item, context)
        after = _source_snapshot(item)
        if before != after:
            audit.append(
                {
                    "stage": stage,
                    "target_id": item.get("node_id" if stage == "node" else "edge_id", ""),
                    "source_context_id_before": before["source_context_id"],
                    "source_context_id_after": after["source_context_id"],
                    "source_path_before": before["source_path"],
                    "source_path_after": after["source_path"],
                    "reason": "unique_context_match_after_unicode_or_path_normalization",
                }
            )
    return normalized, audit


def validate_edges_hard(
    edge_package: dict[str, Any],
    schema: dict[str, Any],
    node_pack: dict[str, Any],
    contexts: Sequence[ExtractionSectionContext],
) -> list[dict[str, Any]]:
    """Validate edge candidates with deterministic hard rules.

    Args:
        edge_package: EEA edge candidate package.
        schema: Published KG schema.
        node_pack: VA-approved node pack.
        contexts: Source contexts for evidence checks.

    Returns:
        List of issue dicts. Empty list means hard rules passed.
    """

    edge_map = _edge_label_map(schema)
    evidence_fields = _evidence_required_fields(schema)
    context_ids = {context.source_context_id for context in contexts}
    nodes_by_id = {node.get("node_id"): node for node in node_pack.get("nodes", [])}
    issues: list[dict[str, Any]] = []
    for edge in edge_package.get("edges", []):
        target_id = str(edge.get("edge_id", ""))
        source_context_id = str(edge.get("source_context_id", ""))
        predicate = str(edge.get("predicate", ""))
        properties = edge.get("properties", {})
        edge_schema = edge_map.get(predicate)
        if edge_schema is None:
            issues.append(
                _issue(
                    target_type="edge",
                    target_id=target_id,
                    source_context_id=source_context_id,
                    issue_type="illegal_edge_predicate",
                    field_path="predicate",
                    reason=f"Edge predicate {predicate} is not in schema edge_labels.",
                    expected_fix="Use only schema edge_labels[].predicate_id.",
                    evidence_hint="Check kg_schema_label_property_v2.json.",
                    original_item=edge,
                )
            )
        for prop in sorted(_required_props(edge_schema or {}) | {"evidence", "confidence"}):
            if prop not in properties:
                issues.append(
                    _issue(
                        target_type="edge",
                        target_id=target_id,
                        source_context_id=source_context_id,
                        issue_type="missing_required_property",
                        field_path=f"properties.{prop}",
                        reason=f"Required property {prop} is missing.",
                        expected_fix=f"Add schema-compatible properties.{prop}.",
                        evidence_hint="Use edge evidence from text or node evidence.",
                        original_item=edge,
                    )
                )
        source_node = nodes_by_id.get(edge.get("source_node_id"))
        target_node = nodes_by_id.get(edge.get("target_node_id"))
        if source_node is None or target_node is None:
            issues.append(
                _issue(
                    target_type="edge",
                    target_id=target_id,
                    source_context_id=source_context_id,
                    issue_type="edge_endpoint_missing",
                    field_path="source_node_id/target_node_id",
                    reason="Edge source or target node id is not in node_pack.",
                    expected_fix="Reference only VA-approved node ids.",
                    evidence_hint="Use node_pack nodes.",
                    original_item=edge,
                )
            )
        elif edge_schema is not None:
            if source_node.get("label") != edge_schema.get("source_label") or target_node.get("label") != edge_schema.get("target_label"):
                issues.append(
                    _issue(
                        target_type="edge",
                        target_id=target_id,
                        source_context_id=source_context_id,
                        issue_type="edge_endpoint_label_mismatch",
                        field_path="source_node_id/target_node_id",
                        reason="Edge endpoint labels do not match schema source_label/target_label.",
                        expected_fix="Use a predicate compatible with the endpoint labels or change endpoints.",
                        evidence_hint="Check schema edge_labels.",
                        original_item=edge,
                    )
                )
        issues.extend(_validate_common_item(edge, "edge", target_id, source_context_id, properties, evidence_fields, context_ids))
    return issues


def _validate_common_item(
    item: dict[str, Any],
    target_type: str,
    target_id: str,
    source_context_id: str,
    properties: dict[str, Any],
    evidence_fields: set[str],
    context_ids: set[str],
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if source_context_id not in context_ids:
        issues.append(
            _issue(
                target_type=target_type,
                target_id=target_id,
                source_context_id=source_context_id,
                issue_type="unknown_source_context",
                field_path="source_context_id",
                reason="source_context_id does not match any input context.",
                expected_fix="Use the source_context_id from ExtractionSectionContext.",
                evidence_hint="Bind enhanced Markdown to sections_index first.",
                original_item=item,
            )
        )
    evidence = properties.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        issues.append(
            _issue(
                target_type=target_type,
                target_id=target_id,
                source_context_id=source_context_id,
                issue_type="missing_evidence",
                field_path="properties.evidence",
                reason="Evidence list is missing or empty.",
                expected_fix="Add at least one EvidenceRef.",
                evidence_hint="Use textbook_body or eligible ipa_generated_text.",
                original_item=item,
            )
        )
    else:
        for index, ev in enumerate(evidence):
            if not isinstance(ev, dict):
                continue
            for field in evidence_fields:
                if field not in ev:
                    issues.append(
                        _issue(
                            target_type=target_type,
                            target_id=target_id,
                            source_context_id=source_context_id,
                            issue_type="missing_evidence_field",
                            field_path=f"properties.evidence[{index}].{field}",
                            reason=f"EvidenceRef missing required field {field}.",
                            expected_fix="Use schema-compatible EvidenceRef.",
                            evidence_hint="Preserve source path and section metadata.",
                            original_item=item,
                        )
                    )
            quote = str(ev.get("quote_or_summary", ""))
            if _readable_quote_length(quote) > 120:
                issues.append(
                    _issue(
                        target_type=target_type,
                        target_id=target_id,
                        source_context_id=source_context_id,
                        issue_type="evidence_quote_too_long",
                        field_path=f"properties.evidence[{index}].quote_or_summary",
                        reason="EvidenceRef quote_or_summary exceeds 120 characters.",
                        expected_fix="Shorten quote_or_summary to 120 characters or fewer while preserving traceable source meaning.",
                        evidence_hint="Use the shortest useful source span or a concise IPA-generated summary.",
                        original_item=item,
                    )
                )
    figures = properties.get("figures")
    if figures is not None:
        if not isinstance(figures, list):
            issues.append(
                _issue(
                    target_type=target_type,
                    target_id=target_id,
                    source_context_id=source_context_id,
                    issue_type="invalid_figures_shape",
                    field_path="properties.figures",
                    reason="figures must be a list of FigureRef objects when present.",
                    expected_fix="Use properties.figures as a list, or omit it when no figure is attached.",
                    evidence_hint="Attach images as FigureRef properties with image_path.",
                    original_item=item,
                )
            )
        else:
            for index, figure in enumerate(figures):
                if not isinstance(figure, dict) or not str(figure.get("image_path", "")).strip():
                    issues.append(
                        _issue(
                            target_type=target_type,
                            target_id=target_id,
                            source_context_id=source_context_id,
                            issue_type="figure_missing_image_path",
                            field_path=f"properties.figures[{index}]",
                            reason="FigureRef must be an object with a non-empty image_path.",
                            expected_fix="Add image_path to the FigureRef, or remove malformed figure entries.",
                            evidence_hint="figure_id is optional here and may be backfilled later.",
                            original_item=item,
                        )
                    )
    confidence = properties.get("confidence")
    if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
        issues.append(
            _issue(
                target_type=target_type,
                target_id=target_id,
                source_context_id=source_context_id,
                issue_type="invalid_confidence",
                field_path="properties.confidence",
                reason="confidence must be a number in [0, 1].",
                expected_fix="Set confidence to a numeric value between 0 and 1.",
                evidence_hint="Follow schema confidence_policy.",
                original_item=item,
            )
        )
    return issues


def _readable_quote_length(quote: str) -> int:
    """Measure evidence length without counting LaTeX command names."""

    return len(LATEX_COMMAND_RE.sub("", quote))


def _unique_context_index(
    contexts: Sequence[ExtractionSectionContext],
    key_func: Any,
) -> dict[str, ExtractionSectionContext]:
    buckets: dict[str, list[ExtractionSectionContext]] = {}
    for context in contexts:
        key = str(key_func(context))
        if key:
            buckets.setdefault(key, []).append(context)
    return {key: bucket[0] for key, bucket in buckets.items() if len(bucket) == 1}


def _normalize_source_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = text.replace("\\", "/").lower()
    return re.sub(r"[\s_#\-:：，,。．.、·]+", "", text)


def _context_from_source_path(
    source_path: str,
    *,
    context_by_norm_path: dict[str, ExtractionSectionContext],
    context_by_norm_file: dict[str, ExtractionSectionContext],
) -> ExtractionSectionContext | None:
    if not source_path:
        return None
    norm_path = _normalize_source_key(source_path)
    if norm_path in context_by_norm_path:
        return context_by_norm_path[norm_path]
    name = Path(source_path.replace("\\", "/")).name
    return context_by_norm_file.get(_normalize_source_key(name))


def _resolve_context_for_item(
    item: dict[str, Any],
    *,
    context_by_exact_id: dict[str, ExtractionSectionContext],
    context_by_norm_id: dict[str, ExtractionSectionContext],
    context_by_norm_path: dict[str, ExtractionSectionContext],
    context_by_norm_file: dict[str, ExtractionSectionContext],
    context_by_section_id: dict[str, ExtractionSectionContext],
) -> ExtractionSectionContext | None:
    source_context_id = str(item.get("source_context_id", ""))
    if source_context_id in context_by_exact_id:
        return context_by_exact_id[source_context_id]
    context = context_by_norm_id.get(_normalize_source_key(source_context_id))
    if context is not None:
        return context
    properties = item.get("properties", {})
    if isinstance(properties, dict):
        context = _context_from_source_path(
            str(properties.get("source_path", "")),
            context_by_norm_path=context_by_norm_path,
            context_by_norm_file=context_by_norm_file,
        )
        if context is not None:
            return context
        for evidence in properties.get("evidence", []) if isinstance(properties.get("evidence"), list) else []:
            if not isinstance(evidence, dict):
                continue
            context = _context_from_source_path(
                str(evidence.get("source_path", "")),
                context_by_norm_path=context_by_norm_path,
                context_by_norm_file=context_by_norm_file,
            )
            if context is not None:
                return context
            section = evidence.get("section")
            if isinstance(section, dict):
                section_context_id = str(section.get("source_context_id", ""))
                if section_context_id in context_by_exact_id:
                    return context_by_exact_id[section_context_id]
                context = context_by_norm_id.get(_normalize_source_key(section_context_id))
                if context is not None:
                    return context
                section_id = str(section.get("id") or section.get("section_id") or "")
                if section_id in context_by_section_id:
                    return context_by_section_id[section_id]
    return None


def _section_title(context: ExtractionSectionContext) -> str:
    metadata = context.section_metadata
    for key in ["title", "chapter_title", "section_title"]:
        value = str(metadata.get(key, "")).strip()
        if value:
            return value
    return Path(context.markdown_file).stem


def _source_snapshot(item: dict[str, Any]) -> dict[str, str]:
    properties = item.get("properties", {})
    source_path = ""
    if isinstance(properties, dict):
        source_path = str(properties.get("source_path", ""))
        if not source_path:
            for evidence in properties.get("evidence", []) if isinstance(properties.get("evidence"), list) else []:
                if isinstance(evidence, dict) and evidence.get("source_path"):
                    source_path = str(evidence.get("source_path", ""))
                    break
    return {"source_context_id": str(item.get("source_context_id", "")), "source_path": source_path}


def _apply_context_to_item_sources(item: dict[str, Any], context: ExtractionSectionContext) -> None:
    item["source_context_id"] = context.source_context_id
    properties = item.get("properties")
    if not isinstance(properties, dict):
        return
    canonical_path = str(context.markdown_path)
    if "source_path" in properties:
        properties["source_path"] = canonical_path
    evidence = properties.get("evidence")
    if not isinstance(evidence, list):
        return
    title = _section_title(context)
    for ev in evidence:
        if not isinstance(ev, dict):
            continue
        source_type = ev.get("source_type")
        if source_type in {None, "textbook_body", "ipa_generated_text"}:
            ev["source_path"] = canonical_path
        section = ev.get("section")
        if not isinstance(section, dict):
            continue
        section["id"] = context.section_id
        section["title"] = title
        if "source_context_id" in section:
            section["source_context_id"] = context.source_context_id
        if "section_id" in section:
            section["section_id"] = context.section_id


def hard_issues_to_va_revise(
    *,
    stage: str,
    issues: Sequence[dict[str, Any]],
) -> str:
    """Convert hard-rule issues into a VA-compatible revise response.

    Args:
        stage: `node` or `edge`.
        issues: Hard-rule issue objects, each containing original item.

    Returns:
        Text containing `<VA_REVISE>` and one or more `<VA_REVISE_ITEM>`.
    """

    blocks = ["<VA_REVISE>"]
    for issue in issues:
        blocks.append("<VA_REVISE_ITEM>")
        blocks.append(f"Reason: {issue.get('reason', '')}")
        blocks.append("```json")
        blocks.append(json.dumps(issue, ensure_ascii=False, indent=2))
        blocks.append("```")
        blocks.append("</VA_REVISE_ITEM>")
    blocks.append("</VA_REVISE>")
    return "\n".join(blocks)


def parse_va_response(raw_text: str) -> dict[str, Any]:
    """Parse VA control tags and revise items.

    Args:
        raw_text: Raw VA output.

    Returns:
        Parsed result with status `pass` or `revise`.

    Raises:
        ValueError: If tags are missing, ambiguous, or malformed.
    """

    text = raw_text.strip()
    has_pass = "<VA_PASS>" in text and "</VA_PASS>" in text
    has_revise = "<VA_REVISE>" in text and "</VA_REVISE>" in text
    if has_pass == has_revise:
        raise ValueError("VA control tag missing or ambiguous")
    if has_pass:
        return {"status": "pass", "items": []}
    items = []
    for item_text in re.findall(r"<VA_REVISE_ITEM>(.*?)</VA_REVISE_ITEM>", text, re.S):
        try:
            item = extract_json_object(item_text)
        except ValueError as exc:
            raise ValueError("VA revise item JSON malformed") from exc
        if "original_item" not in item:
            raise ValueError("VA revise item missing original_item")
        items.append(item)
    if not items:
        raise ValueError("VA revise response has no revise items")
    return {"status": "revise", "items": items}


def try_parse_va_response(raw_text: str) -> dict[str, Any]:
    """Non-raising VA parse result for fallback paths."""

    try:
        parsed = parse_va_response(raw_text)
        parsed["parse_ok"] = True
        return parsed
    except ValueError as exc:
        return {
            "status": "parse_failed",
            "parse_ok": False,
            "items": [],
            "error": str(exc),
        }


def distill_feedback(parsed_va: dict[str, Any]) -> list[ValidationFeedback]:
    """Convert parsed VA revise items into feedback objects.

    Args:
        parsed_va: Parsed VA response.

    Returns:
        Feedback list for NEA or EEA. Empty when VA passed.
    """

    if parsed_va.get("status") == "pass":
        return []
    feedback = []
    for item in parsed_va.get("items", []):
        feedback.append(
            ValidationFeedback(
                target_type=str(item.get("target_type", "")),
                target_id=str(item.get("target_id", "")),
                source_context_id=str(item.get("source_context_id", "")),
                issue_type=str(item.get("issue_type", "")),
                field_path=str(item.get("field_path", "")),
                reason=str(item.get("reason", "")),
                expected_fix=str(item.get("expected_fix", "")),
                evidence_hint=str(item.get("evidence_hint", "")),
                original_item=dict(item.get("original_item", {})),
            )
        )
    return feedback
