"""CLI and orchestration for KG Extraction MAS."""

from __future__ import annotations

import argparse
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import re
import time
from typing import Any, Callable, Sequence
import unicodedata

from mas.common.progress import step
from mas.pipelines.common.usage_tracker import reset_usage, usage_snapshot

from .agents import (
    DEFAULT_TEXT_MODEL,
    DEFAULT_VALIDATION_API_KEY_ENV,
    DEFAULT_VALIDATION_BASE_URL,
    DEFAULT_VALIDATION_MODEL,
    DEFAULT_VALIDATION_PROVIDER,
    ExtractionModelCallError,
    ExtractionModelNotConfiguredError,
    ExtractionModelTimeoutError,
    run_eea,
    run_nea,
    run_va,
)
from .io import make_run_id, prepare_run_tree, write_json, write_report
from .models import ExtractionSectionContext, IpaImageEvidence, KgExtractionRunConfig, ValidationFeedback, jsonable, make_stable_id
from .prompts import (
    COUNTED_EDGE_LIMIT,
    COUNTED_NODE_LIMIT,
    UNCOUNTED_EDGE_PREDICATES,
    UNCOUNTED_NODE_LABELS,
    build_eea_prompt,
    build_nea_prompt,
    build_va_prompt,
    normalize_figure_image_path,
)
from .sources import build_section_contexts, load_published_schema, load_standards, split_markdown_blocks
from .standardize import standardize_kg
from .validation import (
    distill_feedback,
    hard_issues_to_va_revise,
    normalize_candidate_sources,
    parse_va_response,
    try_parse_va_response,
    validate_edges_hard,
    validate_nodes_hard,
)


CODE_ROOT = Path(__file__).resolve().parents[4]
CURRENT_RUN_PATHS: dict[str, Path] | None = None


