"""CLI and orchestration for IPA v1."""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime
import functools
import hashlib
import inspect
import json
import os
import pickle
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Any, Sequence
from unittest.mock import Mock

import yaml

from mas.common.progress import step
from mas.config.models import get_model
from mas.pipelines.common.usage_tracker import usage_snapshot
from mas.pipelines.common.qwen_vl_provider import QwenVLProviderError
from mas.utils.io import write_json

from .context_builder import build_image_context
from .image_reference import resolve_image_reference
from .ipa_agent import ModelNotConfiguredError, process_batch, process_textualization, process_verification
from .logger import JSONLRecord, JsonlLogger, utc_timestamp
from .markdown_enhancer import enhance_markdown
from .markdown_parser import SectionMarkdown, load_section_markdown, parse_markdown
from .output_auditor import (
    ImageTag,
    TextualizationResult,
    audit_round1_json,
    audit_round2_json,
    audit_verify_json,
    distill_verification_feedback,
)
from .prompt_builder import PROMPT_DIR, build_round1_prompt, build_round2_prompt, build_verify_prompt, load_taxonomy


def make_run_id(mock: bool, label: str | None = None, now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    prefix = "ipa_mock" if mock else "ipa_real"
    suffix = f"_{label}" if label else ""
    return f"{prefix}_{stamp}{suffix}"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Image Processing Agent v1.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--input-md", default=None, help="Single section Markdown file.")
    group.add_argument("--sections-dir", default=None, help="markdown_segmenter sections/ directory.")
    parser.add_argument("--sections-index", default=None, help="Optional sections_index.json.")
    parser.add_argument("--image-source-dir", default=None, help="Optional source images directory to snapshot into run inputs.")
    parser.add_argument("--source-pdf", default=None, help="Optional source PDF path recorded in IPA image trace audit.")
    parser.add_argument(
        "--output-root",
        default=str(Path("code_implement") / "data" / "intermediate" / "ipa_outputs"),
        help="IPA output root.",
    )
    parser.add_argument("--config", default=None, help="Optional YAML config path.")
    parser.add_argument("--mock", action="store_true", default=None, help="Enable mock model mode.")
    parser.add_argument("--no-mock", action="store_false", dest="mock", help="Disable mock model mode.")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=20,
        help="Deprecated; round1 now always runs one image at a time and ignores this value.",
    )
    parser.add_argument("--run-id", default=None, help="Optional run id label appended after timestamp.")
    parser.add_argument("--taxonomy", default=None, help="Optional image_taxonomy selected_image_taxonomy.json.")
    parser.add_argument("--no-ipa-resume", action="store_true", help="禁用 per-image checkpoint resume,默认启用")
    parser.add_argument(
        "--per-image-hard-timeout-seconds",
        type=int,
        default=600,
        help="单图 round2 处理硬总时长上限,超过即跳过该图",
    )
    return parser.parse_args(argv)


def load_ipa_config(config_path: str | Path | None) -> dict[str, Any]:
    if not config_path:
        return {}
    path = Path(config_path)
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data.get("ipa", data)


def resolve_mock(cli_mock: bool | None, config: dict[str, Any]) -> bool:
    if cli_mock is not None:
        return bool(cli_mock)
    return bool(config.get("mock", False))


