"""Parse section Markdown files for IPA image processing."""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from pathlib import Path
from typing import Any, List, Tuple


IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]*)\)")
HEADING_RE = re.compile(r"^(#{1,6})\s*(.*\S)?\s*$", re.MULTILINE)


@dataclass
class SectionMarkdown:
    path: Path
    order: int
    title: str
    textbook: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    text: str = ""


@dataclass
class MarkdownBlock:
    index: int
    text: str
    start_char: int
    end_char: int
    start_line: int
    end_line: int


@dataclass
class MarkdownImage:
    image_id: str
    section_order: int
    image_order: int
    alt_text: str
    raw_link: str
    raw_markdown: str
    start_char: int
    end_char: int
    line_number: int
    block_index: int | None
    nearest_heading: str


def load_section_markdown(path: Path, metadata: dict[str, Any]) -> SectionMarkdown:
    md_path = Path(path).resolve()
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    order = int(metadata.get("order") or metadata.get("section_order") or 1)
    title = str(metadata.get("title") or metadata.get("chapter_title") or md_path.stem)
    textbook = str(metadata.get("textbook") or "")
    return SectionMarkdown(path=md_path, order=order, title=title, textbook=textbook, metadata=metadata, text=text)


def _line_number_at(text: str, char_offset: int) -> int:
    return text.count("\n", 0, char_offset) + 1


def split_nonempty_blocks(text: str) -> List[MarkdownBlock]:
    blocks: List[MarkdownBlock] = []
    for match in re.finditer(r"\S(?:.*?)(?=\n\s*\n|\Z)", text, flags=re.DOTALL):
        block_text = match.group(0).strip()
        if not block_text:
            continue
        start = match.start()
        end = match.end()
        blocks.append(
            MarkdownBlock(
                index=len(blocks),
                text=block_text,
                start_char=start,
                end_char=end,
                start_line=_line_number_at(text, start),
                end_line=_line_number_at(text, end),
            )
        )
    return blocks


def nearest_heading_before(text: str, char_offset: int) -> str:
    nearest = ""
    for match in HEADING_RE.finditer(text):
        if match.start() > char_offset:
            break
        heading = match.group(0).strip()
        if heading:
            nearest = heading
    return nearest


def _block_index_for(blocks: list[MarkdownBlock], char_offset: int) -> int | None:
    for block in blocks:
        if block.start_char <= char_offset <= block.end_char:
            return block.index
    return None


def find_markdown_images(section: SectionMarkdown, blocks: list[MarkdownBlock]) -> list[MarkdownImage]:
    images: list[MarkdownImage] = []
    for image_order, match in enumerate(IMAGE_RE.finditer(section.text), start=1):
        image_id = f"s{section.order:03d}_img{image_order:04d}"
        images.append(
            MarkdownImage(
                image_id=image_id,
                section_order=section.order,
                image_order=image_order,
                alt_text=match.group(1),
                raw_link=match.group(2).strip(),
                raw_markdown=match.group(0),
                start_char=match.start(),
                end_char=match.end(),
                line_number=_line_number_at(section.text, match.start()),
                block_index=_block_index_for(blocks, match.start()),
                nearest_heading=nearest_heading_before(section.text, match.start()),
            )
        )
    return images


def parse_markdown(section: SectionMarkdown) -> Tuple[list[MarkdownImage], list[MarkdownBlock]]:
    blocks = split_nonempty_blocks(section.text)
    return find_markdown_images(section, blocks), blocks