def _standards_with_runtime_schema(standards: list[dict[str, Any]], schema_path: Path) -> list[dict[str, Any]]:
    schema_path = Path(schema_path)
    try:
        schema_content = schema_path.read_text(encoding="utf-8")
    except OSError:
        return standards
    schema_record = {
        "file": "kg_schema_label_property_v2.json",
        "path": str(schema_path.resolve()),
        "chars": len(schema_content),
        "sha256": hashlib.sha256(schema_content.encode("utf-8")).hexdigest(),
        "content": schema_content,
    }
    replaced = False
    updated: list[dict[str, Any]] = []
    for item in standards:
        if item.get("file") == "kg_schema_label_property_v2.json":
            updated.append(schema_record)
            replaced = True
        else:
            updated.append(item)
    if not replaced:
        updated.append(schema_record)
    return updated


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse KG extraction CLI arguments.

    Args:
        argv: Optional CLI argv list.

    Returns:
        Parsed argparse namespace.
    """

    parser = argparse.ArgumentParser(description="Run FaMAS KG extraction.")
    parser.add_argument("--enhanced-md", action="append", required=True)
    parser.add_argument("--sections-index", required=True)
    parser.add_argument("--standards-dir", required=True)
    parser.add_argument("--schema-path", required=True)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--node-model", default=DEFAULT_TEXT_MODEL)
    parser.add_argument("--edge-model", default=DEFAULT_TEXT_MODEL)
    parser.add_argument("--standard-model", default=DEFAULT_TEXT_MODEL)
    parser.add_argument("--validation-provider", default=DEFAULT_VALIDATION_PROVIDER)
    parser.add_argument("--validation-model", default=DEFAULT_VALIDATION_MODEL)
    parser.add_argument("--validation-base-url", default=DEFAULT_VALIDATION_BASE_URL)
    parser.add_argument("--validation-api-key-env", default=DEFAULT_VALIDATION_API_KEY_ENV)
    parser.add_argument("--max-revision-rounds", type=int, default=5)
    parser.add_argument("--node-batch-size", type=int, default=1)
    parser.add_argument("--qwen-timeout-seconds", type=int, default=120)
    parser.add_argument("--qwen-retry-attempts", type=int, default=3)
    parser.add_argument("--qwen-timeout-retry-attempts", type=int, default=2)
    parser.add_argument("--qwen-timeout-retry-budget-seconds", type=int, default=300)
    parser.add_argument("--qwen-max-tokens", type=int, default=8192)
    parser.add_argument("--qwen-max-input-tokens", type=int, default=64000)
    parser.add_argument("--source-context-id", action="append", default=[])
    parser.add_argument("--section-char-limit", type=int, default=80000)
    parser.add_argument("--edge-batch-size", type=int, default=1)
    parser.add_argument("--revision-context-window", type=int, default=1000)
    parser.add_argument("--revision-stall-threshold", type=int, default=2)
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> KgExtractionRunConfig:
    """Build run config from CLI args.

    Args:
        args: Parsed argparse namespace.

    Returns:
        KG extraction run config.
    """

    return KgExtractionRunConfig(
        enhanced_md_paths=[Path(item) for item in args.enhanced_md],
        sections_index_path=Path(args.sections_index),
        standards_dir=Path(args.standards_dir),
        schema_path=Path(args.schema_path),
        run_id=args.run_id,
        mock=bool(args.mock),
        node_model=args.node_model,
        edge_model=args.edge_model,
        standard_model=args.standard_model,
        validation_provider=args.validation_provider,
        validation_model=args.validation_model,
        validation_base_url=args.validation_base_url,
        validation_api_key_env=args.validation_api_key_env,
        max_revision_rounds=args.max_revision_rounds,
        node_batch_size=args.node_batch_size,
        qwen_timeout_seconds=args.qwen_timeout_seconds,
        qwen_retry_attempts=args.qwen_retry_attempts,
        qwen_timeout_retry_attempts=args.qwen_timeout_retry_attempts,
        qwen_timeout_retry_budget_seconds=args.qwen_timeout_retry_budget_seconds,
        qwen_max_tokens=args.qwen_max_tokens,
        qwen_max_input_tokens=args.qwen_max_input_tokens,
        source_context_ids=[str(item).strip() for item in args.source_context_id if str(item).strip()],
        section_char_limit=args.section_char_limit,
        edge_batch_size=args.edge_batch_size,
        revision_context_window=args.revision_context_window,
        revision_stall_threshold=args.revision_stall_threshold,
        resume=not args.no_resume,
    )


def _is_degraded_accepted_item(item: Any) -> bool:
    return (
        isinstance(item, dict)
        and (
            item.get("validation_status") == "degraded_accepted"
            or item.get("status") == "degraded_accepted"
            or item.get("quality_status") == "degraded"
        )
    )


def _accepted_package(
    stage: str,
    package: dict[str, Any],
    accepted_items: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
    degraded_accepted: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    degraded_accepted = list(degraded_accepted or [])
    if stage == "node":
        result = dict(package)
        result["nodes"] = accepted_items
        result["rejected_nodes"] = rejected
        result["degraded_accepted_nodes"] = degraded_accepted
        result["schema_version"] = "kg.node_pack.v1"
        result["validation_summary"] = {
            "accepted_count": len(accepted_items),
            "counted_accepted_count": sum(1 for item in accepted_items if _is_counted_node(item)),
            "rejected_count": len(rejected),
            "degraded_accepted_count": len(degraded_accepted),
            "max_revision_rounds": 5,
        }
        return result
    result = dict(package)
    result["edges"] = accepted_items
    result["rejected_edges"] = rejected
    result["degraded_accepted_edges"] = degraded_accepted
    return result


def _write_failure_outputs(
    *,
    paths: dict[str, Path],
    run_id: str,
    config: KgExtractionRunConfig,
    failed_stage: str,
    error: Exception,
    raw_response_path: Path | None = None,
) -> None:
    manifest = {
        "schema_version": "kg.extraction_manifest.v1",
        "run_id": Path(paths["output_dir"]).name,
        "status": "failed",
        "mock": config.mock,
        "failed_stage": failed_stage,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "raw_response_path": str(raw_response_path) if raw_response_path else "",
        "work_dir": str(paths["work_dir"]),
        "output_dir": str(paths["output_dir"]),
    }
    write_json(paths["output_dir"] / "kg_extraction_manifest.json", manifest)
    write_json(paths["work_dir"] / "manifest.json", manifest)
    write_report(
        paths["output_dir"] / "kg_extraction_report.md",
        "KG Extraction Report",
        [
            f"- run_id: `{Path(paths['output_dir']).name}`",
            "- status: `failed`",
            f"- failed_stage: `{failed_stage}`",
            f"- error_type: `{type(error).__name__}`",
            f"- raw_response_path: `{raw_response_path or ''}`",
        ],
    )


def _context_batches(contexts: Sequence[Any], batch_size: int) -> list[Sequence[Any]]:
    if batch_size <= 0 or batch_size >= len(contexts):
        return [contexts]
    return [contexts[index : index + batch_size] for index in range(0, len(contexts), batch_size)]


def split_oversized_section_contexts(
    contexts: Sequence[ExtractionSectionContext],
    *,
    section_char_limit: int = 80000,
) -> list[ExtractionSectionContext]:
    if section_char_limit <= 0:
        return list(contexts)
    split_contexts: list[ExtractionSectionContext] = []
    for context in contexts:
        if len(context.markdown_text) <= section_char_limit:
            split_contexts.append(context)
            continue
        blocks = split_markdown_blocks(context.markdown_text)
        if not blocks:
            split_contexts.append(context)
            continue
        ranges: list[tuple[int, int]] = []
        current_start: int | None = None
        current_end: int | None = None
        for block in blocks:
            block_start = int(block["start"])
            block_end = int(block["end"])
            if current_start is None:
                current_start = block_start
                current_end = block_end
                continue
            assert current_end is not None
            if block_end - current_start > section_char_limit and current_end > current_start:
                ranges.append((current_start, current_end))
                current_start = block_start
            current_end = block_end
        if current_start is not None and current_end is not None:
            ranges.append((current_start, current_end))
        total = len(ranges)
        for index, (start, end) in enumerate(ranges, start=1):
            part_text = context.markdown_text[start:end]
            split_contexts.append(
                ExtractionSectionContext(
                    source_context_id=context.source_context_id,
                    section_id=context.section_id,
                    markdown_path=context.markdown_path,
                    markdown_file=context.markdown_file,
                    markdown_text=part_text,
                    textbook_profile=dict(context.textbook_profile),
                    section_metadata=dict(context.section_metadata),
                    ipa_image_evidence=_filter_evidence_for_slice(
                        context.ipa_image_evidence,
                        full_text=context.markdown_text,
                        start=start,
                        end=end,
                    ),
                )
            )
    return split_contexts


def _filter_source_contexts(
    contexts: Sequence[ExtractionSectionContext],
    source_context_ids: Sequence[str],
) -> list[ExtractionSectionContext]:
    requested = {str(item).strip() for item in source_context_ids if str(item).strip()}
    if not requested:
        return list(contexts)

    selected: list[ExtractionSectionContext] = []
    for context in contexts:
        context_id = str(context.source_context_id).strip()
        section_id = str(context.section_id).strip()
        if context_id in requested or section_id in requested:
            selected.append(context)
            continue
        if section_id and any(
            requested_id.startswith(f"{section_id}_") or context_id.startswith(f"{requested_id}_")
            for requested_id in requested
        ):
            selected.append(context)
    if not selected:
        raise ValueError(
            "No enhanced Markdown contexts matched the requested source_context_ids."
        )
    return selected


def _filter_evidence_for_slice(
    evidence_items: Sequence[IpaImageEvidence],
    *,
    full_text: str,
    start: int,
    end: int,
) -> list[IpaImageEvidence]:
    filtered: list[IpaImageEvidence] = []
    for evidence in evidence_items:
        evidence_position = full_text.find(evidence.result_text) if evidence.result_text else -1
        if evidence_position < 0 and evidence.image_markdown:
            evidence_position = full_text.find(evidence.image_markdown)
        if start <= evidence_position < end:
            filtered.append(evidence)
    return filtered


def _merge_node_packages(packages: Sequence[dict[str, Any]], *, run_id: str, mock: bool) -> dict[str, Any]:
    nodes: list[dict[str, Any]] = []
    rejected: list[Any] = []
    for package in packages:
        nodes.extend(package.get("nodes", []))
        rejected.extend(package.get("rejected_evidence", []))
    return {
        "schema_version": "kg.node_extraction.v1",
        "run_id": run_id,
        "mock": mock,
        "batch_id": "merged_batches",
        "nodes": nodes,
        "rejected_evidence": rejected,
    }


def _merge_edge_packages(packages: Sequence[dict[str, Any]], *, run_id: str, mock: bool) -> dict[str, Any]:
    edges: list[dict[str, Any]] = []
    for package in packages:
        edges.extend(package.get("edges", []))
    return {
        "schema_version": "kg.edge_extraction.v1",
        "run_id": run_id,
        "mock": mock,
        "batch_id": "merged_batches",
        "edges": edges,
    }


def _schema_supports_edge(schema: dict[str, Any], predicate: str, source_label: str, target_label: str) -> bool:
    for item in schema.get("edge_labels", []):
        if not isinstance(item, dict):
            continue
        if (
            item.get("predicate_id") == predicate
            and item.get("source_label") == source_label
            and item.get("target_label") == target_label
        ):
            return True
    return False


def _node_display_text(node: dict[str, Any]) -> str:
    props = node.get("properties", {})
    for key in ("name", "title", "problem_text"):
        value = props.get(key)
        if value:
            return str(value)
    return str(node.get("node_id", ""))


def _node_evidence(node: dict[str, Any]) -> list[dict[str, Any]]:
    evidence = node.get("properties", {}).get("evidence", [])
    if not isinstance(evidence, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in evidence:
        if not isinstance(item, dict):
            continue
        copied = dict(item)
        quote = str(copied.get("quote_or_summary", "")).strip()
        if len(quote) > 120:
            copied["quote_or_summary"] = quote[:117].rstrip() + "..."
        cleaned.append(copied)
    return cleaned


def _token_overlap_score(left: str, right: str) -> int:
    left_tokens = {item for item in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", left) if len(item) >= 2}
    right_tokens = {item for item in re.findall(r"[\u4e00-\u9fffA-Za-z0-9]{2,}", right) if len(item) >= 2}
    generic = {"时代", "文化", "人类", "分布", "知识", "问题", "活动", "课程", "石器"}
    left_tokens -= generic
    right_tokens -= generic
    return len(left_tokens & right_tokens)


def _make_synthesized_edge(
    *,
    predicate: str,
    source: dict[str, Any],
    target: dict[str, Any],
    source_context_id: str,
    rationale: str,
    confidence: float,
) -> dict[str, Any]:
    evidence = _node_evidence(target) or _node_evidence(source)
    edge_id = make_stable_id(
        f"edge_{predicate}",
        [predicate, source.get("node_id", ""), target.get("node_id", ""), source_context_id],
    )
    return {
        "edge_id": edge_id,
        "predicate": predicate,
        "source_node_id": source.get("node_id", ""),
        "target_node_id": target.get("node_id", ""),
        "properties": {
            "relation_label": predicate,
            "rationale": rationale,
            "evidence": evidence,
            "confidence": confidence,
        },
        "source_context_id": source_context_id,
        "revision_round": 0,
        "status": "candidate",
        "audit_refs": ["deterministic_structural_edge"],
    }


def _synthesize_structural_edges(
    *,
    node_pack: dict[str, Any],
    edge_pack: dict[str, Any],
    schema: dict[str, Any],
) -> list[dict[str, Any]]:
    """Add schema-compatible structural edges when EEA returns an empty or sparse graph."""

    nodes = [node for node in node_pack.get("nodes", []) if isinstance(node, dict)]
    existing = {
        (edge.get("predicate"), edge.get("source_node_id"), edge.get("target_node_id"))
        for edge in edge_pack.get("edges", [])
        if isinstance(edge, dict)
    }
    by_label: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        by_label.setdefault(str(node.get("label", "")), []).append(node)

    synthesized: list[dict[str, Any]] = []

    def add(predicate: str, source: dict[str, Any], target: dict[str, Any], rationale: str, confidence: float) -> None:
        key = (predicate, source.get("node_id"), target.get("node_id"))
        if key in existing:
            return
        source_context_id = str(source.get("source_context_id") or target.get("source_context_id") or "")
        if not source_context_id:
            return
        if not _node_evidence(source) and not _node_evidence(target):
            return
        edge = _make_synthesized_edge(
            predicate=predicate,
            source=source,
            target=target,
            source_context_id=source_context_id,
            rationale=rationale,
            confidence=confidence,
        )
        synthesized.append(edge)
        existing.add(key)

    if _schema_supports_edge(schema, "contains", "ChapterSection", "KnowledgePoint"):
        sections = by_label.get("ChapterSection", [])
        specific_sections = [node for node in sections if node.get("properties", {}).get("section_num")]
        container_sections = specific_sections or sections
        for section in container_sections:
            for target in by_label.get("KnowledgePoint", []):
                if section.get("source_context_id") == target.get("source_context_id"):
                    add("contains", section, target, "The knowledge point is evidenced inside the same textbook section.", 0.88)

    if _schema_supports_edge(schema, "tests", "Problem", "KnowledgePoint"):
        knowledge_points = by_label.get("KnowledgePoint", [])
        for problem in by_label.get("Problem", []):
            problem_text = _node_display_text(problem)
            ranked = sorted(
                (
                    (_token_overlap_score(problem_text, _node_display_text(kp)), kp)
                    for kp in knowledge_points
                    if kp.get("source_context_id") == problem.get("source_context_id")
                ),
                key=lambda item: item[0],
                reverse=True,
            )
            for score, target in ranked[:2]:
                if score > 0 or _node_display_text(target) in problem_text:
                    add("tests", problem, target, "The problem text directly overlaps with the knowledge point name.", 0.78)

    if _schema_supports_edge(schema, "integrates", "CurriculumUnit", "KnowledgePoint"):
        for unit in by_label.get("CurriculumUnit", []):
            for target in by_label.get("KnowledgePoint", []):
                if unit.get("source_context_id") == target.get("source_context_id"):
                    add("integrates", unit, target, "The curriculum unit and knowledge point are extracted from the same integrated textbook context.", 0.72)

    return synthesized


def _merge_extraction_packages_for_batch(
    *,
    stage: str,
    packages: Sequence[dict[str, Any]],
    run_id: str,
    mock: bool,
    batch_id: str,
) -> dict[str, Any]:
    if stage == "node":
        merged = _merge_node_packages(packages, run_id=run_id, mock=mock)
    else:
        merged = _merge_edge_packages(packages, run_id=run_id, mock=mock)
    merged["batch_id"] = batch_id
    return merged


def _safe_prompt_context_suffix(contexts: Sequence[ExtractionSectionContext]) -> str:
    ids = [str(context.source_context_id or context.section_id or context.markdown_file).strip() for context in contexts]
    if not ids:
        return "unknown"
    suffix = "_".join(ids)
    suffix = re.sub(r"[^A-Za-z0-9_.-]+", "_", suffix).strip("._-")
    if len(suffix) > 80:
        digest = hashlib.sha256("_".join(ids).encode("utf-8")).hexdigest()[:10]
        suffix = f"{suffix[:69]}_{digest}"
    return suffix or "unknown"


def _node_pack_for_contexts(node_pack: dict[str, Any], contexts: Sequence[Any]) -> dict[str, Any]:
    context_ids = {context.source_context_id for context in contexts}
    local = dict(node_pack)
    local["nodes"] = [node for node in node_pack.get("nodes", []) if node.get("source_context_id") in context_ids]
    return local


def _candidate_package_for_contexts(
    *,
    stage: str,
    candidate_package: dict[str, Any],
    contexts: Sequence[Any],
) -> dict[str, Any]:
    context_ids = {context.source_context_id for context in contexts}
    normalized_context_ids = {_normalize_batch_key(context.source_context_id) for context in contexts}
    item_key = "nodes" if stage == "node" else "edges"
    local = dict(candidate_package)
    local[item_key] = [
        item
        for item in candidate_package.get(item_key, [])
        if item.get("source_context_id") in context_ids
        or _normalize_batch_key(item.get("source_context_id", "")) in normalized_context_ids
    ]
    return local


def _normalize_batch_key(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"[\s_#\-:：，,。．.、·]+", "", text).casefold()


def _merge_validation_packages(
    *,
    stage: str,
    base_package: dict[str, Any],
    packages: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    item_key = "nodes" if stage == "node" else "edges"
    rejected_key = "rejected_nodes" if stage == "node" else "rejected_edges"
    degraded_key = "degraded_accepted_nodes" if stage == "node" else "degraded_accepted_edges"
    merged = dict(base_package)
    merged[item_key] = [item for package in packages for item in package.get(item_key, [])]
    merged[rejected_key] = [item for package in packages for item in package.get(rejected_key, [])]
    merged[degraded_key] = [item for package in packages for item in package.get(degraded_key, [])]
    if stage == "node":
        merged["schema_version"] = "kg.node_pack.v1"
        merged["validation_summary"] = {
            "accepted_count": len(merged[item_key]),
            "counted_accepted_count": sum(1 for item in merged[item_key] if _is_counted_node(item)),
            "rejected_count": len(merged[rejected_key]),
            "degraded_accepted_count": len(merged[degraded_key]),
            "max_revision_rounds": base_package.get("validation_summary", {}).get("max_revision_rounds", 5),
        }
    return merged


def _merge_validation_audits(
    *,
    stage: str,
    audits: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    rejected: list[Any] = []
    degraded_accepted: list[Any] = []
    merged = {
        "stage": stage,
        "rounds": [],
        "source_normalizations": [],
        "rejected": rejected,
        "degraded_accepted": degraded_accepted,
        "batch_count": len(audits),
    }
    for batch_index, audit in enumerate(audits, start=1):
        for round_entry in audit.get("rounds", []):
            merged["rounds"].append(dict(round_entry, batch_index=batch_index))
        for entry in audit.get("source_normalizations", []):
            merged["source_normalizations"].append(dict(entry, batch_index=batch_index))
        rejected.extend(audit.get("rejected", []))
        degraded_accepted.extend(audit.get("degraded_accepted", []))
    return merged


def _normalized_image_path(value: Any) -> str:
    return normalize_figure_image_path(value)


def _context_ipa_image_index(contexts: Sequence[ExtractionSectionContext]) -> dict[str, dict[str, IpaImageEvidence]]:
    index: dict[str, dict[str, IpaImageEvidence]] = {}
    for context in contexts:
        bucket = index.setdefault(context.source_context_id, {})
        for evidence in context.ipa_image_evidence:
            image_path = _normalized_image_path(evidence.image_path)
            if image_path and image_path not in bucket:
                bucket[image_path] = evidence
    return index


def backfill_figure_ids(
    *,
    stage: str,
    package: dict[str, Any],
    contexts: Sequence[ExtractionSectionContext],
) -> dict[str, Any]:
    """Fill FigureRef.figure_id from section IPA image evidence and audit misses."""

    item_key = "nodes" if stage == "node" else "edges"
    id_key = _item_id_key(stage)
    image_index = _context_ipa_image_index(contexts)
    audit = {"stage": stage, "backfilled": [], "untraceable": []}
    for item in package.get(item_key, []):
        if not isinstance(item, dict):
            continue
        target_id = str(item.get(id_key, ""))
        source_context_id = str(item.get("source_context_id", ""))
        properties = item.get("properties", {})
        if not isinstance(properties, dict):
            continue
        figures = properties.get("figures")
        if not isinstance(figures, list):
            continue
        context_images = image_index.get(source_context_id, {})
        for index, figure in enumerate(figures):
            if not isinstance(figure, dict):
                continue
            image_path = str(figure.get("image_path", "")).strip()
            evidence = context_images.get(_normalized_image_path(image_path))
            if evidence is None:
                audit["untraceable"].append(
                    {
                        "stage": stage,
                        "target_type": stage,
                        "target_id": target_id,
                        "source_context_id": source_context_id,
                        "field_path": f"properties.figures[{index}].image_path",
                        "image_path": image_path,
                        "reason": "figure image_path not traceable to section ipa_image_evidence",
                    }
                )
                figure.pop("figure_id", None)
                continue
            old_figure_id = str(figure.get("figure_id", "") or "")
            figure["figure_id"] = evidence.evidence_key
            audit["backfilled"].append(
                {
                    "stage": stage,
                    "target_type": stage,
                    "target_id": target_id,
                    "source_context_id": source_context_id,
                    "field_path": f"properties.figures[{index}].figure_id",
                    "image_path": image_path,
                    "figure_id": evidence.evidence_key,
                    "previous_figure_id": old_figure_id,
                }
            )
    audit["backfilled_count"] = len(audit["backfilled"])
    audit["untraceable_count"] = len(audit["untraceable"])
    return audit


def _rejection_counts(package: dict[str, Any], rejected_key: str) -> tuple[int, int]:
    revision_rejected = 0
    timeout_skipped = 0
    for entry in package.get(rejected_key, []):
        if not isinstance(entry, dict):
            continue
        reason = entry.get("reason")
        if reason == "revision_not_converged":
            revision_rejected += 1
        elif reason == "timeout_exhausted":
            timeout_skipped += 1
    return revision_rejected, timeout_skipped


def _rate(rejected: int, accepted: int) -> float:
    denominator = accepted + rejected
    return (rejected / denominator) if denominator else 0


def _va_rejection_stats(*, node_pack: dict[str, Any], edge_pack: dict[str, Any]) -> dict[str, Any]:
    node_accepted = len(node_pack.get("nodes", []))
    edge_accepted = len(edge_pack.get("edges", []))
    node_rejected, node_timeout_skipped = _rejection_counts(node_pack, "rejected_nodes")
    edge_rejected, edge_timeout_skipped = _rejection_counts(edge_pack, "rejected_edges")
    return {
        "node_accepted": node_accepted,
        "node_rejected": node_rejected,
        "node_reject_rate": _rate(node_rejected, node_accepted),
        "edge_accepted": edge_accepted,
        "edge_rejected": edge_rejected,
        "edge_reject_rate": _rate(edge_rejected, edge_accepted),
        "node_timeout_skipped": node_timeout_skipped,
        "edge_timeout_skipped": edge_timeout_skipped,
    }


def _degraded_accepted_counts(*, node_pack: dict[str, Any], edge_pack: dict[str, Any]) -> dict[str, int]:
    node_entries = node_pack.get("degraded_accepted_nodes", [])
    edge_entries = edge_pack.get("degraded_accepted_edges", [])
    node_count = len(node_entries) if isinstance(node_entries, list) else 0
    edge_count = len(edge_entries) if isinstance(edge_entries, list) else 0
    if not node_count:
        node_count = sum(1 for item in node_pack.get("nodes", []) if _is_degraded_accepted_item(item))
    if not edge_count:
        edge_count = sum(1 for item in edge_pack.get("edges", []) if _is_degraded_accepted_item(item))
    return {"nodes": node_count, "edges": edge_count}


def _safe_revision_round(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _round_count_for_items(items: Sequence[Any], rejected: Sequence[Any]) -> dict[str, int]:
    rounds = [_safe_revision_round(item.get("revision_round", 0)) for item in items if isinstance(item, dict)]
    max_round = max(rounds, default=0)
    result = {f"round_{index}": 0 for index in range(max_round + 1)}
    for revision_round in rounds:
        result[f"round_{revision_round}"] = result.get(f"round_{revision_round}", 0) + 1
    result["not_converged"] = sum(
        1
        for entry in rejected
        if isinstance(entry, dict) and entry.get("reason") == "revision_not_converged"
    )
    return result


def _va_revision_round_counts(*, node_pack: dict[str, Any], edge_pack: dict[str, Any]) -> dict[str, Any]:
    return {
        "node": _round_count_for_items(node_pack.get("nodes", []), node_pack.get("rejected_nodes", [])),
        "edge": _round_count_for_items(edge_pack.get("edges", []), edge_pack.get("rejected_edges", [])),
    }


def _context_ipa_kg_value_index(contexts: Sequence[ExtractionSectionContext]) -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for context in contexts:
        bucket = result.setdefault(context.source_context_id, {})
        for evidence in context.ipa_image_evidence:
            image_path = _normalized_image_path(evidence.image_path)
            if image_path and image_path not in bucket:
                bucket[image_path] = str(evidence.kg_value or "").strip().lower()
    return result


def _figure_list(item: Any) -> list[dict[str, Any]]:
    if not isinstance(item, dict):
        return []
    properties = item.get("properties", {})
    if not isinstance(properties, dict):
        return []
    figures = properties.get("figures")
    if not isinstance(figures, list):
        return []
    return [figure for figure in figures if isinstance(figure, dict)]


def _figure_stats(
    *,
    merged_nodes: dict[str, Any],
    merged_edges: dict[str, Any],
    contexts: Sequence[ExtractionSectionContext],
    figure_ref_audit: dict[str, Any],
) -> dict[str, Any]:
    nodes = merged_nodes.get("nodes", [])
    edges = merged_edges.get("edges", [])
    node_figure_refs = 0
    edge_figure_refs = 0
    nodes_with_figure = 0
    edges_with_figure = 0
    kg_value_dist = {"high": 0, "medium": 0, "low": 0, "uncertain": 0, "unknown": 0}
    kg_value_index = _context_ipa_kg_value_index(contexts)
    for collection, counter_name in [(nodes, "node"), (edges, "edge")]:
        for item in collection if isinstance(collection, list) else []:
            figures = _figure_list(item)
            if not figures:
                continue
            if counter_name == "node":
                nodes_with_figure += 1
                node_figure_refs += len(figures)
            else:
                edges_with_figure += 1
                edge_figure_refs += len(figures)
            context_images = kg_value_index.get(str(item.get("source_context_id", "")), {})
            for figure in figures:
                kg_value = context_images.get(_normalized_image_path(figure.get("image_path", "")), "unknown")
                if kg_value not in kg_value_dist:
                    kg_value = "unknown"
                kg_value_dist[kg_value] += 1
    return {
        "nodes_total": len(nodes) if isinstance(nodes, list) else 0,
        "nodes_with_figure": nodes_with_figure,
        "node_figure_refs": node_figure_refs,
        "edges_total": len(edges) if isinstance(edges, list) else 0,
        "edges_with_figure": edges_with_figure,
        "edge_figure_refs": edge_figure_refs,
        "figure_refs_total": node_figure_refs + edge_figure_refs,
        "kg_value_dist": kg_value_dist,
        "untraceable_count": int(figure_ref_audit.get("untraceable_count", 0) or 0),
    }


def _numeric_confidences(package: dict[str, Any], item_key: str) -> list[float]:
    values: list[float] = []
    items = package.get(item_key, [])
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        properties = item.get("properties", {})
        if not isinstance(properties, dict):
            continue
        confidence = properties.get("confidence")
        if isinstance(confidence, (int, float)):
            values.append(float(confidence))
    return values


def _average(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0


def _avg_confidence(*, merged_nodes: dict[str, Any], merged_edges: dict[str, Any]) -> dict[str, float]:
    node_values = _numeric_confidences(merged_nodes, "nodes")
    edge_values = _numeric_confidences(merged_edges, "edges")
    return {
        "node": _average(node_values),
        "edge": _average(edge_values),
        "overall": _average([*node_values, *edge_values]),
    }


def _graph_label_index(nodes: Sequence[Any]) -> dict[str, str]:
    return {
        str(node.get("node_id", "")): str(node.get("label", ""))
        for node in nodes
        if isinstance(node, dict) and str(node.get("node_id", "")).strip()
    }


def _is_counted_node(node: Any) -> bool:
    if not isinstance(node, dict):
        return False
    return str(node.get("label", "")) not in set(UNCOUNTED_NODE_LABELS)


def _is_counted_edge(edge: Any, node_labels: dict[str, str]) -> bool:
    if not isinstance(edge, dict):
        return False
    predicate = str(edge.get("predicate", ""))
    source_label = node_labels.get(str(edge.get("source_node_id", "")), "")
    target_label = node_labels.get(str(edge.get("target_node_id", "")), "")
    return (
        predicate not in set(UNCOUNTED_EDGE_PREDICATES)
        and source_label not in set(UNCOUNTED_NODE_LABELS)
        and target_label not in set(UNCOUNTED_NODE_LABELS)
    )


def _graph_count_stats(*, merged_nodes: dict[str, Any], merged_edges: dict[str, Any]) -> dict[str, Any]:
    nodes = merged_nodes.get("nodes", [])
    edges = merged_edges.get("edges", [])
    node_list = nodes if isinstance(nodes, list) else []
    edge_list = edges if isinstance(edges, list) else []
    node_labels = _graph_label_index(node_list)
    counted_nodes = sum(1 for node in node_list if _is_counted_node(node))
    counted_edges = sum(1 for edge in edge_list if _is_counted_edge(edge, node_labels))
    return {
        "nodes_total": len(node_list),
        "nodes_counted": counted_nodes,
        "nodes_structural": len(node_list) - counted_nodes,
        "edges_total": len(edge_list),
        "edges_counted": counted_edges,
        "edges_structural": len(edge_list) - counted_edges,
        "count_policy": {
            "counted_node_limit": COUNTED_NODE_LIMIT,
            "counted_edge_limit": COUNTED_EDGE_LIMIT,
            "uncounted_node_labels": list(UNCOUNTED_NODE_LABELS),
            "uncounted_edge_predicates": list(UNCOUNTED_EDGE_PREDICATES),
        },
    }


def _empty_extraction_package(stage: str, *, run_id: str, mock: bool) -> dict[str, Any]:
    item_key = "nodes" if stage == "node" else "edges"
    schema_version = "kg.node_extraction.v1" if stage == "node" else "kg.edge_extraction.v1"
    return {
        "schema_version": schema_version,
        "run_id": run_id,
        "mock": mock,
        "batch_id": "empty_content_degraded",
        item_key: [],
    }


def _prepare_resumable_run_tree(run_id: str, *, work_root: Path | None, output_root: Path | None) -> dict[str, Path]:
    work_base = Path(work_root or (CODE_ROOT / "data" / "intermediate" / "kg_extraction_outputs"))
    output_base = Path(output_root or (CODE_ROOT / "data" / "output" / "kg_extraction_outputs"))
    work_dir = work_base / run_id
    output_dir = output_base / run_id
    paths = {
        "work_dir": work_dir,
        "output_dir": output_dir,
        "node": work_dir / "node_outputs",
        "edge": work_dir / "edge_outputs",
        "validation": work_dir / "validation_outputs",
        "standard": work_dir / "standard_outputs",
        "final_standard": output_dir / "standard_outputs",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    for stage in ["node", "edge", "validation", "standard"]:
        for rel in ["inputs", "prompts", "responses", "audit"]:
            (paths[stage] / rel).mkdir(parents=True, exist_ok=True)
    return paths


def _context_source_ids(context_batch: Sequence[ExtractionSectionContext]) -> list[str]:
    return [context.source_context_id for context in context_batch]


def _context_markdown_hashes(context_batch: Sequence[ExtractionSectionContext]) -> dict[str, str]:
    return {
        context.source_context_id: hashlib.sha256(context.markdown_text.encode("utf-8")).hexdigest()[:16]
        for context in context_batch
    }


def _batch_checkpoint_path(paths: dict[str, Path], stage: str, batch_index: int) -> Path:
    return paths[stage] / "batches" / f"batch_{batch_index:03d}.json"


def _load_batch_checkpoint(
    *,
    paths: dict[str, Path],
    stage: str,
    batch_index: int,
    context_batch: Sequence[ExtractionSectionContext],
    resume: bool,
) -> dict[str, Any] | None:
    if not resume:
        return None
    checkpoint_path = _batch_checkpoint_path(paths, stage, batch_index)
    if not checkpoint_path.exists():
        return None
    try:
        payload = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if payload.get("status") != "success":
        return None
    if payload.get("source_context_ids") != _context_source_ids(context_batch):
        return None
    if payload.get("markdown_content_hashes") != _context_markdown_hashes(context_batch):
        return None
    package = payload.get("package")
    return package if isinstance(package, dict) else None


def _write_batch_checkpoint(
    *,
    paths: dict[str, Path],
    stage: str,
    batch_index: int,
    batch_id: str,
    context_batch: Sequence[ExtractionSectionContext],
    package: dict[str, Any],
) -> None:
    write_json(
        _batch_checkpoint_path(paths, stage, batch_index),
        {
            "status": "success",
            "stage": stage,
            "batch_id": batch_id,
            "source_context_ids": _context_source_ids(context_batch),
            "markdown_content_hashes": _context_markdown_hashes(context_batch),
            "package": package,
        },
    )


def _collect_timeout_events(
    *,
    skipped_node_batches: Sequence[dict[str, Any]],
    skipped_edge_batches: Sequence[dict[str, Any]],
    skipped_node_reruns: Sequence[dict[str, Any]],
    skipped_edge_reruns: Sequence[dict[str, Any]],
    node_pack: dict[str, Any],
    edge_pack: dict[str, Any],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for entry in [*skipped_node_batches, *skipped_edge_batches, *skipped_node_reruns, *skipped_edge_reruns]:
        if entry.get("reason") == "timeout_exhausted":
            events.append(
                {
                    "stage": entry.get("stage"),
                    "batch_id": entry.get("batch_id"),
                    "target_ids": entry.get("target_ids", []),
                    "source_context_ids": entry.get("source_context_ids", []),
                    "attempts": entry.get("attempts"),
                    "elapsed": entry.get("elapsed"),
                    "prompt_path": entry.get("prompt_path"),
                    "raw_response_path": entry.get("raw_response_path"),
                    "error_type": entry.get("error_type"),
                    "error_message": entry.get("error_message"),
                    "attempt_records": entry.get("attempt_records", []),
                    "kind": "skipped",
                }
            )
    for stage, rejected_key, package in [
        ("node", "rejected_nodes", node_pack),
        ("edge", "rejected_edges", edge_pack),
    ]:
        for entry in package.get(rejected_key, []):
            if isinstance(entry, dict) and entry.get("reason") == "timeout_exhausted":
                timeout_event = entry.get("timeout_event", {}) if isinstance(entry.get("timeout_event"), dict) else {}
                events.append(
                    {
                        "stage": stage,
                        "target_id": entry.get("target_id"),
                        "source_context_ids": timeout_event.get("source_context_ids", []),
                        "attempts": timeout_event.get("attempts"),
                        "elapsed": timeout_event.get("elapsed"),
                        "prompt_path": timeout_event.get("prompt_path"),
                        "raw_response_path": timeout_event.get("raw_response_path"),
                        "error_type": timeout_event.get("error_type"),
                        "error_message": timeout_event.get("error_message"),
                        "attempt_records": timeout_event.get("attempt_records", []),
                        "kind": "rejected",
                    }
                )
    return events


def _manifest_status_from_degradation(
    *,
    timeout_events: Sequence[dict[str, Any]],
    skipped_node_batches: Sequence[dict[str, Any]],
    skipped_edge_batches: Sequence[dict[str, Any]],
) -> tuple[str, str]:
    skipped_batch_count = len(skipped_node_batches) + len(skipped_edge_batches)
    timeout_count = len(timeout_events)
    if skipped_batch_count or timeout_count:
        batch_label = "batch" if skipped_batch_count == 1 else "batches"
        event_label = "event" if timeout_count == 1 else "events"
        return "degraded", f"{skipped_batch_count} skipped {batch_label}; {timeout_count} timeout {event_label}"
    return "passed", ""


def _qwen_model_config(config: KgExtractionRunConfig, model: str) -> dict[str, Any]:
    return {
        "model": model,
        "timeout_seconds": config.qwen_timeout_seconds,
        "retry_attempts": config.qwen_retry_attempts,
        "timeout_retry_attempts": config.qwen_timeout_retry_attempts,
        "timeout_retry_budget_seconds": config.qwen_timeout_retry_budget_seconds,
        "max_tokens": config.qwen_max_tokens,
        "max_input_tokens": config.qwen_max_input_tokens,
    }


def _qwen_stage_model_config(config: KgExtractionRunConfig, model: str, stage: str) -> dict[str, Any]:
    model_config = _qwen_model_config(config, model)
    model_config["usage_stage"] = stage
    return model_config


def _is_empty_content_error(error: Exception) -> bool:
    return "content is empty" in str(error).lower()


def _is_retryable_extractor_response_error(error: Exception) -> bool:
    text = str(error).lower()
    return "content is empty" in text or "response is not valid json" in text


def _sleep_nea_retry(attempt: int, config: KgExtractionRunConfig) -> None:
    if config.mock:
        return
    time.sleep(0.5 * attempt)


def _run_nea_with_empty_content_retry(
    *,
    prompt: dict[str, Any],
    config: KgExtractionRunConfig,
    prompt_path: Path,
    raw_response_path: Path,
    batch_id: str,
    context_batch: Sequence[ExtractionSectionContext],
    max_attempts: int = 3,
    allow_timeout_degraded_retry: bool = True,
) -> tuple[dict[str, Any] | None, str, dict[str, Any] | list[dict[str, Any]] | None]:
    return _run_extractor_with_empty_content_retry(
        stage="node",
        prompt=prompt,
        config=config,
        prompt_path=prompt_path,
        raw_response_path=raw_response_path,
        batch_id=batch_id,
        context_batch=context_batch,
        runner=run_nea,
        model=config.node_model,
        max_attempts=max_attempts,
        allow_timeout_degraded_retry=allow_timeout_degraded_retry,
    )


def _run_eea_with_empty_content_retry(
    *,
    prompt: dict[str, Any],
    config: KgExtractionRunConfig,
    prompt_path: Path,
    raw_response_path: Path,
    batch_id: str,
    context_batch: Sequence[ExtractionSectionContext],
    max_attempts: int = 3,
    allow_timeout_degraded_retry: bool = True,
) -> tuple[dict[str, Any] | None, str, dict[str, Any] | list[dict[str, Any]] | None]:
    return _run_extractor_with_empty_content_retry(
        stage="edge",
        prompt=prompt,
        config=config,
        prompt_path=prompt_path,
        raw_response_path=raw_response_path,
        batch_id=batch_id,
        context_batch=context_batch,
        runner=run_eea,
        model=config.edge_model,
        max_attempts=max_attempts,
        allow_timeout_degraded_retry=allow_timeout_degraded_retry,
    )


def _timeout_skipped_record(
    *,
    stage: str,
    batch_id: str,
    config: KgExtractionRunConfig,
    prompt_path: Path,
    raw_response_path: Path,
    context_batch: Sequence[ExtractionSectionContext],
    error: ExtractionModelTimeoutError,
    degraded_retry: bool = False,
) -> dict[str, Any]:
    skipped = {
        "batch_id": batch_id,
        "stage": stage,
        "reason": "timeout_exhausted",
        "attempts": config.qwen_timeout_retry_attempts,
        "elapsed": None,
        "error_type": type(error).__name__,
        "error_message": str(error),
        "attempt_records": list(getattr(error, "attempt_records", [])),
        "prompt_path": str(prompt_path),
        "raw_response_path": str(raw_response_path),
        "source_context_ids": _context_source_ids(context_batch),
    }
    if degraded_retry:
        skipped["degraded_retry"] = True
    return skipped


def _skipped_records(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return [value] if isinstance(value, dict) else []


def _prompt_with_single_context(
    *,
    stage: str,
    prompt: dict[str, Any],
    context: ExtractionSectionContext,
) -> dict[str, Any]:
    single_prompt = dict(prompt)
    user = str(prompt.get("user", ""))
    if "INPUT_JSON" not in user:
        return single_prompt
    prefix, payload_text = user.split("INPUT_JSON", 1)
    try:
        payload = json.loads(payload_text.strip())
    except json.JSONDecodeError:
        return single_prompt
    context_payload = context.to_json()
    for item in payload.get("section_contexts", []):
        if isinstance(item, dict) and item.get("source_context_id") == context.source_context_id:
            context_payload = item
            break
    payload["section_contexts"] = [context_payload]
    if stage == "edge" and isinstance(payload.get("node_pack"), dict):
        payload["node_pack"] = _node_pack_for_contexts(payload["node_pack"], [context])
    single_prompt["user"] = prefix + "INPUT_JSON\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    return single_prompt


def _retry_timed_out_batch_by_section(
    *,
    stage: str,
    prompt: dict[str, Any],
    config: KgExtractionRunConfig,
    prompt_path: Path,
    raw_response_path: Path,
    batch_id: str,
    context_batch: Sequence[ExtractionSectionContext],
    runner: Callable[..., tuple[dict[str, Any], str]],
    model: str,
    timeout_error: ExtractionModelTimeoutError,
) -> tuple[dict[str, Any] | None, str, list[dict[str, Any]] | None]:
    recovered_packages: list[dict[str, Any]] = []
    skipped_records: list[dict[str, Any]] = []
    raw_parts: list[str] = []
    for section_index, context in enumerate(context_batch, start=1):
        section_batch_id = f"{batch_id}_section_{section_index:03d}"
        section_prompt = _prompt_with_single_context(stage=stage, prompt=prompt, context=context)
        section_prompt_path = prompt_path.with_name(f"{prompt_path.stem}_section_{section_index:03d}{prompt_path.suffix}")
        section_raw_path = raw_response_path.with_name(f"{raw_response_path.stem}_section_{section_index:03d}{raw_response_path.suffix}")
        write_json(section_prompt_path, section_prompt)
        try:
            package, raw, skipped = _run_extractor_with_empty_content_retry(
                stage=stage,
                prompt=section_prompt,
                config=config,
                prompt_path=section_prompt_path,
                raw_response_path=section_raw_path,
                batch_id=section_batch_id,
                context_batch=[context],
                runner=runner,
                model=model,
                allow_timeout_degraded_retry=False,
            )
        except ExtractionModelTimeoutError as exc:
            raw = getattr(exc, "raw_response", "") or ""
            section_raw_path.write_text(raw, encoding="utf-8")
            skipped = _timeout_skipped_record(
                stage=stage,
                batch_id=section_batch_id,
                config=config,
                prompt_path=section_prompt_path,
                raw_response_path=section_raw_path,
                context_batch=[context],
                error=exc,
                degraded_retry=True,
            )
            package = None
        raw_parts.append(raw)
        records = _skipped_records(skipped)
        if records:
            for record in records:
                record["degraded_retry"] = True
            skipped_records.extend(records)
            if package is None:
                continue
        if package is not None:
            recovered_packages.append(package)

    merged_raw = "\n".join(part for part in raw_parts if part)
    raw_response_path.write_text(merged_raw, encoding="utf-8")
    if not recovered_packages:
        if not skipped_records:
            skipped_records.append(
                _timeout_skipped_record(
                    stage=stage,
                    batch_id=batch_id,
                    config=config,
                    prompt_path=prompt_path,
                    raw_response_path=raw_response_path,
                    context_batch=context_batch,
                    error=timeout_error,
                    degraded_retry=True,
                )
            )
        return None, merged_raw, skipped_records
    package = _merge_extraction_packages_for_batch(
        stage=stage,
        packages=recovered_packages,
        run_id=str(recovered_packages[0].get("run_id", batch_id)),
        mock=config.mock,
        batch_id=batch_id,
    )
    if skipped_records:
        package["degraded_retry_skipped_batches"] = skipped_records
    return package, merged_raw, skipped_records or None


def _run_extractor_with_empty_content_retry(
    *,
    stage: str,
    prompt: dict[str, Any],
    config: KgExtractionRunConfig,
    prompt_path: Path,
    raw_response_path: Path,
    batch_id: str,
    context_batch: Sequence[ExtractionSectionContext],
    runner: Callable[..., tuple[dict[str, Any], str]],
    model: str,
    max_attempts: int = 3,
    allow_timeout_degraded_retry: bool = True,
) -> tuple[dict[str, Any] | None, str, dict[str, Any] | list[dict[str, Any]] | None]:
    last_error: Exception | None = None
    last_raw = ""
    for attempt in range(1, max_attempts + 1):
        try:
            stage_label = "NEA" if stage == "node" else "EEA"
            package, raw = runner(prompt, mock=config.mock, model_config=_qwen_stage_model_config(config, model, stage_label))
            return package, raw, None
        except (ExtractionModelCallError, ExtractionModelNotConfiguredError) as exc:
            # The provider layer owns network/timeout retries. This outer loop
            # retries completed responses that are empty or malformed JSON.
            if isinstance(exc, ExtractionModelTimeoutError):
                last_raw = getattr(exc, "raw_response", "") or ""
                raw_response_path.write_text(last_raw, encoding="utf-8")
                if allow_timeout_degraded_retry and stage in {"node", "edge"} and len(context_batch) > 1:
                    return _retry_timed_out_batch_by_section(
                        stage=stage,
                        prompt=prompt,
                        config=config,
                        prompt_path=prompt_path,
                        raw_response_path=raw_response_path,
                        batch_id=batch_id,
                        context_batch=context_batch,
                        runner=runner,
                        model=model,
                        timeout_error=exc,
                    )
                return (
                    None,
                    last_raw,
                    _timeout_skipped_record(
                        stage=stage,
                        batch_id=batch_id,
                        config=config,
                        prompt_path=prompt_path,
                        raw_response_path=raw_response_path,
                        context_batch=context_batch,
                        error=exc,
                    ),
                )
            if not _is_retryable_extractor_response_error(exc):
                raise
            last_error = exc
            last_raw = getattr(exc, "raw_response", "") or ""
            if attempt < max_attempts:
                _sleep_nea_retry(attempt, config)
                continue
    raw_response_path.write_text(last_raw, encoding="utf-8")
    skipped = {
        "batch_id": batch_id,
        "stage": stage,
        "reason": "retryable_response_error_exhausted",
        "attempts": max_attempts,
        "error_type": type(last_error).__name__ if last_error else "ExtractionModelCallError",
        "error_message": str(last_error) if last_error else f"{stage} response content is empty",
        "prompt_path": str(prompt_path),
        "raw_response_path": str(raw_response_path),
        "source_context_ids": [context.source_context_id for context in context_batch],
    }
    return None, last_raw, skipped


def _sleep_va_retry(attempt: int, config: KgExtractionRunConfig) -> None:
    if config.mock:
        return
    time.sleep(1.5 * attempt)


def _run_va_with_retry(
    *,
    stage: str,
    prompt: dict[str, Any],
    config: KgExtractionRunConfig,
    max_attempts: int = 3,
) -> tuple[str, int, dict[str, Any]]:
    """Run VA until its response parses or max attempts are exhausted."""

    raw_va = ""
    parsed: dict[str, Any] = {"status": "parse_failed", "parse_ok": False, "items": [], "error": ""}
    last_error: ExtractionModelCallError | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            raw_va = run_va(
                prompt,
                mock=config.mock,
                validation_config={
                    "provider": config.validation_provider,
                    "model": config.validation_model,
                    "base_url": config.validation_base_url,
                    "api_key_env": config.validation_api_key_env,
                    "usage_stage": "VA (node)" if stage == "node" else "VA (edge)",
                },
            )
        except ExtractionModelCallError as exc:
            if not _is_empty_content_error(exc):
                raise
            last_error = exc
            raw_va = getattr(exc, "raw_response", "") or ""
            parsed = {
                "status": "parse_failed",
                "parse_ok": False,
                "items": [],
                "error": str(exc),
            }
            if attempt < max_attempts:
                _sleep_va_retry(attempt, config)
                continue
            break
        parsed = try_parse_va_response(raw_va)
        if parsed.get("parse_ok"):
            return raw_va, attempt, parsed
        if attempt < max_attempts:
            _sleep_va_retry(attempt, config)
    if last_error is not None and not raw_va:
        raw_va = getattr(last_error, "raw_response", "") or ""
    return raw_va, max_attempts, parsed


def _item_id_key(stage: str) -> str:
    return "node_id" if stage == "node" else "edge_id"


def _revision_anchor_candidates(feedback: ValidationFeedback) -> list[str]:
    item = feedback.original_item
    candidates: list[str] = []
    properties = item.get("properties", {}) if isinstance(item, dict) else {}
    evidence = properties.get("evidence", []) if isinstance(properties, dict) else []
    if isinstance(evidence, list):
        for ev in evidence:
            if isinstance(ev, dict):
                candidates.append(str(ev.get("quote_or_summary", "")).strip())
    for key in ["problem_text", "definition", "name", "title"]:
        value = properties.get(key) if isinstance(properties, dict) else None
        if value is None and isinstance(item, dict):
            value = item.get(key)
        if isinstance(value, str):
            candidates.append(value.strip()[:160])
    if feedback.evidence_hint:
        candidates.append(feedback.evidence_hint.strip()[:160])
    unique: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if len(candidate) < 4 or candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
    return unique


def _locate_revision_anchor(context: ExtractionSectionContext, feedback: ValidationFeedback) -> tuple[int, int] | None:
    for anchor in _revision_anchor_candidates(feedback):
        position = context.markdown_text.find(anchor)
        if position >= 0:
            return position, position + len(anchor)
        compact_anchor = re.sub(r"\s+", " ", anchor).strip()
        if compact_anchor != anchor:
            position = context.markdown_text.find(compact_anchor)
            if position >= 0:
                return position, position + len(compact_anchor)
    return None


def _minimal_revision_markdown(feedback: ValidationFeedback) -> str:
    item = feedback.original_item
    snippets = _revision_anchor_candidates(feedback)
    return "\n".join(
        [
            "Revision target current item:",
            "```json",
            json.dumps(item, ensure_ascii=False, indent=2),
            "```",
            "Existing evidence snippets:",
            *[f"- {snippet}" for snippet in snippets],
        ]
    )


def _merge_windows(windows: Sequence[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[tuple[int, int]] = []
    for start, end in sorted(windows):
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
            continue
        merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return merged


def _build_revision_contexts(
    *,
    feedback: Sequence[ValidationFeedback],
    contexts: Sequence[ExtractionSectionContext],
    window_size: int,
) -> list[ExtractionSectionContext]:
    context_by_id: dict[str, list[ExtractionSectionContext]] = {}
    for context in contexts:
        context_by_id.setdefault(context.source_context_id, []).append(context)
    grouped: dict[str, dict[str, Any]] = {}
    safe_window = max(0, int(window_size))

    for item_feedback in feedback:
        matches = context_by_id.get(item_feedback.source_context_id, [])
        located_context: ExtractionSectionContext | None = None
        located_span: tuple[int, int] | None = None
        for context in matches:
            span = _locate_revision_anchor(context, item_feedback)
            if span is not None:
                located_context = context
                located_span = span
                break
        base_context = located_context or (matches[0] if matches else None)
        group_key = item_feedback.source_context_id or f"missing_context_{len(grouped)}"
        group = grouped.setdefault(
            group_key,
            {"context": base_context, "windows": [], "fallbacks": []},
        )
        if group["context"] is None and base_context is not None:
            group["context"] = base_context
        if located_context is not None and located_span is not None:
            start, end = located_span
            group["context"] = located_context
            group["windows"].append(
                (
                    max(0, start - safe_window),
                    min(len(located_context.markdown_text), end + safe_window),
                )
            )
        else:
            group["fallbacks"].append(_minimal_revision_markdown(item_feedback))

    narrowed: list[ExtractionSectionContext] = []
    for source_context_id, group in grouped.items():
        base_context = group["context"]
        parts: list[str] = []
        if base_context is not None:
            for start, end in _merge_windows(group["windows"]):
                parts.append(base_context.markdown_text[start:end])
        parts.extend(group["fallbacks"])
        if not parts:
            continue
        markdown_text = "\n\n--- REVISION CONTEXT WINDOW ---\n\n".join(parts)
        if base_context is not None:
            narrowed.append(replace(base_context, markdown_text=markdown_text))
        else:
            narrowed.append(
                ExtractionSectionContext(
                    source_context_id=source_context_id,
                    section_id="",
                    markdown_path=Path(""),
                    markdown_file="",
                    markdown_text=markdown_text,
                    textbook_profile={},
                    section_metadata={},
                    ipa_image_evidence=[],
                )
            )
    return narrowed


def _revision_rejection_entry(
    *,
    item: dict[str, Any],
    feedback: ValidationFeedback,
    consecutive_rounds: int,
) -> dict[str, Any]:
    return {
        "reason": "revision_not_converged",
        "target_id": feedback.target_id,
        "issue_type": feedback.issue_type,
        "field_path": feedback.field_path,
        "last_issue": {
            "reason": feedback.reason,
            "expected_fix": feedback.expected_fix,
            "evidence_hint": feedback.evidence_hint,
        },
        "consecutive_rounds": consecutive_rounds,
        "item": item,
    }


def _degraded_acceptance_entry(
    *,
    stage: str,
    item: dict[str, Any],
    reason: str,
    round_index: int,
    feedback: ValidationFeedback | None = None,
    timeout_event: dict[str, Any] | None = None,
    detail: str = "",
) -> tuple[dict[str, Any], dict[str, Any]]:
    target_id = str(item.get(_item_id_key(stage), ""))
    audit_ref = {
        "stage": stage,
        "target_id": target_id,
        "source_context_id": str(item.get("source_context_id", "")),
        "round": round_index,
        "reason": reason,
    }
    accepted_item = copy.deepcopy(item)
    accepted_item["status"] = "degraded_accepted"
    accepted_item["quality_status"] = "degraded"
    accepted_item["validation_status"] = "degraded_accepted"
    accepted_item["degradation_reason"] = reason
    accepted_item.setdefault("audit_refs", [])
    if isinstance(accepted_item["audit_refs"], list):
        accepted_item["audit_refs"].append(audit_ref)
    accepted_item.setdefault("validation_audit_refs", [])
    if isinstance(accepted_item["validation_audit_refs"], list):
        accepted_item["validation_audit_refs"].append(audit_ref)

    audit_entry: dict[str, Any] = {
        "stage": stage,
        "target_id": target_id,
        "source_context_id": audit_ref["source_context_id"],
        "round": round_index,
        "reason": reason,
        "item": accepted_item,
    }
    if feedback is not None:
        audit_entry["last_issue"] = {
            "issue_type": feedback.issue_type,
            "field_path": feedback.field_path,
            "reason": feedback.reason,
            "expected_fix": feedback.expected_fix,
            "evidence_hint": feedback.evidence_hint,
        }
    if timeout_event is not None:
        audit_entry["timeout_event"] = timeout_event
    if detail:
        audit_entry["detail"] = detail
    return accepted_item, audit_entry


def _timeout_revision_rejection_entry(
    *,
    stage: str,
    item: dict[str, Any],
    timeout_event: dict[str, Any],
) -> dict[str, Any]:
    target_id = str(item.get(_item_id_key(stage), ""))
    return {
        "reason": "timeout_exhausted",
        "target_id": target_id,
        "issue_type": "timeout_exhausted",
        "field_path": "",
        "last_issue": {
            "reason": timeout_event.get("error_message", "revision timeout exhausted"),
            "expected_fix": "retry this revision target in a later run",
            "evidence_hint": "provider timeout while revising this target",
        },
        "timeout_event": timeout_event,
        "item": item,
    }


def validate_with_revision_loop(
    *,
    stage: str,
    initial_package: dict[str, Any],
    rerun_callback: Callable[[Sequence[ValidationFeedback], int, Sequence[Any], dict[str, Any]], dict[str, Any]],
    schema: dict[str, Any],
    contexts: Sequence[Any],
    node_pack: dict[str, Any] | None,
    standards: Sequence[dict[str, Any]],
    config: KgExtractionRunConfig,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate node or edge candidates with local revision loop.

    Args:
        stage: `node` or `edge`.
        initial_package: Initial NEA/EEA candidate package.
        rerun_callback: Function that reruns affected extraction with feedback.
        schema: Published KG schema.
        contexts: Source contexts.
        node_pack: Required for edge validation.
        standards: Loaded standards files.
        config: Run config.

    Returns:
        Tuple of accepted package and validation audit.
    """

    current_package = initial_package
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    degraded_accepted: list[dict[str, Any]] = []
    audit = {
        "stage": stage,
        "rounds": [],
        "source_normalizations": [],
        "rejected": rejected,
        "degraded_accepted": degraded_accepted,
    }
    item_key = "nodes" if stage == "node" else "edges"
    id_key = _item_id_key(stage)
    pending_ids = None
    stall_counts: dict[tuple[str, str], int] = {}
    previous_issue_pairs: set[tuple[str, str]] = set()
    paths = CURRENT_RUN_PATHS
    for round_index in range(config.max_revision_rounds + 1):
        items = current_package.get(item_key, [])
        if pending_ids is not None:
            items = [item for item in items if item.get(id_key) in pending_ids]
        temp_package = dict(current_package)
        temp_package[item_key] = items
        temp_package, source_normalizations = normalize_candidate_sources(
            stage=stage,
            candidate_package=temp_package,
            contexts=contexts,
        )
        items = temp_package.get(item_key, [])
        if source_normalizations:
            audit["source_normalizations"].extend(
                [dict(entry, round=round_index) for entry in source_normalizations]
            )
        if not items:
            degraded = current_package.get("degraded_revision") if isinstance(current_package, dict) else None
            if pending_ids is not None and isinstance(degraded, dict) and degraded.get("reason") == "timeout_exhausted":
                degraded_items = [
                    item
                    for item in current_package.get("degraded_revision_items", [])
                    if isinstance(item, dict) and str(item.get(id_key, "")) in pending_ids
                ]
                degraded_audit_entries: list[dict[str, Any]] = []
                for item in degraded_items:
                    accepted_item, audit_entry = _degraded_acceptance_entry(
                        stage=stage,
                        item=item,
                        reason="revision_timeout_exhausted",
                        round_index=round_index,
                        timeout_event=degraded,
                    )
                    accepted.append(accepted_item)
                    degraded_accepted.append(audit_entry)
                    degraded_audit_entries.append(audit_entry)
                audit["rounds"].append(
                    {
                        "round": round_index,
                        "status": "degraded_accepted",
                        "reason": "revision_timeout_exhausted",
                        "target_ids": [str(item.get(id_key, "")) for item in degraded_items],
                        "issue_count": len(degraded_items),
                        "va_attempts": 0,
                        "degraded_accepted_count": len(degraded_audit_entries),
                    }
                )
                break
            audit["rounds"].append(
                {
                    "round": round_index,
                    "status": "pass",
                    "issue_count": 0,
                    "va_attempts": 0,
                    "note": "no pending items after degraded rerun",
                }
            )
            break
        issues = (
            validate_nodes_hard(temp_package, schema, contexts)
            if stage == "node"
            else validate_edges_hard(temp_package, schema, node_pack or {}, contexts)
        )
        va_attempts = 1
        if issues:
            raw_va = hard_issues_to_va_revise(stage=stage, issues=issues)
            parsed = parse_va_response(raw_va)
        else:
            prompt = build_va_prompt(
                stage=stage,
                candidates=temp_package,
                contexts=contexts,
                schema=schema,
                standards=standards,
                node_pack=node_pack,
            )
            if paths:
                prompt_dir = paths["validation"] / stage / "prompts"
                prompt_dir.mkdir(parents=True, exist_ok=True)
                write_json(prompt_dir / f"va_{stage}_round_{round_index:03d}.json", prompt)
            raw_va, va_attempts, parsed = _run_va_with_retry(
                stage=stage,
                prompt=prompt,
                config=config,
            )
        if paths:
            response_dir = paths["validation"] / stage / "responses"
            response_dir.mkdir(parents=True, exist_ok=True)
            (response_dir / f"va_{stage}_round_{round_index:03d}.txt").write_text(raw_va, encoding="utf-8")
        if not parsed.get("parse_ok", True):
            if paths:
                _write_failure_outputs(
                    paths=paths,
                    run_id=config.run_id or "",
                    config=config,
                    failed_stage=f"va_{stage}_parse",
                    error=ValueError(parsed.get("error", "VA parse failed")),
                    raw_response_path=paths["validation"] / stage / "responses" / f"va_{stage}_round_{round_index:03d}.txt",
                )
            audit["rounds"].append(
                {
                    "round": round_index,
                    "status": "degraded_accepted",
                    "reason": "va_parse_failed",
                    "issue_count": len(items),
                    "va_attempts": va_attempts,
                    "note": "VA response unparseable after retries; last usable candidates accepted as degraded",
                }
            )
            for item in items:
                accepted_item, audit_entry = _degraded_acceptance_entry(
                    stage=stage,
                    item=item,
                    reason="va_parse_failed",
                    round_index=round_index,
                    detail=str(parsed.get("error", "")),
                )
                accepted.append(accepted_item)
                degraded_accepted.append(audit_entry)
            break
        audit["rounds"].append(
            {
                "round": round_index,
                "status": parsed["status"],
                "issue_count": len(parsed.get("items", [])),
                "va_attempts": va_attempts,
            }
        )
        if parsed["status"] == "pass":
            accepted.extend(items)
            break
        feedback = distill_feedback(parsed)
        failed_ids = {item.target_id for item in feedback}
        item_by_id = {str(item.get(id_key, "")): item for item in items if isinstance(item, dict)}
        feedback_by_pair = {(item.target_id, item.issue_type): item for item in feedback}
        current_issue_pairs = set(feedback_by_pair)
        stalled_feedback: dict[str, tuple[ValidationFeedback, int]] = {}
        for pair, item_feedback in feedback_by_pair.items():
            count = stall_counts.get(pair, 0) + 1 if pair in previous_issue_pairs else 1
            stall_counts[pair] = count
            if config.revision_stall_threshold > 0 and count >= config.revision_stall_threshold:
                stalled_feedback[item_feedback.target_id] = (item_feedback, count)
        previous_issue_pairs = current_issue_pairs
        if stalled_feedback:
            stalled_ids = set(stalled_feedback)
            for target_id, (item_feedback, count) in stalled_feedback.items():
                accepted_item, audit_entry = _degraded_acceptance_entry(
                    stage=stage,
                    item=item_by_id.get(target_id, item_feedback.original_item),
                    reason="revision_not_converged",
                    round_index=round_index,
                    feedback=item_feedback,
                    detail=f"same issue persisted for {count} validation rounds",
                )
                audit_entry["consecutive_rounds"] = count
                accepted.append(accepted_item)
                degraded_accepted.append(audit_entry)
            audit["rounds"].append(
                {
                    "round": round_index,
                    "status": "degraded_accepted",
                    "reason": "revision_not_converged",
                    "target_ids": sorted(stalled_ids),
                    "issue_types": sorted({item.issue_type for item, _count in stalled_feedback.values()}),
                    "stall_threshold": config.revision_stall_threshold,
                    "degraded_accepted_count": len(stalled_ids),
                }
            )
            feedback = [item for item in feedback if item.target_id not in stalled_ids]
            failed_ids = {item.target_id for item in feedback}
        if round_index >= config.max_revision_rounds:
            feedback_by_target = {item.target_id: item for item in feedback}
            for item in items:
                target_id = str(item.get(id_key, ""))
                if target_id in failed_ids:
                    accepted_item, audit_entry = _degraded_acceptance_entry(
                        stage=stage,
                        item=item,
                        reason="verify_not_converged",
                        round_index=round_index,
                        feedback=feedback_by_target.get(target_id),
                        detail="maximum revision rounds reached",
                    )
                    accepted.append(accepted_item)
                    degraded_accepted.append(audit_entry)
            accepted.extend([item for item in items if item.get(id_key) not in failed_ids and item.get(id_key) not in stalled_feedback])
            break
        accepted.extend([item for item in items if item.get(id_key) not in failed_ids and item.get(id_key) not in stalled_feedback])
        if not feedback:
            break
        revision_contexts = _build_revision_contexts(
            feedback=feedback,
            contexts=contexts,
            window_size=config.revision_context_window,
        )
        current_package = rerun_callback(feedback, round_index + 1, revision_contexts, temp_package)
        pending_ids = failed_ids
    return _accepted_package(stage, initial_package, accepted, rejected, degraded_accepted), audit