def _load_sections_index(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def discover_section_inputs(
    *,
    sections_dir: Path | None,
    sections_index: Path | None,
    input_md: Path | None,
) -> list[SectionMarkdown]:
    if input_md is not None:
        return [load_section_markdown(Path(input_md), {"order": 1, "title": Path(input_md).stem})]
    if sections_dir is None:
        raise ValueError("sections_dir or input_md is required")
    sections_dir = Path(sections_dir).resolve()
    index_path = Path(sections_index).resolve() if sections_index else sections_dir.parent / "sections_index.json"
    index = _load_sections_index(index_path)
    textbook = str(index.get("textbook", ""))
    sections: list[SectionMarkdown] = []

    indexed_items = index.get("sections") if isinstance(index.get("sections"), list) else None
    if indexed_items:
        for item in indexed_items:
            file_name = item.get("file")
            if not file_name:
                continue
            md_path = sections_dir / str(file_name)
            if not md_path.exists():
                raise FileNotFoundError(f"section listed in index is missing: {md_path}")
            metadata = dict(item)
            metadata["title"] = item.get("chapter_title") or item.get("section_title") or md_path.stem
            metadata["textbook"] = textbook
            sections.append(load_section_markdown(md_path, metadata))
        return sections

    for order, md_path in enumerate(sorted(sections_dir.glob("*.md")), start=1):
        sections.append(load_section_markdown(md_path, {"order": order, "title": md_path.stem, "textbook": textbook}))
    return sections


def _unique_run_dir(output_root: Path, run_id: str) -> Path:
    output_root.mkdir(parents=True, exist_ok=True)
    candidate = output_root / run_id
    if not candidate.exists():
        return candidate
    suffix = 2
    while True:
        alternate = output_root / f"{run_id}_{suffix}"
        if not alternate.exists():
            return alternate
        suffix += 1


def copy_inputs_to_run(
    *,
    sections: list[SectionMarkdown],
    run_dir: Path,
    sections_index: Path | None,
    image_source_dir: Path | None,
) -> tuple[Path, int]:
    snapshot_sections = run_dir / "inputs" / "sections"
    snapshot_sections.mkdir(parents=True, exist_ok=True)
    for section in sections:
        shutil.copy2(section.path, snapshot_sections / section.path.name)
    if sections_index and Path(sections_index).exists():
        shutil.copy2(sections_index, run_dir / "inputs" / "sections_index.json")
    mirrored_count = 0
    image_target = snapshot_sections / "images"
    for section in sections:
        sibling_images = section.path.parent / "images"
        if sibling_images.exists() and sibling_images.is_dir():
            image_target.mkdir(parents=True, exist_ok=True)
            for image in sibling_images.iterdir():
                if image.is_file():
                    shutil.copy2(image, image_target / image.name)
    if image_source_dir and Path(image_source_dir).exists():
        image_target.mkdir(parents=True, exist_ok=True)
        for image in Path(image_source_dir).iterdir():
            if image.is_file():
                target = image_target / image.name
                if not target.exists():
                    shutil.copy2(image, target)
                mirrored_count += 1
        mirror_target = run_dir / "inputs" / "images"
        if not mirror_target.exists():
            mirror_target.mkdir(parents=True, exist_ok=True)
        for image in Path(image_source_dir).iterdir():
            if image.is_file():
                shutil.copy2(image, mirror_target / image.name)
    return snapshot_sections, mirrored_count


def _copy_preview_images(images_src: Path, enhanced_images: Path) -> int:
    if not images_src.exists() or not images_src.is_dir():
        return 0
    enhanced_images.mkdir(parents=True, exist_ok=True)
    copied = 0
    for image in images_src.iterdir():
        if not image.is_file():
            continue
        try:
            shutil.copy2(image, enhanced_images / image.name)
        except OSError as exc:
            print(f"[WARN] IPA preview image copy skipped for {image.name}: {exc}", file=os.sys.stderr)
            continue
        copied += 1
    return copied


def _tag_to_json(tag: ImageTag) -> dict[str, Any]:
    return asdict(tag)


def _textualization_to_json(result: TextualizationResult) -> dict[str, Any]:
    return asdict(result)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


IMAGE_FILE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MEDIUM_OUTPUT_MODE_HINT = (
    "For kg_value=medium, produce short_name and short_description only. "
    "Do not output markdown_text; this is a lightweight visual description for FigureRef traceability."
)


def _stable_figure_id(*parts: Any) -> str:
    text = "\n".join(str(part or "") for part in parts)
    return "fig_" + hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _source_page_from_name(name: str) -> int | None:
    match = re.search(r"page(\d+)", str(name), flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _result_description(result: TextualizationResult | None) -> str:
    if result is None:
        return ""
    if result.markdown_text.strip():
        return result.markdown_text.strip()
    parts = [result.short_name.strip(), result.short_description.strip()]
    return "：".join(part for part in parts if part)


def _verification_issues(audit: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(audit, dict):
        return []
    issues: list[dict[str, Any]] = []
    for item in audit.get("verdict_history", []):
        if not isinstance(item, dict):
            continue
        for issue in item.get("issues", []):
            if isinstance(issue, dict):
                issues.append(dict(issue))
    return issues


def _processing_plan(tag: ImageTag) -> str:
    if tag.audit_status != "passed":
        return "uncertain_fallback" if tag.kg_value == "uncertain" else "trace_only"
    if tag.kg_value == "high":
        return "full_round2"
    if tag.kg_value == "medium":
        return "lightweight_description"
    if tag.kg_value == "uncertain":
        return "uncertain_fallback"
    return "trace_only"


def _make_uncertain_fallback(
    *,
    tag: ImageTag,
    image: Any,
    resolved: Any,
    context: Any,
) -> TextualizationResult:
    heading = str(getattr(context, "nearest_heading", "") or getattr(context, "section_title", "") or "").strip()
    alt_text = str(getattr(image, "alt_text", "") or "").strip()
    file_name = str(getattr(resolved, "file_name", "") or Path(str(getattr(resolved, "resolved_path", ""))).name)
    basis = f"邻近标题：{heading}" if heading else f"文件名：{file_name}"
    if alt_text:
        basis = f"alt：{alt_text}；{basis}"
    return TextualizationResult(
        image_id=tag.image_id,
        can_textualize=False,
        markdown_text="",
        short_name="待复核图片",
        short_description=f"IPA 未能可靠判断该图像价值，保留原图链接与上下文供复核（{basis}）。",
        uncertainty="uncertain fallback generated without deep visual textualization",
        audit_status="passed",
        processing_status="fallback_uncertain",
        fallback_reason=tag.error or tag.reason or "kg_value=uncertain",
    )


def _trace_record_for_visible_image(
    *,
    image: Any,
    resolved: Any,
    context: Any,
    tag: ImageTag | None,
    result: TextualizationResult | None,
    critic_audit: dict[str, Any] | None,
    source_pdf: Path | None,
    final_note_written: bool,
) -> dict[str, Any]:
    image_path = str(getattr(resolved, "resolved_path", ""))
    figure_id = _stable_figure_id(source_pdf or "", getattr(image, "image_id", ""), image_path, getattr(image, "raw_link", ""))
    kg_value = str(getattr(tag, "kg_value", "unknown") if tag else "unknown")
    if result is not None:
        processing_status = result.processing_status or result.audit_status
    elif tag is None:
        processing_status = "classification_missing"
    elif not getattr(resolved, "exists", False):
        processing_status = "missing_image_file"
    elif tag.kg_value == "low":
        processing_status = "skipped_low"
    elif tag.kg_value == "uncertain":
        processing_status = "fallback_missing"
    else:
        processing_status = "trace_only"
    return {
        "schema_version": "ipa.image_trace_audit.v1",
        "image_id": getattr(image, "image_id", ""),
        "figure_id": figure_id,
        "image_path": image_path,
        "raw_link": getattr(image, "raw_link", ""),
        "source_pdf": str(Path(source_pdf).resolve()) if source_pdf else "",
        "source_page": _source_page_from_name(getattr(resolved, "file_name", "") or getattr(image, "raw_link", "")),
        "source_section_id": f"s{getattr(image, 'section_order', 0):03d}" if getattr(image, "section_order", None) else "",
        "source_section_title": str(getattr(context, "section_title", "")),
        "source_markdown_file": Path(str(getattr(resolved, "markdown_file", ""))).name,
        "source_markdown_path": str(getattr(resolved, "markdown_file", "")),
        "nearest_heading": str(getattr(context, "nearest_heading", "")),
        "image_exists": bool(getattr(resolved, "exists", False)),
        "kg_value": kg_value,
        "image_type_id": str(getattr(tag, "image_type_id", "unknown") if tag else "unknown"),
        "round1_status": str(getattr(tag, "audit_status", "missing") if tag else "missing"),
        "round1_reason": str(getattr(tag, "reason", "") if tag else ""),
        "round2_status": str(getattr(result, "audit_status", "not_run") if result else "not_run"),
        "processing_status": processing_status,
        "skip_reason": str(getattr(result, "skip_reason", "") if result else ("kg_value=low; trace only" if tag and tag.kg_value == "low" else "")),
        "fallback_reason": str(getattr(result, "fallback_reason", "") if result else ""),
        "degraded_reason": str(getattr(result, "degraded_reason", "") if result else ""),
        "verifier_issues": _verification_issues(critic_audit),
        "final_candidate_description": _result_description(result),
        "final_candidate_description_present": bool(_result_description(result).strip()),
        "final_ipa_note_written": bool(final_note_written),
    }


def _trace_records_for_unreferenced_source_images(
    *,
    image_source_dir: Path | None,
    referenced_file_names: set[str],
    source_pdf: Path | None,
) -> list[dict[str, Any]]:
    if image_source_dir is None or not Path(image_source_dir).exists():
        return []
    records: list[dict[str, Any]] = []
    for path in sorted(Path(image_source_dir).iterdir()):
        if not path.is_file() or path.suffix.lower() not in IMAGE_FILE_SUFFIXES:
            continue
        if path.name in referenced_file_names:
            continue
        image_id = "unreferenced_" + hashlib.sha1(str(path.resolve()).encode("utf-8")).hexdigest()[:12]
        records.append(
            {
                "schema_version": "ipa.image_trace_audit.v1",
                "image_id": image_id,
                "figure_id": _stable_figure_id(source_pdf or "", path.resolve()),
                "image_path": str(path.resolve()),
                "raw_link": "",
                "source_pdf": str(Path(source_pdf).resolve()) if source_pdf else "",
                "source_page": _source_page_from_name(path.name),
                "source_section_id": "",
                "source_section_title": "",
                "source_markdown_file": "",
                "source_markdown_path": "",
                "nearest_heading": "",
                "image_exists": True,
                "kg_value": "unknown",
                "image_type_id": "not_in_section_markdown",
                "round1_status": "not_seen_by_ipa",
                "round1_reason": "MinerU/PDF extracted image is not referenced in section Markdown.",
                "round2_status": "not_run",
                "processing_status": "not_in_section_markdown",
                "skip_reason": "not referenced by section Markdown; ITA/IPA did not receive this image.",
                "fallback_reason": "",
                "degraded_reason": "",
                "verifier_issues": [],
                "final_candidate_description": "",
                "final_candidate_description_present": False,
                "final_ipa_note_written": False,
            }
        )
    return records


def _write_trace_audit(run_dir: Path, records: list[dict[str, Any]]) -> None:
    write_json(run_dir / "audit" / "image_trace_audit.json", records)
    with (run_dir / "audit" / "image_trace_audit.jsonl").open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _write_round1_outputs(run_dir: Path, tags: dict[str, ImageTag]) -> None:
    write_json(run_dir / "round1_tags" / "image_tags.json", [_tag_to_json(tag) for tag in tags.values()])
    with (run_dir / "round1_tags" / "image_tags.jsonl").open("w", encoding="utf-8") as handle:
        for tag in tags.values():
            handle.write(json.dumps(_tag_to_json(tag), ensure_ascii=False) + "\n")


def _load_round1_tag_checkpoint(run_dir: Path, image_id: str) -> ImageTag | None:
    path = run_dir / "round1_tags" / "per_image" / f"{image_id}.json"
    if not path.exists():
        return None
    try:
        return ImageTag(**json.loads(path.read_text(encoding="utf-8")))
    except Exception:
        return None


def _write_round1_tag_checkpoint(run_dir: Path, tag: ImageTag) -> None:
    write_json(run_dir / "round1_tags" / "per_image" / f"{tag.image_id}.json", _tag_to_json(tag))


def _ipa_revision_round_counts(audits: Sequence[dict[str, Any]], *, max_rounds: int = 5) -> dict[str, Any]:
    by_rounds = {f"round_{index}": 0 for index in range(1, max(0, int(max_rounds)) + 1)}
    by_final_status = {"accepted": 0, "degraded": 0, "rejected": 0}
    for audit in audits:
        if not isinstance(audit, dict):
            continue
        try:
            rounds_used = int(audit.get("rounds_used", 0))
        except (TypeError, ValueError):
            rounds_used = 0
        round_key = f"round_{rounds_used}"
        if round_key in by_rounds:
            by_rounds[round_key] += 1
        final_status = str(audit.get("final_status", "") or "")
        if final_status in by_final_status:
            by_final_status[final_status] += 1
    return {"by_rounds": by_rounds, "by_final_status": by_final_status}


def _load_round2_progress(progress_path: Path) -> dict[str, dict[str, Any]]:
    completed: dict[str, dict[str, Any]] = {}
    if not progress_path.exists():
        return completed
    for line in progress_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except Exception:
            continue
        image_id = rec.get("image_id")
        if image_id:
            completed[str(image_id)] = rec
    return completed


def _round2_progress_status(result: TextualizationResult) -> str:
    if result.audit_status == "passed":
        return "ok"
    if "hard-timeout" in (result.uncertainty or ""):
        return "timeout"
    return "failed"


def _append_round2_progress(progress_path: Path, result: TextualizationResult) -> None:
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    with progress_path.open("a", encoding="utf-8") as fp:
        fp.write(
            json.dumps(
                {
                    "image_id": result.image_id,
                    "status": _round2_progress_status(result),
                    "result": _textualization_to_json(result),
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def _map_confidence(round_index: int, accepted: bool) -> float:
    """Heuristic consensus confidence, not a calibrated posterior probability."""
    if not accepted:
        return 0.2
    return max(0.5, 0.9 - 0.1 * max(0, round_index - 1))


def _critic_revision_audit_record(
    tag: ImageTag,
    history: list[dict[str, Any]],
    final_status: str,
    rounds_used: int,
) -> dict[str, Any]:
    verdict_history = [
        {"round": item.get("round"), "verdict": item.get("verdict", "revise"), "issues": item.get("issues", [])}
        for item in history
        if item.get("verdict") or item.get("issues")
    ]
    return {
        "image_id": tag.image_id,
        "final_status": final_status,
        "rounds_used": rounds_used,
        "verdict_history": verdict_history,
        "history": history,
    }


def _write_prompt_response(base_dir: Path, stem: str, prompt: Any | None = None, raw_response: str | None = None) -> None:
    base_dir.mkdir(parents=True, exist_ok=True)
    if prompt is not None:
        (base_dir / f"{stem}_prompt.json").write_text(json.dumps(asdict(prompt), ensure_ascii=False, indent=2), encoding="utf-8")
    if raw_response is not None:
        (base_dir / f"{stem}_response.txt").write_text(raw_response, encoding="utf-8")


def _round2_required(tag: ImageTag) -> bool:
    if tag.audit_status != "passed":
        return False
    if tag.kg_value in {"low", "uncertain"}:
        return False
    return bool(tag.is_valuable and tag.needs_round2 and (tag.can_textualize or tag.can_describe))


def run_critic_revision_for_image(
    *,
    image: Any,
    resolved: Any,
    context: Any,
    tag: ImageTag,
    mock: bool,
    gen_model_config: dict[str, Any] | None,
    verify_model_config: dict[str, Any] | None,
    max_rounds: int = 5,
    run_dir: Path,
    logger: JsonlLogger | None,
) -> tuple[TextualizationResult, dict[str, Any]]:
    """Run bounded G textualization and C verification for one valuable image."""
    feedback = ""
    history: list[dict[str, Any]] = []
    last_candidate: TextualizationResult | None = None
    cr_dir = Path(run_dir) / "round2_textualization" / "critic_revision" / tag.image_id
    max_rounds = max(1, int(max_rounds))

    for round_index in range(1, max_rounds + 1):
        g_prompt = build_round2_prompt(
            f"round2_{tag.image_id}_r{round_index}",
            image,
            resolved,
            context,
            tag,
            revision_feedback=feedback,
        )
        g_resp = process_textualization(g_prompt, tag, mock=mock, model_config=gen_model_config)
        _write_prompt_response(cr_dir, f"round_{round_index}_g", prompt=g_prompt, raw_response=g_resp.raw_response)
        try:
            candidate = audit_round2_json(g_resp.raw_response, tag.image_id, can_textualize=tag.can_textualize)
        except ValueError as exc:
            history.append({"round": round_index, "g_raw": g_resp.raw_response, "g_audit_error": str(exc)})
            feedback = "上轮输出非法JSON，请严格按schema输出，并只写图中确有内容。"
            continue
        last_candidate = candidate

        c_prompt = build_verify_prompt(
            f"verify_{tag.image_id}_r{round_index}",
            image,
            resolved,
            context,
            tag,
            candidate,
            round_index,
        )
        c_resp = process_verification(c_prompt, mock=mock, model_config=verify_model_config)
        _write_prompt_response(cr_dir, f"round_{round_index}_c", prompt=c_prompt, raw_response=c_resp.raw_response)
        try:
            verdict = audit_verify_json(c_resp.raw_response, tag.image_id)
        except ValueError as exc:
            history.append(
                {
                    "round": round_index,
                    "g_raw": g_resp.raw_response,
                    "c_raw": c_resp.raw_response,
                    "c_audit_error": str(exc),
                }
            )
            feedback = "核实方未给出有效判定，请保守重述图中确有内容，避免编造或复制上下文。"
            continue

        history.append(
            {
                "round": round_index,
                "g_raw": g_resp.raw_response,
                "c_raw": c_resp.raw_response,
                "verdict": verdict.verdict,
                "issues": verdict.issues,
            }
        )
        if verdict.verdict == "accept":
            candidate.uncertainty = (
                f"{candidate.uncertainty}; confidence_final={_map_confidence(round_index, accepted=True):.2f}"
                if candidate.uncertainty
                else f"confidence_final={_map_confidence(round_index, accepted=True):.2f}"
            )
            candidate.audit_status = "passed"
            candidate.processing_status = "accepted"
            return candidate, _critic_revision_audit_record(tag, history, "accepted", round_index)
        if round_index >= max_rounds - 1:
            candidate.uncertainty = (
                f"{candidate.uncertainty}; critic-not-converged; confidence_final={_map_confidence(round_index, accepted=False):.2f}"
                if candidate.uncertainty
                else f"critic-not-converged; confidence_final={_map_confidence(round_index, accepted=False):.2f}"
            )
            candidate.audit_status = "degraded"
            candidate.processing_status = "degraded"
            candidate.degraded_reason = "critic-not-converged"
            return candidate, _critic_revision_audit_record(tag, history, "degraded", round_index)
        feedback = distill_verification_feedback(verdict)

    if last_candidate is not None:
        last_candidate.uncertainty = (
            f"{last_candidate.uncertainty}; critic-not-converged; confidence_final={_map_confidence(max_rounds, accepted=False):.2f}"
            if last_candidate.uncertainty
            else f"critic-not-converged; confidence_final={_map_confidence(max_rounds, accepted=False):.2f}"
        )
        last_candidate.audit_status = "degraded"
        last_candidate.processing_status = "degraded"
        last_candidate.degraded_reason = "critic-not-converged"
        return last_candidate, _critic_revision_audit_record(tag, history, "degraded", max_rounds)

    rejected = TextualizationResult(
        image_id=tag.image_id,
        can_textualize=False,
        markdown_text="",
        short_name="未通过核实",
        short_description="经<=5轮核实仍未达成一致，保留原图链接",
        uncertainty=f"critic-revision not converged; confidence_final={_map_confidence(max_rounds, accepted=False):.2f}",
        audit_status="rejected",
        error="max_revision_rounds reached without accept",
        processing_status="rejected",
        degraded_reason="critic-revision not converged without usable candidate",
    )
    return rejected, _critic_revision_audit_record(tag, history, "rejected", max_rounds)


_HARD_TIMEOUT_GRACE_SECONDS = 5


def _hard_timeout_worker(payload_path: str, result_path: str) -> int:
    try:
        with Path(payload_path).open("rb") as handle:
            callable_no_args = pickle.load(handle)
        try:
            value = callable_no_args()
        except BaseException as exc:
            payload = {
                "kind": "exception",
                "exception": exc,
                "exception_type": type(exc).__name__,
                "message": str(exc),
                "traceback": traceback.format_exc(),
            }
        else:
            payload = {"kind": "result", "value": value}
        with Path(result_path).open("wb") as handle:
            pickle.dump(payload, handle)
        return 0
    except BaseException as exc:
        fallback = {
            "kind": "worker_error",
            "exception_type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        try:
            with Path(result_path).open("wb") as handle:
                pickle.dump(fallback, handle)
        except BaseException:
            pass
        return 1


def _popen_for_hard_timeout(payload_path: Path, result_path: Path) -> subprocess.Popen[bytes]:
    cmd = [
        sys.executable,
        "-m",
        "mas.pipelines.image_processing.run",
        "--hard-timeout-worker",
        str(payload_path),
        str(result_path),
    ]
    if os.name == "nt":
        return subprocess.Popen(cmd, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    return subprocess.Popen(cmd, start_new_session=True)


def _terminate_process_tree(process: subprocess.Popen[bytes], grace_seconds: int = _HARD_TIMEOUT_GRACE_SECONDS) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            os.kill(process.pid, signal.CTRL_BREAK_EVENT)
        except OSError:
            try:
                process.terminate()
            except OSError:
                pass
        try:
            process.wait(timeout=grace_seconds)
            return
        except subprocess.TimeoutExpired:
            pass
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        try:
            process.wait(timeout=grace_seconds)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        return

    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    except OSError:
        process.terminate()
    try:
        process.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except ProcessLookupError:
        return
    except OSError:
        process.kill()
    process.wait()


def _callable_uses_mock_mode(callable_no_args: Any) -> bool:
    if not inspect.isfunction(callable_no_args):
        return False
    closure = inspect.getclosurevars(callable_no_args)
    if "mock" in closure.nonlocals:
        return bool(closure.nonlocals["mock"])
    return False


def _qwen_provider_is_mocked() -> bool:
    from . import ipa_agent

    return isinstance(ipa_agent.call_qwen_vl, Mock)


def _closure_value(closure: inspect.ClosureVars, name: str, default: Any = None) -> Any:
    if name in closure.nonlocals:
        return closure.nonlocals[name]
    if name in closure.globals:
        return closure.globals[name]
    return default


def _callable_for_subprocess(callable_no_args: Any) -> Any:
    if not inspect.isfunction(callable_no_args) or callable_no_args.__name__ != "<lambda>":
        return callable_no_args
    closure = inspect.getclosurevars(callable_no_args)
    names = set(callable_no_args.__code__.co_names)
    referenced_process_textualization = _closure_value(closure, "process_textualization")
    if referenced_process_textualization is not None and "process_textualization" in names:
        return functools.partial(
            referenced_process_textualization,
            _closure_value(closure, "round2_prompt"),
            _closure_value(closure, "tag"),
            mock=bool(_closure_value(closure, "mock")),
            model_config=_closure_value(closure, "model_config"),
        )
    referenced_critic_revision = _closure_value(closure, "run_critic_revision_for_image")
    if referenced_critic_revision is not None and "run_critic_revision_for_image" in names:
        return functools.partial(
            referenced_critic_revision,
            image=_closure_value(closure, "image"),
            resolved=_closure_value(closure, "resolved"),
            context=_closure_value(closure, "context"),
            tag=_closure_value(closure, "tag"),
            mock=bool(_closure_value(closure, "mock")),
            gen_model_config=_closure_value(closure, "model_config"),
            verify_model_config=_closure_value(closure, "verify_model_config"),
            max_rounds=_closure_value(closure, "critic_revision_rounds"),
            run_dir=_closure_value(closure, "run_dir"),
            logger=None,
        )
    return callable_no_args


def _run_with_hard_timeout(callable_no_args, timeout_seconds: int):
    """Run callable in an isolated process and kill its process tree on timeout."""
    if _callable_uses_mock_mode(callable_no_args) or _qwen_provider_is_mocked():
        return callable_no_args()
    callable_for_worker = _callable_for_subprocess(callable_no_args)

    with tempfile.TemporaryDirectory(prefix="mas_ipa_timeout_") as tmp_dir:
        payload_path = Path(tmp_dir) / "payload.pkl"
        result_path = Path(tmp_dir) / "result.pkl"
        try:
            with payload_path.open("wb") as handle:
                pickle.dump(callable_for_worker, handle)
        except (AttributeError, TypeError, pickle.PickleError):
            return callable_no_args()

        process = _popen_for_hard_timeout(payload_path, result_path)
        try:
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                _terminate_process_tree(process)
                raise TimeoutError(f"per-image hard timeout exceeded: {timeout_seconds}s")

            if not result_path.exists():
                raise RuntimeError(f"hard timeout worker exited without result, returncode={process.returncode}")
            with result_path.open("rb") as handle:
                payload = pickle.load(handle)
            if payload.get("kind") == "result":
                return payload["value"]
            if payload.get("kind") == "exception":
                exc = payload.get("exception")
                if isinstance(exc, BaseException):
                    raise exc
                raise RuntimeError(payload.get("message", "hard timeout worker raised an unpickleable exception"))
            raise RuntimeError(payload.get("message", "hard timeout worker failed"))
        finally:
            if process.poll() is None:
                _terminate_process_tree(process)
            process.wait()


def run_pipeline(
    *,
    input_md: Path | None,
    sections_dir: Path | None,
    sections_index: Path | None,
    image_source_dir: Path | None,
    output_root: Path,
    mock: bool,
    batch_size: int = 20,
    run_label: str | None = None,
    model_config: dict[str, Any] | None = None,
    verify_model_config: dict[str, Any] | None = None,
    critic_revision_rounds: int = 5,
    enable_critic_revision: bool = True,
    taxonomy_path: Path | None = None,
    per_image_hard_timeout_seconds: int = 600,
    resume: bool = True,
    source_pdf: Path | None = None,
) -> dict[str, Any]:
    run_id = make_run_id(mock=mock, label=run_label)
    resolved_output_root = output_root.resolve()
    resume_candidate = resolved_output_root / run_id
    run_dir = resume_candidate if resume and resume_candidate.exists() else _unique_run_dir(resolved_output_root, run_id)
    run_dir.mkdir(parents=True, exist_ok=resume and run_dir.exists())
    for rel in [
        "round1_tags/per_image",
        "round2_textualization/batches",
        "round2_textualization/critic_revision",
        "enhanced_markdown/sections",
        "logs",
        "audit",
    ]:
        (run_dir / rel).mkdir(parents=True, exist_ok=True)

    original_sections = discover_section_inputs(sections_dir=sections_dir, sections_index=sections_index, input_md=input_md)
    snapshot_sections_dir, mirrored_image_count = copy_inputs_to_run(
        sections=original_sections,
        run_dir=run_dir,
        sections_index=sections_index,
        image_source_dir=image_source_dir,
    )
    snapshot_index = run_dir / "inputs" / "sections_index.json"
    snapshot_sections = discover_section_inputs(
        sections_dir=snapshot_sections_dir if sections_dir else None,
        sections_index=snapshot_index if snapshot_index.exists() else None,
        input_md=(snapshot_sections_dir / original_sections[0].path.name) if input_md else None,
    )

    effective_taxonomy_path = taxonomy_path or PROMPT_DIR / "image_taxonomy.json"
    taxonomy = load_taxonomy(effective_taxonomy_path)
    log_name = f"{run_id}.jsonl"
    logger = JsonlLogger(run_dir / "logs" / log_name)
    all_tags: dict[str, ImageTag] = {}
    all_images_by_section: dict[Path, list[Any]] = {}
    all_context: dict[str, Any] = {}
    all_resolved: dict[str, Any] = {}
    all_image_refs: dict[str, Any] = {}

    try:
        parsed_sections: list[tuple[SectionMarkdown, list[Any], list[Any]]] = []
        total_images = 0
        for section in snapshot_sections:
            images, blocks = parse_markdown(section)
            all_images_by_section[section.path] = images
            parsed_sections.append((section, images, blocks))
            total_images += len(images)

        textualizations: dict[str, TextualizationResult] = {}
        valuable_non_textual: list[dict[str, Any]] = []
        textualized: list[dict[str, Any]] = []
        round2_failed = 0
        round2_skipped_low_value = 0
        fallback_description_count = 0
        medium_description_count = 0
        trace_records: list[dict[str, Any]] = []
        referenced_file_names: set[str] = set()
        critic_revision_audits: list[dict[str, Any]] = []
        critic_revision_audits_by_image: dict[str, dict[str, Any]] = {}
        insertion_results = []
        image_counter = 0
        progress_path = run_dir / "round2_textualization" / "progress.jsonl"
        completed = _load_round2_progress(progress_path) if resume else {}
        progress_path.parent.mkdir(parents=True, exist_ok=True)

        for section, images, blocks in parsed_sections:
            for image in images:
                image_counter += 1
                resolved = resolve_image_reference(section.path, image)
                context = build_image_context(section, image, blocks)
                all_context[image.image_id] = context
                all_resolved[image.image_id] = resolved
                all_image_refs[image.image_id] = image

                tag = _load_round1_tag_checkpoint(run_dir, image.image_id) if resume else None
                if tag is not None:
                    all_tags[tag.image_id] = tag
                else:
                    try:
                        step(f"图像归类 image [{image_counter}/{total_images}] {image.image_id}")
                        prompt = build_round1_prompt(image.image_id, [(image, resolved, context)], taxonomy)
                        response = process_batch(prompt, [image.image_id], taxonomy, mock=mock, model_config=model_config)
                        (run_dir / "round1_tags" / "per_image" / f"{image.image_id}_prompt.json").write_text(
                            json.dumps(asdict(prompt), ensure_ascii=False, indent=2),
                            encoding="utf-8",
                        )
                        (run_dir / "round1_tags" / "per_image" / f"{image.image_id}_response.json").write_text(
                            response.raw_response,
                            encoding="utf-8",
                        )
                        tags = audit_round1_json(response.raw_response, [image.image_id], taxonomy)
                        tag = tags[0]
                        all_tags[tag.image_id] = tag
                        _write_round1_tag_checkpoint(run_dir, tag)
                        logger.write(
                            JSONLRecord(
                                run_id=run_id,
                                timestamp=utc_timestamp(),
                                round="tagging",
                                section_md=str(section.path),
                                image_id=image.image_id,
                                image_link=image.raw_link,
                                image_path=str(resolved.resolved_path),
                                image_exists=resolved.exists,
                                image_type_id=tag.image_type_id,
                                kg_value=tag.kg_value,
                                status="ok",
                                audit_status=tag.audit_status,
                                inserted=False,
                                mock=mock,
                                prompt=prompt.user_prompt,
                                raw_response=response.raw_response,
                                error=tag.error,
                                prompt_template_version=prompt.template_version,
                                batch_id=prompt.batch_id,
                                taxonomy_version=taxonomy.version,
                            )
                        )
                    except (ModelNotConfiguredError, OSError, QwenVLProviderError) as exc:
                        step(f"图像归类 image [{image_counter}/{total_images}] {image.image_id} FAILED: {exc}")
                        tag = ImageTag(
                            image_id=image.image_id,
                            image_type_id="unknown_or_unreadable",
                            kg_value="uncertain",
                            can_textualize=False,
                            confidence=0.0,
                            reason=f"round1 model call failed: {exc}",
                            needs_round2=False,
                            can_describe=False,
                            audit_status="failed",
                            error=str(exc),
                        )
                        all_tags[tag.image_id] = tag
                        _write_round1_tag_checkpoint(run_dir, tag)
                        logger.write(
                            JSONLRecord(
                                run_id=run_id,
                                timestamp=utc_timestamp(),
                                round="tagging",
                                section_md=str(section.path),
                                image_id=image.image_id,
                                image_link=image.raw_link,
                                image_path=str(resolved.resolved_path),
                                image_exists=resolved.exists,
                                image_type_id=tag.image_type_id,
                                kg_value=tag.kg_value,
                                status="failed",
                                audit_status=tag.audit_status,
                                inserted=False,
                                mock=mock,
                                prompt="",
                                raw_response="",
                                error=str(exc),
                                prompt_template_version="",
                                batch_id="",
                                taxonomy_version=taxonomy.version,
                            )
                        )

                if resolved.file_name:
                    referenced_file_names.add(resolved.file_name)
                plan = _processing_plan(tag)
                result: TextualizationResult | None = None
                cr_audit: dict[str, Any] | None = None
                use_critic_revision = False

                if not resolved.exists:
                    trace_records.append(
                        _trace_record_for_visible_image(
                            image=image,
                            resolved=resolved,
                            context=context,
                            tag=tag,
                            result=None,
                            critic_audit=None,
                            source_pdf=source_pdf,
                            final_note_written=True,
                        )
                    )
                    continue

                if plan == "trace_only":
                    if tag.audit_status == "passed" and tag.kg_value == "low":
                        round2_skipped_low_value += 1
                    trace_records.append(
                        _trace_record_for_visible_image(
                            image=image,
                            resolved=resolved,
                            context=context,
                            tag=tag,
                            result=None,
                            critic_audit=None,
                            source_pdf=source_pdf,
                            final_note_written=True,
                        )
                    )
                    continue

                if plan == "uncertain_fallback":
                    result = _make_uncertain_fallback(tag=tag, image=image, resolved=resolved, context=context)
                    textualizations[tag.image_id] = result
                    valuable_non_textual.append(_textualization_to_json(result))
                    fallback_description_count += 1
                    trace_records.append(
                        _trace_record_for_visible_image(
                            image=image,
                            resolved=resolved,
                            context=context,
                            tag=tag,
                            result=result,
                            critic_audit=None,
                            source_pdf=source_pdf,
                            final_note_written=True,
                        )
                    )
                    continue

                progress_rec = completed.get(tag.image_id)
                if progress_rec and progress_rec.get("result"):
                    result = TextualizationResult(**progress_rec["result"])
                    if result.audit_status == "degraded" and result.processing_status == "accepted":
                        result.processing_status = "degraded"
                    if plan == "lightweight_description" and result.processing_status == "accepted":
                        result.processing_status = "medium_described"
                    textualizations[tag.image_id] = result
                    if result.audit_status == "passed" and result.can_textualize:
                        textualized.append(_textualization_to_json(result))
                    elif tag.is_valuable:
                        valuable_non_textual.append(_textualization_to_json(result))
                    if plan == "lightweight_description" and result.audit_status == "passed":
                        medium_description_count += 1
                    if progress_rec.get("status") in ("failed", "timeout") or result.audit_status == "rejected":
                        round2_failed += 1
                    trace_records.append(
                        _trace_record_for_visible_image(
                            image=image,
                            resolved=resolved,
                            context=context,
                            tag=tag,
                            result=result,
                            critic_audit=None,
                            source_pdf=source_pdf,
                            final_note_written=True,
                        )
                    )
                    continue

                if plan == "full_round2":
                    use_critic_revision = bool(enable_critic_revision and (mock or verify_model_config is not None))
                    if use_critic_revision:
                        try:
                            result, cr_audit = _run_with_hard_timeout(
                                lambda: run_critic_revision_for_image(
                                    image=image,
                                    resolved=resolved,
                                    context=context,
                                    tag=tag,
                                    mock=mock,
                                    gen_model_config=model_config,
                                    verify_model_config=verify_model_config,
                                    max_rounds=critic_revision_rounds,
                                    run_dir=run_dir,
                                    logger=logger,
                                ),
                                per_image_hard_timeout_seconds,
                            )
                            critic_revision_audits.append(cr_audit)
                            critic_revision_audits_by_image[tag.image_id] = cr_audit
                        except (ModelNotConfiguredError, OSError, QwenVLProviderError, TimeoutError) as exc:
                            round2_failed += 1
                            result = TextualizationResult(
                                image_id=tag.image_id,
                                can_textualize=False,
                                markdown_text="",
                                short_name="第二轮处理失败",
                                short_description="完整 IPA 多轮处理失败，保留原图链接与审计记录。",
                                uncertainty="critic revision call failed or hard-timeout",
                                audit_status="failed",
                                error=str(exc),
                                processing_status="failed",
                            )
                            cr_audit = {"image_id": tag.image_id, "error": str(exc)}
                            critic_revision_audits.append(cr_audit)
                            critic_revision_audits_by_image[tag.image_id] = cr_audit
                        round2_prompt = build_round2_prompt(f"round2_{tag.image_id}", image, resolved, context, tag)
                        response_raw = json.dumps(_textualization_to_json(result), ensure_ascii=False)
                    else:
                        round2_prompt = build_round2_prompt(f"round2_{tag.image_id}", image, resolved, context, tag)
                        try:
                            round2_response = _run_with_hard_timeout(
                                lambda: process_textualization(
                                    round2_prompt,
                                    tag,
                                    mock=mock,
                                    model_config=model_config,
                                ),
                                per_image_hard_timeout_seconds,
                            )
                            response_raw = round2_response.raw_response
                            try:
                                result = audit_round2_json(
                                    round2_response.raw_response,
                                    tag.image_id,
                                    can_textualize=tag.can_textualize,
                                )
                            except ValueError as exc:
                                round2_failed += 1
                                result = TextualizationResult(
                                    image_id=tag.image_id,
                                    can_textualize=False,
                                    markdown_text="",
                                    short_name="第二轮处理失败",
                                    short_description="模型输出未通过 IPA 审计，保留原图链接与审计记录。",
                                    uncertainty="round2 audit failed",
                                    audit_status="failed",
                                    error=str(exc),
                                    processing_status="failed",
                                )
                        except (ModelNotConfiguredError, OSError, QwenVLProviderError, TimeoutError) as exc:
                            round2_failed += 1
                            result = TextualizationResult(
                                image_id=tag.image_id,
                                can_textualize=False,
                                markdown_text="",
                                short_name="第二轮处理失败",
                                short_description="模型调用异常或硬超时，保留原图链接与审计记录。",
                                uncertainty="round2 model call failed or hard-timeout",
                                audit_status="failed",
                                error=str(exc),
                                processing_status="failed",
                            )
                            response_raw = json.dumps({"error": str(exc)}, ensure_ascii=False)
                else:
                    light_tag = replace(tag, can_textualize=False, can_describe=True, needs_round2=True)
                    round2_prompt = build_round2_prompt(
                        f"round2_{tag.image_id}",
                        image,
                        resolved,
                        context,
                        light_tag,
                        output_mode_hint=MEDIUM_OUTPUT_MODE_HINT,
                    )
                    try:
                        round2_response = _run_with_hard_timeout(
                            lambda: process_textualization(
                                round2_prompt,
                                light_tag,
                                mock=mock,
                                model_config=model_config,
                            ),
                            per_image_hard_timeout_seconds,
                        )
                        response_raw = round2_response.raw_response
                        try:
                            result = audit_round2_json(
                                round2_response.raw_response,
                                tag.image_id,
                                can_textualize=False,
                            )
                            result.processing_status = "medium_described"
                            medium_description_count += 1
                        except ValueError as exc:
                            round2_failed += 1
                            result = TextualizationResult(
                                image_id=tag.image_id,
                                can_textualize=False,
                                markdown_text="",
                                short_name="轻量描述失败",
                                short_description="medium 图片轻量描述未通过审计，保留原图链接与审计记录。",
                                uncertainty="medium description audit failed",
                                audit_status="failed",
                                error=str(exc),
                                processing_status="medium_description_failed",
                            )
                    except (ModelNotConfiguredError, OSError, QwenVLProviderError, TimeoutError) as exc:
                        round2_failed += 1
                        result = TextualizationResult(
                            image_id=tag.image_id,
                            can_textualize=False,
                            markdown_text="",
                            short_name="轻量描述失败",
                            short_description="medium 图片轻量描述调用异常或硬超时，保留原图链接与审计记录。",
                            uncertainty="medium description model call failed or hard-timeout",
                            audit_status="failed",
                            error=str(exc),
                            processing_status="medium_description_failed",
                        )
                        response_raw = json.dumps({"error": str(exc)}, ensure_ascii=False)
                (run_dir / "round2_textualization" / "batches" / f"{tag.image_id}_prompt.json").write_text(
                    json.dumps(asdict(round2_prompt), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                (run_dir / "round2_textualization" / "batches" / f"{tag.image_id}_raw_response.txt").write_text(
                    response_raw,
                    encoding="utf-8",
                )
                if result.audit_status == "rejected":
                    round2_failed += 1
                textualizations[tag.image_id] = result
                if result.can_textualize:
                    textualized.append(_textualization_to_json(result))
                else:
                    valuable_non_textual.append(_textualization_to_json(result))
                _append_round2_progress(progress_path, result)
                trace_records.append(
                    _trace_record_for_visible_image(
                        image=image,
                        resolved=resolved,
                        context=context,
                        tag=tag,
                        result=result,
                        critic_audit=cr_audit or critic_revision_audits_by_image.get(tag.image_id),
                        source_pdf=source_pdf,
                        final_note_written=True,
                    )
                )
                logger.write(
                    JSONLRecord(
                        run_id=run_id,
                        timestamp=utc_timestamp(),
                        round="critic_revision" if use_critic_revision else "textualization",
                        section_md=str(section.path),
                        image_id=image.image_id,
                        image_link=image.raw_link,
                        image_path=str(resolved.resolved_path),
                        image_exists=resolved.exists,
                        image_type_id=tag.image_type_id,
                        kg_value=tag.kg_value,
                        status="ok" if result.audit_status == "passed" else "failed",
                        audit_status=result.audit_status,
                        inserted=False,
                        mock=mock,
                        prompt=round2_prompt.user_prompt,
                        raw_response=response_raw,
                        error=result.error,
                        prompt_template_version=round2_prompt.template_version,
                        batch_id=round2_prompt.batch_id,
                        taxonomy_version=taxonomy.version,
                    )
                )

            result = enhance_markdown(
                section,
                images,
                all_tags,
                textualizations,
                run_dir / "enhanced_markdown" / "sections" / section.path.name,
            )
            insertion_results.append(_jsonable(asdict(result)))

        _write_round1_outputs(run_dir, all_tags)
        if total_images and mirrored_image_count == 0:
            print(
                "[WARN] IPA mirrored_image_count=0 but Markdown contains image references; "
                "the visual model may not see any source images.",
                file=os.sys.stderr,
            )

        enhanced_sections = run_dir / "enhanced_markdown" / "sections"
        enhanced_images = enhanced_sections / "images"
        images_src = snapshot_sections_dir / "images"
        preview_image_count = _copy_preview_images(images_src, enhanced_images)
        unreferenced_source_records = _trace_records_for_unreferenced_source_images(
            image_source_dir=image_source_dir,
            referenced_file_names=referenced_file_names,
            source_pdf=source_pdf,
        )
        trace_records.extend(unreferenced_source_records)
        _write_trace_audit(run_dir, trace_records)
        trace_status_counts = Counter(str(item.get("processing_status", "unknown")) for item in trace_records)
        trace_value_counts = Counter(str(item.get("kg_value", "unknown")) for item in trace_records)
        round1_status_counts = Counter(tag.audit_status for tag in all_tags.values())
        round1_value_counts = Counter(tag.kg_value for tag in all_tags.values())
        round2_processing_counts = Counter(result.processing_status or result.audit_status for result in textualizations.values())

        write_json(run_dir / "round2_textualization" / "textualized_images.json", textualized)
        write_json(run_dir / "round2_textualization" / "valuable_non_textual_images.json", valuable_non_textual)

        generator_model = str((model_config or {}).get("name", ""))
        verifier_model = str((verify_model_config or {}).get("name", get_model("ipa_verifier").get("name", "qwen-vl-plus")))
        warnings = []
        if generator_model and verifier_model and generator_model == verifier_model:
            warnings.append("verifier and generator use the same model; independence is weakened")
        accepted_after_revision = sum(
            1
            for item in critic_revision_audits
            if item.get("final_status") == "accepted" and int(item.get("rounds_used", 0)) > 1
        )
        rejected_by_verifier = sum(1 for item in critic_revision_audits if item.get("final_status") == "rejected")
        manifest = {
            "run_id": run_id,
            "run_dir": str(run_dir),
            "mock": mock,
            "batch_size": batch_size,
            "round1_mode": "single_image_serial",
            "critic_revision_enabled": bool(enable_critic_revision),
            "critic_revision_rounds": critic_revision_rounds,
            "generator_model": generator_model,
            "verifier_model": verifier_model,
            "accepted_after_revision": accepted_after_revision,
            "rejected_by_verifier": rejected_by_verifier,
            "ipa_revision_round_counts": _ipa_revision_round_counts(
                critic_revision_audits,
                max_rounds=critic_revision_rounds,
            ),
            "warnings": warnings,
            "taxonomy_version": taxonomy.version,
            "taxonomy_path": str(effective_taxonomy_path),
            "sections": len(snapshot_sections),
            "images": len(all_tags),
            "mirrored_image_count": mirrored_image_count,
            "enhanced_preview_image_count": preview_image_count,
            "textualized": len(textualized),
            "valuable_non_textual": len(valuable_non_textual),
            "round2_skipped_low_value": round2_skipped_low_value,
            "fallback_descriptions": fallback_description_count,
            "medium_descriptions": medium_description_count,
            "image_trace_audit": str(run_dir / "audit" / "image_trace_audit.json"),
            "image_trace_records": len(trace_records),
            "unreferenced_source_images": len(unreferenced_source_records),
            "image_trace_status_counts": dict(trace_status_counts),
            "image_trace_kg_value_counts": dict(trace_value_counts),
            "round1_audit_status_counts": dict(round1_status_counts),
            "round1_kg_value_counts": dict(round1_value_counts),
            "round2_processing_status_counts": dict(round2_processing_counts),
            "round2_skipped_low_value_note": (
                "images with kg_value=low skip deep Round2 but keep FigureRef trace; uncertain receives fallback trace"
            ),
            "source_pdf": str(Path(source_pdf).resolve()) if source_pdf else "",
            "input_md": str(input_md) if input_md else "",
            "sections_dir": str(sections_dir) if sections_dir else "",
            "sections_index": str(sections_index) if sections_index else "",
            "image_source_dir": str(image_source_dir) if image_source_dir else "",
            "insertion_results": insertion_results,
            "token_usage": usage_snapshot(),
        }
        write_json(run_dir / "manifest.json", manifest)
        write_json(
            run_dir / "audit" / "round1_audit_summary.json",
            {
                "passed": int(round1_status_counts.get("passed", 0)),
                "failed": int(round1_status_counts.get("failed", 0)),
                "by_status": dict(round1_status_counts),
                "kg_value_counts": dict(round1_value_counts),
                "taxonomy_version": taxonomy.version,
            },
        )
        write_json(
            run_dir / "audit" / "round2_audit_summary.json",
            {"passed": len(textualizations) - round2_failed, "failed": round2_failed},
        )
        write_json(run_dir / "audit" / "critic_revision_summary.json", critic_revision_audits)
        return manifest
    finally:
        logger.close()


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    config = load_ipa_config(args.config)
    mock = resolve_mock(args.mock, config)
    try:
        manifest = run_pipeline(
            input_md=Path(args.input_md).resolve() if args.input_md else None,
            sections_dir=Path(args.sections_dir).resolve() if args.sections_dir else None,
            sections_index=Path(args.sections_index).resolve() if args.sections_index else None,
            image_source_dir=Path(args.image_source_dir).resolve() if args.image_source_dir else None,
            source_pdf=Path(args.source_pdf).resolve() if args.source_pdf else None,
            output_root=Path(args.output_root),
            mock=mock,
            batch_size=args.batch_size,
            run_label=args.run_id,
            model_config=config.get("model", {}),
            taxonomy_path=Path(args.taxonomy or config.get("taxonomy_path")).resolve()
            if (args.taxonomy or config.get("taxonomy_path"))
            else None,
            per_image_hard_timeout_seconds=args.per_image_hard_timeout_seconds,
            resume=not args.no_ipa_resume,
        )
    except ModelNotConfiguredError as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({"ok": True, "run_dir": manifest["run_dir"], "mock": manifest["mock"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--hard-timeout-worker":
        raise SystemExit(_hard_timeout_worker(sys.argv[2], sys.argv[3]))
    main()
