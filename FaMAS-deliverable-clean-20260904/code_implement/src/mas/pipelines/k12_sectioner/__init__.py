"""K12 textbook Markdown segmentation used by the FaMAS segmentation stage."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def segment_markdown_file(md_path: Path, output_root: Path, **kwargs: Any) -> dict[str, object]:
    from .adapter import segment_markdown_file as _segment_markdown_file

    return _segment_markdown_file(md_path, output_root, **kwargs)


def sanitize_token(token: str) -> str:
    from .adapter import sanitize_token as _sanitize_token

    return _sanitize_token(token)


__all__ = ["segment_markdown_file", "sanitize_token"]
