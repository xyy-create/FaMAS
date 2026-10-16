"""Source loading helpers for KG Extraction MAS.

This module loads shared standards, the published KG schema, enhanced
Markdown section contexts, IPA image-note evidence, and schema-compatible
EvidenceRef objects. It does not call LLM providers and does not mutate
upstream input files.
"""

from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Sequence

from .models import ExtractionSectionContext, IpaImageEvidence, make_stable_id


SUPPORTED_STANDARD_SUFFIXES = {".md", ".txt", ".json"}
HARD_FAILURE_MARKERS = [
    "第二轮处理失败",
    "未通过审计",
    "图片处理失败或无法可靠识别",
    "未获得可靠分类",
    "degraded",
    "降级",
    "不作为 KG 事实抽取依据",
]
LOW_VALUE_MARKERS = [
    "暂不提取文本化内容",
    "保留原图链接和价值标记",
    "未生成文本化内容",
    "保留原图链接",
    "fallback",
    "追溯记录",
]
IPA_FAILURE_MARKERS = HARD_FAILURE_MARKERS + LOW_VALUE_MARKERS


def load_standards(standards_dir: Path) -> list[dict[str, Any]]:
    """Load every supported shared standards file.

    Args:
        standards_dir: Directory containing standards files.

    Returns:
        Sorted list with `file`, `path`, `chars`, `sha256`, and `content`.

    Raises:
        ValueError: If the directory is missing or invalid.
    """

    root = Path(standards_dir)
    if not root.exists() or not root.is_dir():
        raise ValueError(f"standards directory is missing: {root}")
    standards: list[dict[str, Any]] = []
    for path in sorted(item for item in root.iterdir() if item.is_file()):
        if path.suffix.lower() not in SUPPORTED_STANDARD_SUFFIXES:
            continue
        content = path.read_text(encoding="utf-8")
        standards.append(
            {
                "file": path.name,
                "path": str(path.resolve()),
                "chars": len(content),
                "sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
                "content": content,
            }
        )
    if not standards:
        raise ValueError(f"standards directory has no supported files: {root}")
    return standards


