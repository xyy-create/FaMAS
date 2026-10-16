"""Create enhanced Markdown with IPA notes while preserving source links."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from .markdown_parser import MarkdownImage, SectionMarkdown
from .output_auditor import ImageTag, TextualizationResult


@dataclass
class MarkdownInsertion:
    image_id: str
    inserted: bool
    insert_char: int
    note_text: str
    reason: str


@dataclass
class MarkdownInsertionResult:
    section_path: Path
    output_path: Path
    inserted_count: int
    skipped_count: int
    image_results: list[MarkdownInsertion]


def _blockquote_body(text: str) -> str:
    lines = text.splitlines() or [""]
    return "\n".join(f"> {line}" if line else ">" for line in lines)


def _strip_markdown_image_syntax(text: str) -> str:
    return re.sub(r"!\[([^\]]*)\]\([^)]+\)", r"\1", text)


def _round2_note_text(round2: TextualizationResult) -> str:
    if round2.markdown_text.strip():
        return _strip_markdown_image_syntax(round2.markdown_text)
    parts = [round2.short_name.strip(), round2.short_description.strip()]
    return "：".join(part for part in parts if part)


def build_ipa_note(tag: ImageTag | None, round2: TextualizationResult | None = None) -> str:
    if tag is None:
        return (
            "\n\n> [!NOTE] Image Processing Agent\n"
            "> Image ID：unknown\n"
            "> 图片类型：unknown_or_unreadable\n"
            "> KG 价值：uncertain\n"
            "> 处理状态：classification_missing\n"
            "> 处理结果：图片未获得可靠分类，保留原图链接。\n"
        )

    lines = [
        "",
        "",
        "> [!NOTE] Image Processing Agent",
        f"> Image ID：{tag.image_id}",
        f"> 图片类型：{tag.image_type_id}",
        f"> KG 价值：{tag.kg_value}",
    ]
    if round2 and round2.processing_status == "degraded":
        note_text = _round2_note_text(round2).strip() or "保留原图链接；最后候选描述为空。"
        lines.append("> 处理状态：degraded")
        lines.append("> 处理结果：degraded，保留最后一轮候选描述；不作为 KG 事实抽取依据。")
        lines.append(_blockquote_body(note_text))
    elif round2:
        status = round2.processing_status or round2.audit_status
        note_text = _round2_note_text(round2).strip()
        lines.append(f"> 处理状态：{status}")
        if note_text and (round2.can_textualize or "\n" in note_text):
            lines.append("> 处理结果：")
            lines.append(_blockquote_body(note_text))
        elif note_text:
            lines.append(f"> 处理结果：{note_text}")
        else:
            lines.append("> 处理结果：已保留原图链接，未生成可用文本描述。")
    elif tag.kg_value == "low":
        lines.append("> 处理状态：skipped_low")
        lines.append("> 处理结果：该图片暂不提取文本化内容；保留 FigureRef 追溯记录。")
    elif tag.kg_value == "uncertain" or tag.audit_status != "passed":
        lines.append("> 处理状态：uncertain_no_fallback")
        lines.append("> 处理结果：图片处理失败或无法可靠识别，保留原图链接并进入审计记录。")
    else:
        lines.append("> 处理状态：trace_only")
        lines.append("> 处理结果：该图片保留原图链接和价值标记，未生成文本化内容。")
    return "\n".join(lines) + "\n"


def enhance_markdown(
    section: SectionMarkdown,
    images: list[MarkdownImage],
    tags_by_image_id: dict[str, ImageTag],
    textualizations_by_image_id: dict[str, TextualizationResult],
    output_path: Path,
) -> MarkdownInsertionResult:
    text = section.text
    insertions: list[MarkdownInsertion] = []
    for image in sorted(images, key=lambda item: item.start_char, reverse=True):
        tag = tags_by_image_id.get(image.image_id)
        note = build_ipa_note(tag, textualizations_by_image_id.get(image.image_id))
        text = text[: image.end_char] + note + text[image.end_char :]
        insertions.append(MarkdownInsertion(image.image_id, True, image.end_char, note, "inserted"))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(text, encoding="utf-8")
    insertions.reverse()
    return MarkdownInsertionResult(
        section_path=section.path,
        output_path=output_path,
        inserted_count=len(insertions),
        skipped_count=0,
        image_results=insertions,
    )