def run_pipeline(config: KgExtractionRunConfig) -> dict[str, Any]:
    """Run the full KG Extraction MAS pipeline.

    Args:
        config: Run configuration.

    Returns:
        Final run manifest summary.

    Raises:
        ValueError: If inputs are invalid.
    """

    global CURRENT_RUN_PATHS
    reset_usage()
    run_id = config.run_id or make_run_id("kg_mock" if config.mock else "kg_real")
    paths = (
        _prepare_resumable_run_tree(run_id, work_root=config.work_root, output_root=config.output_root)
        if config.resume
        else prepare_run_tree(run_id, work_root=config.work_root, output_root=config.output_root)
    )
    CURRENT_RUN_PATHS = paths
    schema = load_published_schema(config.schema_path)
    standards = _standards_with_runtime_schema(load_standards(config.standards_dir), config.schema_path)
    original_contexts = build_section_contexts(config.enhanced_md_paths, config.sections_index_path)
    contexts = _filter_source_contexts(original_contexts, config.source_context_ids or [])
    contexts = split_oversized_section_contexts(contexts, section_char_limit=config.section_char_limit)
    write_json(paths["work_dir"] / "inputs" / "section_contexts.json", [context.to_json() for context in contexts])
    write_json(paths["work_dir"] / "inputs" / "standards_manifest.json", [{k: v for k, v in item.items() if k != "content"} for item in standards])

    node_packages: list[dict[str, Any]] = []
    skipped_node_batches: list[dict[str, Any]] = []
    skipped_node_reruns: list[dict[str, Any]] = []
    resumed_node_batches: list[str] = []
    node_context_batches = _context_batches(contexts, config.node_batch_size)
    for batch_index, context_batch in enumerate(node_context_batches, start=1):
        batch_id = f"node_batch_{batch_index:03d}"
        checkpoint_package = _load_batch_checkpoint(
            paths=paths,
            stage="node",
            batch_index=batch_index,
            context_batch=context_batch,
            resume=config.resume,
        )
        if checkpoint_package is not None:
            resumed_node_batches.append(batch_id)
            node_packages.append(checkpoint_package)
            skipped_node_batches.extend(_skipped_records(checkpoint_package.get("degraded_retry_skipped_batches")))
            continue
        step(f"节点抽取 batch [{batch_index}/{len(node_context_batches)}]")
        node_prompt = build_nea_prompt(contexts=context_batch, schema=schema, standards=standards)
        prompt_name = "node_prompt.json" if batch_index == 1 else f"node_prompt_batch_{batch_index:03d}.json"
        raw_name = "node_raw_response.txt" if batch_index == 1 else f"node_raw_response_batch_{batch_index:03d}.txt"
        prompt_path = paths["node"] / "prompts" / prompt_name
        raw_path = paths["node"] / "responses" / raw_name
        write_json(prompt_path, node_prompt)
        try:
            package, node_raw, skipped_batch = _run_nea_with_empty_content_retry(
                prompt=node_prompt,
                config=config,
                prompt_path=prompt_path,
                raw_response_path=raw_path,
                batch_id=batch_id,
                context_batch=context_batch,
            )
        except ExtractionModelCallError as exc:
            raw_path.write_text(exc.raw_response, encoding="utf-8")
            _write_failure_outputs(paths=paths, run_id=run_id, config=config, failed_stage="node", error=exc, raw_response_path=raw_path)
            raise
        except ExtractionModelNotConfiguredError as exc:
            _write_failure_outputs(paths=paths, run_id=run_id, config=config, failed_stage="node", error=exc, raw_response_path=raw_path)
            raise
        if skipped_batch:
            skipped_node_batches.extend(_skipped_records(skipped_batch))
        if skipped_batch and package is None:
            continue
        assert package is not None
        raw_path.write_text(node_raw, encoding="utf-8")
        node_packages.append(package)
        _write_batch_checkpoint(
            paths=paths,
            stage="node",
            batch_index=batch_index,
            batch_id=batch_id,
            context_batch=context_batch,
            package=package,
        )
    node_candidates = _merge_node_packages(node_packages, run_id=Path(paths["output_dir"]).name, mock=config.mock)
    write_json(paths["node"] / "node_candidates.json", node_candidates)

    def rerun_nodes(
        feedback: Sequence[ValidationFeedback],
        revision_round: int,
        rerun_contexts: Sequence[ExtractionSectionContext],
        fallback_package: dict[str, Any],
    ) -> dict[str, Any]:
        prompt = build_nea_prompt(contexts=rerun_contexts, schema=schema, standards=standards, feedback=feedback)
        context_suffix = _safe_prompt_context_suffix(rerun_contexts)
        prompt_path = paths["node"] / "prompts" / f"node_revision_{revision_round:02d}_{context_suffix}.json"
        raw_path = paths["node"] / "responses" / f"node_revision_{revision_round:02d}_{context_suffix}.txt"
        write_json(prompt_path, prompt)
        try:
            package, raw, skipped_rerun = _run_nea_with_empty_content_retry(
                prompt=prompt,
                config=config,
                prompt_path=prompt_path,
                raw_response_path=raw_path,
                batch_id=f"node_revision_{revision_round:02d}",
                context_batch=rerun_contexts,
                allow_timeout_degraded_retry=False,
            )
        except ExtractionModelCallError as exc:
            raw_path.write_text(exc.raw_response, encoding="utf-8")
            _write_failure_outputs(paths=paths, run_id=run_id, config=config, failed_stage="node", error=exc, raw_response_path=raw_path)
            raise
        except ExtractionModelNotConfiguredError as exc:
            _write_failure_outputs(paths=paths, run_id=run_id, config=config, failed_stage="node", error=exc, raw_response_path=raw_path)
            raise
        if skipped_rerun:
            target_ids = {item.target_id for item in feedback}
            if isinstance(skipped_rerun, dict):
                skipped_rerun["target_ids"] = sorted(target_ids)
                skipped_rerun["revision_round"] = revision_round
            skipped_node_reruns.append(skipped_rerun)
            empty_package = _empty_extraction_package("node", run_id=f"node_revision_{revision_round:02d}_empty_content", mock=config.mock)
            empty_package["degraded_revision"] = skipped_rerun
            empty_package["degraded_revision_items"] = [
                item for item in fallback_package.get("nodes", []) if str(item.get("node_id", "")) in target_ids
            ]
            return empty_package
        assert package is not None
        for node in package.get("nodes", []):
            node["revision_round"] = revision_round
        raw_path.write_text(raw, encoding="utf-8")
        return package

    node_validation_packages: list[dict[str, Any]] = []
    node_validation_audits: list[dict[str, Any]] = []
    for context_batch in _context_batches(contexts, config.node_batch_size):
        local_node_candidates = _candidate_package_for_contexts(
            stage="node",
            candidate_package=node_candidates,
            contexts=context_batch,
        )
        local_node_pack, local_node_validation_audit = validate_with_revision_loop(
            stage="node",
            initial_package=local_node_candidates,
            rerun_callback=rerun_nodes,
            schema=schema,
            contexts=context_batch,
            node_pack=None,
            standards=standards,
            config=config,
        )
        node_validation_packages.append(local_node_pack)
        node_validation_audits.append(local_node_validation_audit)
    node_pack = _merge_validation_packages(stage="node", base_package=node_candidates, packages=node_validation_packages)
    node_validation_audit = _merge_validation_audits(stage="node", audits=node_validation_audits)
    node_figure_audit = backfill_figure_ids(stage="node", package=node_pack, contexts=contexts)
    node_validation_audit["figure_refs"] = node_figure_audit
    write_json(paths["node"] / "node_pack.json", node_pack)
    write_json(paths["validation"] / "node_validation_audit.json", node_validation_audit)
    write_json(paths["validation"] / "node_figure_ref_audit.json", node_figure_audit)

    edge_packages: list[dict[str, Any]] = []
    skipped_edge_batches: list[dict[str, Any]] = []
    skipped_edge_reruns: list[dict[str, Any]] = []
    resumed_edge_batches: list[str] = []
    edge_context_batches = _context_batches(contexts, config.edge_batch_size)
    for batch_index, context_batch in enumerate(edge_context_batches, start=1):
        batch_id = f"edge_batch_{batch_index:03d}"
        checkpoint_package = _load_batch_checkpoint(
            paths=paths,
            stage="edge",
            batch_index=batch_index,
            context_batch=context_batch,
            resume=config.resume,
        )
        if checkpoint_package is not None:
            resumed_edge_batches.append(batch_id)
            edge_packages.append(checkpoint_package)
            skipped_edge_batches.extend(_skipped_records(checkpoint_package.get("degraded_retry_skipped_batches")))
            continue
        step(f"边抽取 batch [{batch_index}/{len(edge_context_batches)}]")
        local_node_pack = _node_pack_for_contexts(node_pack, context_batch)
        edge_prompt = build_eea_prompt(contexts=context_batch, node_pack=local_node_pack, schema=schema, standards=standards)
        prompt_name = "edge_prompt.json" if batch_index == 1 else f"edge_prompt_batch_{batch_index:03d}.json"
        raw_name = "edge_raw_response.txt" if batch_index == 1 else f"edge_raw_response_batch_{batch_index:03d}.txt"
        prompt_path = paths["edge"] / "prompts" / prompt_name
        write_json(prompt_path, edge_prompt)
        edge_raw_path = paths["edge"] / "responses" / raw_name
        try:
            edge_package, edge_raw, skipped_batch = _run_eea_with_empty_content_retry(
                prompt=edge_prompt,
                config=config,
                prompt_path=prompt_path,
                raw_response_path=edge_raw_path,
                batch_id=batch_id,
                context_batch=context_batch,
            )
        except ExtractionModelCallError as exc:
            edge_raw_path.write_text(exc.raw_response, encoding="utf-8")
            _write_failure_outputs(paths=paths, run_id=run_id, config=config, failed_stage="edge", error=exc, raw_response_path=edge_raw_path)
            raise
        except ExtractionModelNotConfiguredError as exc:
            _write_failure_outputs(paths=paths, run_id=run_id, config=config, failed_stage="edge", error=exc, raw_response_path=edge_raw_path)
            raise
        if skipped_batch:
            skipped_edge_batches.extend(_skipped_records(skipped_batch))
        if skipped_batch and edge_package is None:
            continue
        assert edge_package is not None
        edge_raw_path.write_text(edge_raw, encoding="utf-8")
        edge_packages.append(edge_package)
        _write_batch_checkpoint(
            paths=paths,
            stage="edge",
            batch_index=batch_index,
            batch_id=batch_id,
            context_batch=context_batch,
            package=edge_package,
        )
    edge_candidates = _merge_edge_packages(edge_packages, run_id=Path(paths["output_dir"]).name, mock=config.mock)
    structural_edges = _synthesize_structural_edges(node_pack=node_pack, edge_pack=edge_candidates, schema=schema)
    if structural_edges:
        edge_candidates["edges"].extend(structural_edges)
        edge_candidates["deterministic_structural_edges"] = len(structural_edges)
    write_json(paths["edge"] / "edge_candidates.json", edge_candidates)

    def rerun_edges(
        feedback: Sequence[ValidationFeedback],
        revision_round: int,
        rerun_contexts: Sequence[ExtractionSectionContext],
        fallback_package: dict[str, Any],
    ) -> dict[str, Any]:
        local_node_pack = _node_pack_for_contexts(node_pack, rerun_contexts)
        prompt = build_eea_prompt(
            contexts=rerun_contexts,
            node_pack=local_node_pack,
            schema=schema,
            standards=standards,
            feedback=feedback,
        )
        context_suffix = _safe_prompt_context_suffix(rerun_contexts)
        prompt_path = paths["edge"] / "prompts" / f"edge_revision_{revision_round:02d}_{context_suffix}.json"
        raw_path = paths["edge"] / "responses" / f"edge_revision_{revision_round:02d}_{context_suffix}.txt"
        write_json(prompt_path, prompt)
        try:
            package, raw, skipped_rerun = _run_eea_with_empty_content_retry(
                prompt=prompt,
                config=config,
                prompt_path=prompt_path,
                raw_response_path=raw_path,
                batch_id=f"edge_revision_{revision_round:02d}",
                context_batch=rerun_contexts,
                allow_timeout_degraded_retry=False,
            )
        except ExtractionModelCallError as exc:
            raw_path.write_text(exc.raw_response, encoding="utf-8")
            _write_failure_outputs(paths=paths, run_id=run_id, config=config, failed_stage="edge", error=exc, raw_response_path=raw_path)
            raise
        except ExtractionModelNotConfiguredError as exc:
            _write_failure_outputs(paths=paths, run_id=run_id, config=config, failed_stage="edge", error=exc, raw_response_path=raw_path)
            raise
        if skipped_rerun:
            target_ids = {item.target_id for item in feedback}
            if isinstance(skipped_rerun, dict):
                skipped_rerun["target_ids"] = sorted(target_ids)
                skipped_rerun["revision_round"] = revision_round
            skipped_edge_reruns.append(skipped_rerun)
            empty_package = _empty_extraction_package("edge", run_id=f"edge_revision_{revision_round:02d}_empty_content", mock=config.mock)
            empty_package["degraded_revision"] = skipped_rerun
            empty_package["degraded_revision_items"] = [
                item for item in fallback_package.get("edges", []) if str(item.get("edge_id", "")) in target_ids
            ]
            return empty_package
        assert package is not None
        for edge in package.get("edges", []):
            edge["revision_round"] = revision_round
        raw_path.write_text(raw, encoding="utf-8")
        return package

    edge_validation_packages: list[dict[str, Any]] = []
    edge_validation_audits: list[dict[str, Any]] = []
    for context_batch in _context_batches(contexts, config.edge_batch_size):
        local_edge_candidates = _candidate_package_for_contexts(
            stage="edge",
            candidate_package=edge_candidates,
            contexts=context_batch,
        )
        local_node_pack = _node_pack_for_contexts(node_pack, context_batch)
        local_edge_pack, local_edge_validation_audit = validate_with_revision_loop(
            stage="edge",
            initial_package=local_edge_candidates,
            rerun_callback=rerun_edges,
            schema=schema,
            contexts=context_batch,
            node_pack=local_node_pack,
            standards=standards,
            config=config,
        )
        edge_validation_packages.append(local_edge_pack)
        edge_validation_audits.append(local_edge_validation_audit)
    edge_pack = _merge_validation_packages(stage="edge", base_package=edge_candidates, packages=edge_validation_packages)
    edge_validation_audit = _merge_validation_audits(stage="edge", audits=edge_validation_audits)
    edge_figure_audit = backfill_figure_ids(stage="edge", package=edge_pack, contexts=contexts)
    edge_validation_audit["figure_refs"] = edge_figure_audit
    write_json(paths["edge"] / "edge_pack.json", edge_pack)
    write_json(paths["validation"] / "edge_validation_audit.json", edge_validation_audit)
    write_json(paths["validation"] / "edge_figure_ref_audit.json", edge_figure_audit)

    standard_raw_path = paths["standard"] / "responses" / "standard_raw_response.txt"
    sda_raw = json.dumps(
        {
            "schema_version": "kg.standard_agent.v1",
            "mode": "deterministic_local_standardization",
            "reason": "Final merged_nodes, merged_edges, and triples are generated locally from VA-approved node and edge packs.",
        },
        ensure_ascii=False,
        indent=2,
    )
    standard_raw_path.write_text(sda_raw, encoding="utf-8")
    standardized = standardize_kg(node_pack=node_pack, edge_pack=edge_pack, schema=schema, contexts=contexts, run_id=Path(paths["output_dir"]).name)
    graph_count_stats = _graph_count_stats(
        merged_nodes=standardized["merged_nodes"],
        merged_edges=standardized["merged_edges"],
    )
    write_json(paths["final_standard"] / "merged_nodes.json", standardized["merged_nodes"])
    write_json(paths["final_standard"] / "merged_edges.json", standardized["merged_edges"])
    write_json(paths["final_standard"] / "triples.json", standardized["triples"])
    write_json(paths["standard"] / "audit" / "standard_audit.json", standardized["audit"])
    timeout_events = _collect_timeout_events(
        skipped_node_batches=skipped_node_batches,
        skipped_edge_batches=skipped_edge_batches,
        skipped_node_reruns=skipped_node_reruns,
        skipped_edge_reruns=skipped_edge_reruns,
        node_pack=node_pack,
        edge_pack=edge_pack,
    )
    manifest_status, degraded_reason = _manifest_status_from_degradation(
        timeout_events=timeout_events,
        skipped_node_batches=skipped_node_batches,
        skipped_edge_batches=skipped_edge_batches,
    )
    figure_ref_audit = {
        "node": node_figure_audit,
        "edge": edge_figure_audit,
        "untraceable_count": node_figure_audit["untraceable_count"] + edge_figure_audit["untraceable_count"],
    }
    degraded_accepted_counts = _degraded_accepted_counts(node_pack=node_pack, edge_pack=edge_pack)

    manifest = {
        "schema_version": "kg.extraction_manifest.v1",
        "status": manifest_status,
        "degraded_reason": degraded_reason,
        "run_id": Path(paths["output_dir"]).name,
        "mock": config.mock,
        "models": {"node": config.node_model, "edge": config.edge_model, "standard": config.standard_model, "validation": config.validation_model},
        "work_dir": str(paths["work_dir"]),
        "output_dir": str(paths["output_dir"]),
        "enhanced_md": [str(path.resolve()) for path in config.enhanced_md_paths],
        "sections_index": str(config.sections_index_path.resolve()),
        "standards": [{k: v for k, v in item.items() if k != "content"} for item in standards],
        "accepted_nodes": len(node_pack.get("nodes", [])),
        "accepted_edges": len(edge_pack.get("edges", [])),
        "degraded_accepted_nodes": degraded_accepted_counts["nodes"],
        "degraded_accepted_edges": degraded_accepted_counts["edges"],
        "counted_nodes": graph_count_stats["nodes_counted"],
        "counted_edges": graph_count_stats["edges_counted"],
        "structural_nodes": graph_count_stats["nodes_structural"],
        "structural_edges": graph_count_stats["edges_structural"],
        "count_policy": graph_count_stats["count_policy"],
        "triples": len(standardized["triples"].get("triples", [])),
        "skipped_node_batches": skipped_node_batches,
        "skipped_edge_batches": skipped_edge_batches,
        "skipped_node_reruns": skipped_node_reruns,
        "skipped_edge_reruns": skipped_edge_reruns,
        "resumed_node_batches": resumed_node_batches,
        "resumed_edge_batches": resumed_edge_batches,
        "timeout_events": timeout_events,
        "va_rejection": _va_rejection_stats(node_pack=node_pack, edge_pack=edge_pack),
        "va_revision_round_counts": _va_revision_round_counts(node_pack=node_pack, edge_pack=edge_pack),
        "figure_ref_audit": figure_ref_audit,
        "figure_stats": _figure_stats(
            merged_nodes=standardized["merged_nodes"],
            merged_edges=standardized["merged_edges"],
            contexts=contexts,
            figure_ref_audit=figure_ref_audit,
        ),
        "avg_confidence": _avg_confidence(
            merged_nodes=standardized["merged_nodes"],
            merged_edges=standardized["merged_edges"],
        ),
        "standard_outputs": {
            "merged_nodes": str(paths["final_standard"] / "merged_nodes.json"),
            "merged_edges": str(paths["final_standard"] / "merged_edges.json"),
            "triples": str(paths["final_standard"] / "triples.json"),
        },
        "token_usage": usage_snapshot(),
    }
    write_json(paths["output_dir"] / "kg_extraction_manifest.json", manifest)
    write_report(
        paths["output_dir"] / "kg_extraction_report.md",
        "KG Extraction Report",
        [
            f"- run_id: `{manifest['run_id']}`",
            f"- mock: `{manifest['mock']}`",
            f"- accepted_nodes: `{manifest['accepted_nodes']}`",
            f"- accepted_edges: `{manifest['accepted_edges']}`",
            f"- degraded_accepted_nodes: `{manifest['degraded_accepted_nodes']}`",
            f"- degraded_accepted_edges: `{manifest['degraded_accepted_edges']}`",
            f"- counted_nodes: `{manifest['counted_nodes']}`",
            f"- counted_edges: `{manifest['counted_edges']}`",
            f"- structural_nodes: `{manifest['structural_nodes']}`",
            f"- structural_edges: `{manifest['structural_edges']}`",
            f"- triples: `{manifest['triples']}`",
            f"- timeout_events: `{len(timeout_events)}`",
            f"- timeout_skipped_or_rejected_blocks: `{len(timeout_events)}`",
            "- final output format: `merged_nodes.json`, `merged_edges.json`, `triples.json`.",
        ],
    )
    write_json(paths["work_dir"] / "manifest.json", manifest)
    return jsonable(manifest)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entrypoint.

    Args:
        argv: Optional CLI argv list.

    Returns:
        Process exit code.
    """

    config = config_from_args(parse_args(argv))
    manifest = run_pipeline(config)
    print(manifest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
