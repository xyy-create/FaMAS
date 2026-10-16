"""Build local Markdown context around an image."""

from __future__ import annotations

from dataclasses import dataclass
import re

from .markdown_parser import MarkdownBlock, MarkdownImage, SectionMarkdown


@dataclass
class ImageContext:
    image_id: str
    section_title: str
    nearest_heading: str
    before_blocks: list[str]
    after_blocks: list[str]
    context_policy: str


def _filter_context_blocks(block_texts: list[str]) -> list[str]:
    img_only = re.compile(r"^!\[[^\]]*\]\([^)]+\)\s*$")
    heading = re.compile(r"^#{1,6}\s")
    result = []
    for text in block_texts:
        stripped = text.strip()
        if heading.match(stripped):
            result.append(stripped)
            continue
        if img_only.match(stripped):
            continue
        cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", stripped).strip()
        meaningful = re.sub(r"[^\w\u4e00-\u9fff]", "", cleaned)
        if len(meaningful) < 6:
            continue
        result.append(cleaned)
    return result


def build_image_context(
    section: SectionMarkdown,
    image: MarkdownImage,
    blocks: list[MarkdownBlock],
    min_each_side: int = 2,
    max_each_side: int = 4,
) -> ImageContext:
    block_index = image.block_index
    if block_index is None:
        before = [block.text for block in blocks if block.end_char <= image.start_char][-max_each_side:]
        after = [block.text for block in blocks if block.start_char >= image.end_char][:max_each_side]
    else:
        before = [block.text for block in blocks[:block_index]][-max_each_side:]
        after = [block.text for block in blocks[block_index + 1 :]][:max_each_side]

    before = before[-max_each_side:]
    after = after[:max_each_side]
    if len(before) > min_each_side:
        before = before[-max_each_side:]
    if len(after) > min_each_side:
        after = after[:max_each_side]

    before = _filter_context_blocks(before)
    after = _filter_context_blocks(after)

    return ImageContext(
        image_id=image.image_id,
        section_title=section.title,
        nearest_heading=image.nearest_heading or section.title,
        before_blocks=before,
        after_blocks=after,
        context_policy=f"heading + before/after {min_each_side}-{max_each_side} non-empty markdown blocks",
    )
