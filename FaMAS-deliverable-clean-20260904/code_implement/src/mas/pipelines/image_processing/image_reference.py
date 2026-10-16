"""Resolve Markdown image links to local files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from .markdown_parser import MarkdownImage


@dataclass
class ImageFileMetadata:
    width: int | None
    height: int | None
    bytes: int | None
    suffix: str


@dataclass
class ResolvedImage:
    image_id: str
    raw_link: str
    markdown_file: Path
    resolved_path: Path
    exists: bool
    file_name: str
    suffix: str
    error: str = ""
    file_metadata: ImageFileMetadata | None = None


def _is_url(link: str) -> bool:
    parsed = urlparse(link)
    return parsed.scheme in {"http", "https", "data"}


def resolve_image_reference(markdown_file: Path, image: MarkdownImage) -> ResolvedImage:
    raw_link = image.raw_link.strip()
    markdown_path = Path(markdown_file).resolve()
    if not raw_link:
        resolved = markdown_path.parent
        return ResolvedImage(image.image_id, raw_link, markdown_path, resolved, False, "", "", "empty image link")
    if _is_url(raw_link):
        resolved = Path(raw_link)
        return ResolvedImage(image.image_id, raw_link, markdown_path, resolved, False, raw_link, "", "remote image link")

    link_path = Path(raw_link)
    resolved = link_path if link_path.is_absolute() else (markdown_path.parent / link_path)
    resolved = resolved.resolve()
    exists = resolved.exists()
    error = "" if exists else f"missing image file: {resolved}"
    size = resolved.stat().st_size if exists else None
    metadata = ImageFileMetadata(width=None, height=None, bytes=size, suffix=resolved.suffix.lower())
    return ResolvedImage(
        image_id=image.image_id,
        raw_link=raw_link,
        markdown_file=markdown_path,
        resolved_path=resolved,
        exists=exists,
        file_name=resolved.name,
        suffix=resolved.suffix.lower(),
        error=error,
        file_metadata=metadata,
    )
