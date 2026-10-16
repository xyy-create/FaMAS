"""Prompt builders for KG Extraction MAS."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from .models import ExtractionSectionContext, ValidationFeedback


COUNTED_NODE_LIMIT = 16
COUNTED_EDGE_LIMIT = 30
UNCOUNTED_NODE_LABELS = ["Problem", "ChapterSection"]
UNCOUNTED_EDGE_PREDICATES = ["contains", "tests"]


def _standards_text(standards: Sequence[dict[str, Any]]) -> str:
    parts = []
    for item in standards:
        parts.append(
            f"## {item['file']}\npath: {item['path']}\nchars: {item.get('chars', len(item.get('content', '')))}\nsha256: {item.get('sha256', '')}\n\n{item['content']}"
        )
    return "\n\n".join(parts)


def _standards_manifest(standards: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{key: value for key, value in item.items() if key != "content"} for item in standards]


def _contexts_payload(contexts: Sequence[ExtractionSectionContext]) -> list[dict[str, Any]]:
    payload: list[dict[str, Any]] = []
    for context in contexts:
        item = dict(context.to_json())
        item["ipa_image_evidence"] = [_compact_ipa_evidence(evidence) for evidence in context.ipa_image_evidence]
        payload.append(item)
    return payload


def normalize_figure_image_path(value: Any) -> str:
    image_path = str(value or "").strip().replace("\\", "/")
    marker = "images/"
    marker_index = image_path.find(marker)
    if marker_index >= 0:
        return image_path[marker_index:]
    return Path(image_path).name


def _truncate_text(text: Any, limit: int) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(0, limit - 1)] + "…"


def _compact_ipa_evidence(evidence: Any) -> dict[str, Any]:
    item = evidence.to_json() if hasattr(evidence, "to_json") else dict(evidence)
    compact = {
        "image_path": normalize_figure_image_path(item.get("image_path", "")),
        "image_type": item.get("image_type", ""),
        "description_text": str(item.get("result_text", "") or ""),
        "name": str(item.get("short_name") or item.get("name") or ""),
        "nearest_heading": item.get("nearest_heading", ""),
    }
    return compact


def _schema_text(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2)


def _count_policy() -> dict[str, Any]:
    return {
        "counted_node_limit": COUNTED_NODE_LIMIT,
        "counted_node_limit_per_section": COUNTED_NODE_LIMIT,
        "counted_edge_limit": COUNTED_EDGE_LIMIT,
        "counted_edge_limit_per_section": COUNTED_EDGE_LIMIT,
        "limit_scope": "per section_context, not per whole batch or whole textbook",
        "uncounted_node_labels": UNCOUNTED_NODE_LABELS,
        "uncounted_edge_predicates": UNCOUNTED_EDGE_PREDICATES,
        "counted_node_definition": "Any node whose label is not Problem or ChapterSection.",
        "counted_edge_definition": "Any edge whose source and target nodes are both counted nodes.",
    }


def _system(stage: str) -> str:
    return (
        f"You are {stage} in KG Extraction MAS. Output strict JSON unless VA control tags are explicitly required. "
        "Use only kg_schema_label_property_v2 node_labels, edge_labels, and shared_property_types. "
        "Images are not EvidenceRef evidence. EvidenceRef is text-only provenance with source_path, section, and quote_or_summary. "
        "Inspect section_contexts[].ipa_image_evidence to decide whether a real image is an intrinsic figure for a node or edge. "
        "If so, attach it only as a FigureRef in properties.figures with image_path, optional name, and optional description. "
        "Never fill figure_id; the pipeline backfills it. Do not create Image nodes."
    )


def _template(name: str) -> str:
    path = Path(__file__).with_name("prompts") / name
    return path.read_text(encoding="utf-8") if path.exists() else ""


def build_nea_prompt(
    *,
    contexts: Sequence[ExtractionSectionContext],
    schema: dict[str, Any],
    standards: Sequence[dict[str, Any]],
    feedback: Sequence[ValidationFeedback] | None = None,
) -> dict[str, Any]:
    """Build the Node Extraction Agent prompt package.

    Args:
        contexts: Bound enhanced Markdown section contexts.
        schema: Published KG schema.
        standards: All loaded standards files.
        feedback: Optional distilled VA feedback.

    Returns:
        Dict with `system`, `user`, `stage`, and metadata.
    """

    user = {
        "task": "Extract node candidates only.",
        "required_schema_version": "kg.node_extraction.v1",
        "schema": schema,
        "section_contexts": _contexts_payload(contexts),
        "standards_manifest": _standards_manifest(standards),
        "count_policy": _count_policy(),
        "distilled_va_feedback": [item.to_json() for item in feedback or []],
        "hard_boundaries": [
            "EvidenceRef is text-only provenance with only source_path, section, and quote_or_summary; it must not contain image references.",
            "Use section_contexts[].ipa_image_evidence only to decide whether to add FigureRef objects to node properties.figures.",
            "A FigureRef may include image_path, name, and description; never provide figure_id.",
            "Do not create Image nodes; images are properties.figures entries on the relevant node.",
            "Every node must have properties.evidence and properties.confidence.",
            "Count only non-Problem, non-ChapterSection nodes toward the node limit.",
            "Problem nodes and ChapterSection nodes are exempt from the node limit and should still be extracted when explicit evidence exists.",
            "Do not omit explicit Problem nodes in order to prioritize KnowledgePoint or ChapterSection nodes.",
            "Exhaustively extract every explicit textbook problem in the section, including worked examples, exercises, review questions, discussion questions, experimental questions, application questions, and multi-part questions.",
        ],
    }
    return {
        "stage": "nea",
        "system": _system("Node Extraction Agent") + "\n\n" + _template("nea_system.txt"),
        "user": _template("nea_user.txt")
        + "\n\nSTANDARDS\n"
        + _standards_text(standards)
        + "\n\nPUBLISHED_SCHEMA\n"
        + _schema_text(schema)
        + "\n\nINPUT_JSON\n"
        + json.dumps(user, ensure_ascii=False, indent=2),
        "metadata": {"standard_files": [item["file"] for item in standards]},
    }


def build_eea_prompt(
    *,
    contexts: Sequence[ExtractionSectionContext],
    node_pack: dict[str, Any],
    schema: dict[str, Any],
    standards: Sequence[dict[str, Any]],
    feedback: Sequence[ValidationFeedback] | None = None,
) -> dict[str, Any]:
    """Build the Edge Extraction Agent prompt package.

    Args:
        contexts: Bound enhanced Markdown section contexts.
        node_pack: VA-approved nodes with evidence.
        schema: Published KG schema.
        standards: All loaded standards files.
        feedback: Optional distilled VA feedback.

    Returns:
        Prompt package for EEA.
    """

    user = {
        "task": "Extract edge candidates only.",
        "required_schema_version": "kg.edge_extraction.v1",
        "node_pack": node_pack,
        "schema": schema,
        "section_contexts": _contexts_payload(contexts),
        "standards_manifest": _standards_manifest(standards),
        "count_policy": _count_policy(),
        "distilled_va_feedback": [item.to_json() for item in feedback or []],
        "hard_boundaries": [
            "Use only VA-approved node ids from node_pack.",
            "Use only schema edge_labels predicate_id.",
            "EvidenceRef is text-only provenance with only source_path, section, and quote_or_summary; it must not contain image references.",
            "Use section_contexts[].ipa_image_evidence only to decide whether to add FigureRef objects to edge properties.figures.",
            "A FigureRef may include image_path, name, and description; never provide figure_id.",
            "No edge without evidence.",
            "Count only edges whose source and target nodes are both non-Problem, non-ChapterSection nodes toward the edge limit.",
            "Edges involving Problem or ChapterSection nodes are exempt from the edge limit and should still be extracted when evidence exists.",
            "Do not leave an explicit Problem node disconnected merely to satisfy the edge limit.",
            "For every approved Problem node, extract all directly supported tests edges.",
        ],
    }
    return {
        "stage": "eea",
        "system": _system("Edge Extraction Agent") + "\n\n" + _template("eea_system.txt"),
        "user": _template("eea_user.txt")
        + "\n\nSTANDARDS\n"
        + _standards_text(standards)
        + "\n\nPUBLISHED_SCHEMA\n"
        + _schema_text(schema)
        + "\n\nINPUT_JSON\n"
        + json.dumps(user, ensure_ascii=False, indent=2),
        "metadata": {"standard_files": [item["file"] for item in standards]},
    }


def build_va_prompt(
    *,
    stage: str,
    candidates: dict[str, Any],
    contexts: Sequence[ExtractionSectionContext],
    schema: dict[str, Any],
    standards: Sequence[dict[str, Any]],
    node_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the Validation Agent prompt package.

    Args:
        stage: `node` or `edge`.
        candidates: Node or edge candidate package.
        contexts: Source contexts.
        schema: Published KG schema.
        standards: All loaded standards files.
        node_pack: Required for edge validation.

    Returns:
        Prompt package requiring VA control tags.
    """

    payload = {
        "stage": stage,
        "candidates": candidates,
        "section_contexts": _contexts_payload(contexts),
        "schema": schema,
        "standards_manifest": _standards_manifest(standards),
        "node_pack": node_pack,
        "hard_boundaries": [
            "EvidenceRef is text-only provenance with only source_path, section, and quote_or_summary; it must not contain image references.",
            "Validate properties.figures as FigureRef objects that reference real section_contexts[].ipa_image_evidence image_path values.",
            "Do not require Image nodes and do not ask the model to fill figure_id.",
        ],
        "required_output": "<VA_PASS>...</VA_PASS> or <VA_REVISE><VA_REVISE_ITEM>...</VA_REVISE_ITEM></VA_REVISE>",
    }
    return {
        "stage": f"va_{stage}",
        "system": (
            "You are Validation Agent. Validate semantic faithfulness and evidence traceability. "
            "Do not output chain-of-thought. Every revise item JSON must include complete original_item."
        )
        + "\n\n"
        + _template("va_system.txt"),
        "user": _template("va_user.txt") + "\n\n" + json.dumps(payload, ensure_ascii=False, indent=2),
        "metadata": {"standard_files": [item["file"] for item in standards]},
    }


def build_sda_prompt(
    *,
    node_pack: dict[str, Any],
    edge_pack: dict[str, Any],
    schema: dict[str, Any],
    standards: Sequence[dict[str, Any]],
    contexts: Sequence[ExtractionSectionContext],
) -> dict[str, Any]:
    """Build the Standard Agent prompt package.

    Args:
        node_pack: VA-approved node package.
        edge_pack: VA-approved edge package.
        schema: Published KG schema.
        standards: All loaded standards files.
        contexts: Section contexts used to derive domain profile.

    Returns:
        Prompt package for SdA standardization.
    """

    payload = {
        "task": "Standardize one KG into merged nodes, merged edges, and triples.",
        "node_pack": node_pack,
        "edge_pack": edge_pack,
        "schema": schema,
        "section_contexts": _contexts_payload(contexts),
        "standards_manifest": _standards_manifest(standards),
    }
    return {
        "stage": "sda",
        "system": _system("Standard Agent") + "\n\n" + _template("standard_system.txt"),
        "user": _template("standard_user.txt") + "\n\n" + json.dumps(payload, ensure_ascii=False, indent=2),
        "metadata": {"standard_files": [item["file"] for item in standards]},
    }