def load_published_schema(schema_path: Path) -> dict[str, Any]:
    """Load and validate the published KG schema contract.

    Args:
        schema_path: Path to `kg_schema_label_property_v2.json`.

    Returns:
        Parsed schema JSON object.

    Raises:
        ValueError: If schema version or required top-level keys are invalid.
    """

    path = Path(schema_path)
    if not path.exists() or not path.is_file():
        raise ValueError(f"schema file is missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("schema must be a JSON object")
    if data.get("schema_version") != "kg.schema.label_property.v2":
        raise ValueError("schema_version must be kg.schema.label_property.v2")
    for key in ["node_labels", "edge_labels", "shared_property_types"]:
        if not isinstance(data.get(key), list) or not data[key]:
            raise ValueError(f"schema requires non-empty {key}")
    return data


def _load_sections_index(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("sections_index must be a JSON object")
    sections = data.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("sections_index requires non-empty sections")
    return data


def build_section_contexts(
    enhanced_md_paths: Sequence[Path],
    sections_index_path: Path,
) -> list[ExtractionSectionContext]:
    """Bind IPA enhanced Markdown files to section metadata.

    Args:
        enhanced_md_paths: One or more IPA enhanced Markdown paths.
        sections_index_path: Path to `sections_index.json`.

    Returns:
        Section contexts with parsed IPA image evidence.

    Raises:
        ValueError: If inputs are missing or cannot be matched by filename.
    """

    if not enhanced_md_paths:
        raise ValueError("at least one --enhanced-md path is required")
    index = _load_sections_index(sections_index_path)
    sections = index["sections"]
    by_file = {str(item.get("file")): item for item in sections if isinstance(item, dict)}
    contexts: list[ExtractionSectionContext] = []
    for raw_path in enhanced_md_paths:
        path = Path(raw_path)
        if not path.exists() or not path.is_file():
            raise ValueError(f"enhanced markdown file does not exist: {path}")
        section = by_file.get(path.name)
        if section is None:
            raise ValueError(f"no section metadata found for enhanced markdown file: {path.name}")
        order = int(section.get("order", len(contexts) + 1))
        section_id = f"s{order:03d}"
        source_context_id = f"{section_id}_{path.stem}"
        context = ExtractionSectionContext(
            source_context_id=source_context_id,
            section_id=section_id,
            markdown_path=path.resolve(),
            markdown_file=path.name,
            markdown_text=path.read_text(encoding="utf-8"),
            textbook_profile={
                "textbook": str(index.get("textbook", "")),
                "subject": str(index.get("subject", "")),
                "publisher": str(index.get("publisher", "")),
                "grade": str(index.get("grade", "")),
            },
            section_metadata={str(key): value for key, value in section.items()},
            ipa_image_evidence=[],
        )
        context.ipa_image_evidence = parse_ipa_image_notes(context)
        contexts.append(context)
    return contexts


def split_markdown_blocks(text: str) -> list[dict[str, Any]]:
    """Split Markdown into blocks while preserving IPA notes.

    Args:
        text: Markdown text.

    Returns:
        Blocks with text and character offsets.
    """

    lines = text.splitlines(keepends=True)
    blocks: list[dict[str, Any]] = []
    current: list[str] = []
    start = 0
    offset = 0
    in_note = False

    def flush(end_offset: int) -> None:
        nonlocal current, start
        block_text = "".join(current).strip()
        if block_text:
            blocks.append({"text": block_text, "start": start, "end": end_offset})
        current = []
        start = end_offset

    for line in lines:
        line_start = offset
        line_end = offset + len(line)
        if "[!NOTE] Image Processing Agent" in line:
            flush(line_start)
            current = [line]
            start = line_start
            in_note = True
            offset = line_end
            continue
        if in_note:
            if line.startswith(">") or not line.strip():
                current.append(line)
                offset = line_end
                continue
            flush(line_start)
            in_note = False
            current = [line]
            start = line_start
            offset = line_end
            continue
        if not line.strip():
            flush(line_start)
            start = line_end
            offset = line_end
            continue
        if line.startswith("#"):
            flush(line_start)
            current = [line]
            start = line_start
            offset = line_end
            continue
        if not current:
            start = line_start
        current.append(line)
        offset = line_end
    flush(len(text))
    return blocks


def build_local_context(
    markdown_text: str,
    char_start: int,
    char_end: int,
    *,
    default_each_side: int = 3,
    min_each_side: int = 2,
    max_each_side: int = 4,
) -> dict[str, Any]:
    """Build IPA-style local context around evidence or image text.

    Args:
        markdown_text: Full enhanced Markdown text.
        char_start: Evidence start character offset.
        char_end: Evidence end character offset.
        default_each_side: Default non-empty blocks on each side.
        min_each_side: Minimum target when boundaries allow.
        max_each_side: Maximum blocks on each side.

    Returns:
        Dict containing nearest heading, before blocks, after blocks, and policy.
    """

    blocks = split_markdown_blocks(markdown_text)
    block_index = 0
    for idx, block in enumerate(blocks):
        if block["start"] <= char_start <= block["end"]:
            block_index = idx
            break
    each_side = max(min_each_side, min(default_each_side, max_each_side))
    before = [b["text"] for b in blocks[max(0, block_index - each_side) : block_index]]
    after = [b["text"] for b in blocks[block_index + 1 : block_index + 1 + each_side]]
    nearest_heading = ""
    for b in reversed(blocks[: block_index + 1]):
        if b["text"].startswith("#"):
            nearest_heading = b["text"].splitlines()[0].lstrip("#").strip()
            break
    return {
        "nearest_heading": nearest_heading,
        "before_blocks": before[-max_each_side:],
        "after_blocks": after[:max_each_side],
        "policy": {
            "default_each_side": default_each_side,
            "min_each_side": min_each_side,
            "max_each_side": max_each_side,
        },
        "char_start": char_start,
        "char_end": char_end,
    }


def _parse_image_path(image_markdown: str) -> str:
    match = re.search(r"!\[[^\]]*\]\(([^)]+)\)", image_markdown)
    return match.group(1).strip() if match else ""


def _field_value(note_text: str, field_name: str) -> str:
    match = re.search(rf">\s*{re.escape(field_name)}[:：]\s*(.*)", note_text)
    if not match:
        return ""
    first = match.group(1).strip()
    if first:
        return first.strip()
    if field_name != "处理结果":
        return ""
    code_match = re.search(r">\s*处理结果[:：]\s*\n(?:>\s*```\s*\n)?(?P<body>.*?)(?:\n>\s*```|\Z)", note_text, re.S)
    if not code_match:
        return ""
    body = code_match.group("body")
    lines = []
    for line in body.splitlines():
        line = re.sub(r"^>\s?", "", line).strip()
        if line and line != "```":
            lines.append(line)
    return "\n".join(lines).strip()


def _has_hard_failure(result_text: str) -> bool:
    return any(marker in result_text for marker in HARD_FAILURE_MARKERS)


def _has_usable_result_text(result_text: str) -> bool:
    text = result_text.strip()
    if not text:
        return False
    if _has_hard_failure(text):
        return False
    return not any(marker in text for marker in LOW_VALUE_MARKERS)


BLOCKED_PROCESSING_STATUSES = {
    "degraded",
    "failed",
    "rejected",
    "skipped_low",
    "fallback_uncertain",
    "uncertain_no_fallback",
    "medium_description_failed",
    "classification_missing",
    "missing_image_file",
    "trace_only",
}


def _is_blocked_processing_status(processing_status: str) -> bool:
    value = processing_status.strip().lower()
    return value in BLOCKED_PROCESSING_STATUSES or "degraded" in value or "fallback" in value


def _is_eligible_note(kg_value: str, result_text: str, processing_status: str = "") -> bool:
    if _is_blocked_processing_status(processing_status):
        return False
    if kg_value.strip().lower() not in {"high", "medium"}:
        return False
    return _has_usable_result_text(result_text)


def _is_supplementary_note(kg_value: str, result_text: str, processing_status: str = "") -> bool:
    return False


def parse_ipa_image_notes(context: ExtractionSectionContext) -> list[IpaImageEvidence]:
    """Parse IPA image-note blocks from enhanced Markdown.

    Args:
        context: Section context containing Markdown text.

    Returns:
        Parsed image evidence records with eligibility flags.
    """

    text = context.markdown_text
    note_pattern = re.compile(
        r"(?P<img>!\[[^\]]*\]\([^)]+\))\s*\n\s*\n(?P<note>>\s*\[!NOTE\]\s*Image Processing Agent(?:(?:\n>.*)|(?:\n\s*))+)",
        re.MULTILINE,
    )
    notes: list[IpaImageEvidence] = []
    for index, match in enumerate(note_pattern.finditer(text), start=1):
        image_markdown = match.group("img").strip()
        image_path = _parse_image_path(image_markdown)
        note_text = match.group("note")
        image_type = _field_value(note_text, "图片类型")
        kg_value = _field_value(note_text, "KG 价值").lower()
        processing_status = _field_value(note_text, "处理状态")
        result_text = _field_value(note_text, "处理结果")
        eligible = _is_eligible_note(kg_value, result_text, processing_status)
        supplementary = _is_supplementary_note(kg_value, result_text, processing_status)
        if eligible:
            result_status = "eligible_text"
        elif supplementary:
            result_status = "supplementary_image"
        elif _has_hard_failure(result_text) or _is_blocked_processing_status(processing_status):
            result_status = "hard_failed"
        else:
            result_status = "not_fact_eligible"
        local_image_id = f"{context.section_id}_img{index:04d}"
        local = build_local_context(text, match.start(), match.end())
        evidence_key = make_stable_id(
            "ipa_evidence",
            [
                str(context.markdown_path),
                context.markdown_file,
                context.section_id,
                image_path,
                local_image_id,
            ],
        )
        notes.append(
            IpaImageEvidence(
                evidence_key=evidence_key,
                local_image_id=local_image_id,
                image_markdown=image_markdown,
                image_path=image_path,
                source_markdown_path=str(context.markdown_path),
                markdown_file=context.markdown_file,
                section_id=context.section_id,
                image_type=image_type,
                kg_value=kg_value,
                result_text=result_text,
                result_status=result_status,
                eligible_for_fact_evidence=eligible,
                nearest_heading=str(local["nearest_heading"]),
                before_blocks=list(local["before_blocks"]),
                after_blocks=list(local["after_blocks"]),
                supplementary_for_fact_evidence=supplementary,
            )
        )
    return notes


def to_evidence_ref(
    *,
    context: ExtractionSectionContext,
    source_type: str,
    source_path: str,
    quote_or_summary: str,
    ipa_note_summary: str | None = None,
) -> dict[str, Any]:
    """Create a schema-compatible EvidenceRef.

    Args:
        context: Source section context.
        source_type: `textbook_body`, `ipa_image`, or `ipa_generated_text`.
        source_path: Markdown path or image path.
        quote_or_summary: Original quote or faithful IPA-generated text.
        ipa_note_summary: Optional IPA provenance summary.

    Returns:
        EvidenceRef object matching the published schema.
    """

    evidence = {
        "source_type": source_type,
        "source_path": str(source_path),
        "section": {
            "source_context_id": context.source_context_id,
            "section_id": context.section_id,
            "metadata": context.section_metadata,
        },
        "quote_or_summary": quote_or_summary,
    }
    if ipa_note_summary:
        evidence["ipa_note_summary"] = ipa_note_summary
    return evidence


def locate_evidence_text(
    evidence_text: str,
    contexts: Sequence[ExtractionSectionContext],
) -> dict[str, Any]:
    """Locate evidence text approximately in source contexts.

    Args:
        evidence_text: Candidate EvidenceRef quote_or_summary.
        contexts: Source section contexts.

    Returns:
        Best match with context id, source path, score, and match status.
    """

    needle = _normalize_for_match(evidence_text)
    best = {"score": 0.0, "match_status": "not_found", "source_context_id": "", "source_path": ""}
    if not needle:
        return best
    for context in contexts:
        body = _normalize_for_match(context.markdown_text)
        score = 1.0 if needle in body else difflib.SequenceMatcher(None, needle, body).quick_ratio()
        for evidence in context.ipa_image_evidence:
            if evidence.eligible_for_fact_evidence or evidence.supplementary_for_fact_evidence:
                ipa_score = 1.0 if needle in _normalize_for_match(evidence.result_text) else difflib.SequenceMatcher(
                    None, needle, _normalize_for_match(evidence.result_text)
                ).ratio()
                score = max(score, ipa_score)
        if score > float(best["score"]):
            best = {
                "score": score,
                "match_status": "matched" if score >= 0.8 else "weak_match",
                "source_context_id": context.source_context_id,
                "source_path": str(context.markdown_path),
            }
    return best


def _normalize_for_match(text: str) -> str:
    return re.sub(r"[\s，。、“”‘’：:；;,.!！?？`*_#>\-\[\]\(\)]", "", str(text))
