"""Collect and sample images for taxonomy discovery."""

from __future__ import annotations

from dataclasses import dataclass, asdict
import random
from pathlib import Path
from typing import Any

from mas.pipelines.image_processing.context_builder import build_image_context
from mas.pipelines.image_processing.image_reference import resolve_image_reference
from mas.pipelines.image_processing.markdown_parser import SectionMarkdown, parse_markdown
from mas.pipelines.image_processing.run import discover_section_inputs


@dataclass
class SampledImage:
    image_id: str
    section_id: str
    section_order: int
    section_title: str
    markdown_path: str
    raw_link: str
    resolved_path: str
    exists: bool
    nearest_heading: str
    before_context: list[str]
    after_context: list[str]
    file_name: str = ""
    suffix: str = ""
    bytes: int | None = None
    textbook: str = ""

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _with_image_source_dir(markdown_file: Path, raw_link: str, image_source_dir: Path | None) -> Path | None:
    if image_source_dir is None:
        return None
    source = Path(image_source_dir)
    candidate = source / Path(raw_link).name
    if candidate.exists():
        return candidate.resolve()
    return None


def collect_images(
    *,
    sections_dir: Path,
    sections_index: Path | None,
    image_source_dir: Path | None,
) -> list[SampledImage]:
    sections = discover_section_inputs(sections_dir=sections_dir, sections_index=sections_index, input_md=None)
    collected: list[SampledImage] = []
    for section in sections:
        assert isinstance(section, SectionMarkdown)
        images, blocks = parse_markdown(section)
        for image in images:
            resolved = resolve_image_reference(section.path, image)
            source_override = _with_image_source_dir(section.path, image.raw_link, image_source_dir)
            resolved_path = source_override or resolved.resolved_path
            exists = bool(source_override) or resolved.exists
            context = build_image_context(section, image, blocks)
            file_metadata = resolved.file_metadata
            collected.append(
                SampledImage(
                    image_id=image.image_id,
                    section_id=f"s{section.order:03d}",
                    section_order=section.order,
                    section_title=section.title,
                    markdown_path=str(section.path),
                    raw_link=image.raw_link,
                    resolved_path=str(resolved_path),
                    exists=exists,
                    nearest_heading=context.nearest_heading,
                    before_context=context.before_blocks,
                    after_context=context.after_blocks,
                    file_name=Path(resolved_path).name,
                    suffix=Path(resolved_path).suffix.lower(),
                    bytes=file_metadata.bytes if file_metadata else None,
                    textbook=section.textbook,
                )
            )
    return collected


def sample_images(images: list[SampledImage], *, sample_size: int, seed: int) -> list[SampledImage]:
    if sample_size <= 0:
        raise ValueError("sample_size must be positive")
    if len(images) <= sample_size:
        return list(images)
    rng = random.Random(seed)
    return rng.sample(images, sample_size)


def resolve_sample_size(
    total: int,
    *,
    ratio: float = 0.6,
    batch_size: int = 50,
    min_batches: int = 1,
) -> int:
    """Resolve a ratio-based sample size floored to a batch-size multiple."""

    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    if total <= 0:
        return 0
    raw = int(total * ratio)
    floored = (raw // batch_size) * batch_size
    if floored == 0:
        floored = min(batch_size * min_batches, total)
    return min(floored, total)


def shuffle_for_batches(images: list[SampledImage], *, seed: int) -> list[SampledImage]:
    """Return a seeded shuffle so sequential chunking evenly assigns batches."""

    shuffled = list(images)
    rng = random.Random(seed)
    rng.shuffle(shuffled)
    return shuffled
