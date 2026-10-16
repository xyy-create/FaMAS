"""Adapter that exposes the K12 sectioner through FaMAS' segmentation API."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from . import high_school
from . import junior_retry_20260807 as junior


sanitize_token = high_school.sanitize_token


def _select_impl(stage: str, grade: str = "") -> Any:
    marker = f"{stage} {grade}".lower()
    if any(token in marker for token in ["小学", "初中", "primary", "elementary", "junior", "middle"]):
        return junior
    return high_school


def _ensure_ordered_index(book_dir: Path, sections_dir: Path, written: int) -> int:
    index_path = book_dir / "sections_index.json"
    if not index_path.exists():
        return written

    index = json.loads(index_path.read_text(encoding="utf-8"))
    raw_sections = index.get("sections")
    if not isinstance(raw_sections, list):
        return written

    filtered: list[dict[str, Any]] = []
    for item in raw_sections:
        if not isinstance(item, dict):
            continue
        file_name = str(item.get("file", "")).strip()
        if not file_name or not (sections_dir / file_name).is_file():
            continue
        next_item = dict(item)
        next_item["order"] = len(filtered) + 1
        next_item.setdefault("start_line", 1)
        try:
            text = (sections_dir / file_name).read_text(encoding="utf-8", errors="ignore")
            next_item["end_line"] = max(1, text.count("\n") + 1)
        except OSError:
            next_item.setdefault("end_line", 1)
        filtered.append(next_item)

    if not filtered:
        for order, md_path in enumerate(sorted(sections_dir.glob("*.md")), start=1):
            text = md_path.read_text(encoding="utf-8", errors="ignore")
            filtered.append(
                {
                    "order": order,
                    "chapter_num": "",
                    "chapter_title": md_path.stem,
                    "section_num": "",
                    "section_title": "",
                    "file": md_path.name,
                    "start_line": 1,
                    "end_line": max(1, text.count("\n") + 1),
                }
            )

    index["sections"] = filtered
    index_text = json.dumps(index, ensure_ascii=False, indent=2)
    index_path.write_text(index_text, encoding="utf-8")
    (book_dir / "section_index.json").write_text(index_text, encoding="utf-8")
    return len(filtered)


def _copy_images(md_path: Path, sections_dir: Path) -> tuple[str, int]:
    images_src = md_path.parent / "images"
    images_dst = sections_dir / "images"
    if not images_src.is_dir():
        return str(images_dst), 0
    shutil.copytree(images_src, images_dst, dirs_exist_ok=True)
    return str(images_dst), sum(1 for item in images_dst.iterdir() if item.is_file())


FALLBACK_TARGET_CHARS = 9000
FALLBACK_MAX_CHARS = 14000
FALLBACK_MAX_PAGES_PER_SECTION = 4


def _line_count(text: str) -> int:
    return max(1, text.count("\n") + 1)


def _page_number_from_heading(line: str) -> int | None:
    match = re.match(r"^##\s+Page\s+(\d+)\s*$", line.strip(), re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _split_page_blocks(text: str) -> list[dict[str, Any]]:
    lines = text.splitlines()
    blocks: list[dict[str, Any]] = []
    current: list[str] = []
    current_page: int | None = None
    start_line = 1

    def flush(end_line: int) -> None:
        nonlocal current, current_page, start_line
        block_text = "\n".join(current).strip()
        if block_text:
            blocks.append(
                {
                    "page": current_page,
                    "text": block_text,
                    "start_line": start_line,
                    "end_line": max(start_line, end_line),
                }
            )
        current = []
        current_page = None
        start_line = end_line + 1

    for index, line in enumerate(lines, start=1):
        page_number = _page_number_from_heading(line)
        if page_number is not None:
            if current:
                flush(index - 1)
            current_page = page_number
            start_line = index
            current = [line]
            continue
        if not current and line.strip():
            start_line = index
        current.append(line)

    if current:
        flush(len(lines))
    return blocks


def _split_large_text(text: str, *, target_chars: int = FALLBACK_TARGET_CHARS) -> list[str]:
    paragraphs = re.split(r"\n\s*\n", text.strip())
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in paragraphs:
        piece = paragraph.strip()
        if not piece:
            continue
        if current and current_len + len(piece) > target_chars:
            chunks.append("\n\n".join(current).strip())
            current = []
            current_len = 0
        while len(piece) > FALLBACK_MAX_CHARS:
            chunks.append(piece[:target_chars].strip())
            piece = piece[target_chars:].strip()
        current.append(piece)
        current_len += len(piece)
    if current:
        chunks.append("\n\n".join(current).strip())
    return [chunk for chunk in chunks if chunk]


def _group_page_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_len = 0

    def flush() -> None:
        nonlocal current, current_len
        if not current:
            return
        pages = [item.get("page") for item in current if item.get("page") is not None]
        title = f"Pages {pages[0]}-{pages[-1]}" if len(pages) > 1 else f"Page {pages[0]}" if pages else "Document chunk"
        grouped.append(
            {
                "title": title,
                "text": "\n\n".join(str(item["text"]).strip() for item in current if str(item.get("text", "")).strip()),
                "start_line": int(current[0].get("start_line", 1)),
                "end_line": int(current[-1].get("end_line", 1)),
            }
        )
        current = []
        current_len = 0

    for block in blocks:
        block_text = str(block.get("text", "")).strip()
        if not block_text:
            continue
        next_too_large = current_len + len(block_text) > FALLBACK_TARGET_CHARS
        too_many_pages = len(current) >= FALLBACK_MAX_PAGES_PER_SECTION
        if current and (next_too_large or too_many_pages):
            flush()
        current.append(block)
        current_len += len(block_text)
        if current_len >= FALLBACK_MAX_CHARS:
            flush()
    flush()
    return grouped


def _fallback_sections_from_markdown(text: str) -> tuple[list[dict[str, Any]], str]:
    page_blocks = _split_page_blocks(text)
    if len(page_blocks) > 1:
        return _group_page_blocks(page_blocks), "page_group"

    chunks = _split_large_text(text)
    sections = [
        {
            "title": f"Chunk {index}",
            "text": chunk,
            "start_line": 1,
            "end_line": _line_count(chunk),
        }
        for index, chunk in enumerate(chunks, start=1)
    ]
    return sections, "fixed_length"


def _write_chunked_section_fallback(
    *,
    md_path: Path,
    book_dir: Path,
    sections_dir: Path,
    prefix: str,
    stage: str,
    subject: str,
    publisher: str,
    grade: str,
    book_name: str,
    reason: str,
) -> dict[str, Any]:
    sections_dir.mkdir(parents=True, exist_ok=True)
    text = md_path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return {"written": 0, "fallback_reason": "empty_markdown"}

    sections, strategy = _fallback_sections_from_markdown(text)
    if not sections:
        return {"written": 0, "fallback_reason": "empty_markdown"}

    for old_section in sections_dir.glob("*.md"):
        old_section.unlink()

    (book_dir / "metadata.md").write_text(
        f"# {book_name}\n\nGenerated by chunked fallback segmentation.\n",
        encoding="utf-8",
    )
    index_sections: list[dict[str, Any]] = []
    for order, section in enumerate(sections, start=1):
        title = str(section.get("title") or f"Chunk {order}")
        section_file = f"fallback_{order:03d}.md"
        section_text = str(section.get("text", "")).strip()
        (sections_dir / section_file).write_text(section_text + "\n", encoding="utf-8")
        index_sections.append(
            {
                "order": order,
                "chapter_num": str(order),
                "chapter_title": title,
                "section_num": "",
                "section_title": "",
                "file": section_file,
                "start_line": int(section.get("start_line", 1)),
                "end_line": int(section.get("end_line", _line_count(section_text))),
            }
        )
    index = {
        "book_prefix": prefix,
        "book_name": book_name,
        "stage": stage,
        "subject": subject,
        "grade": grade,
        "publisher": publisher,
        "sections": index_sections,
    }
    index_text = json.dumps(index, ensure_ascii=False, indent=2)
    (book_dir / "sections_index.json").write_text(index_text, encoding="utf-8")
    (book_dir / "section_index.json").write_text(index_text, encoding="utf-8")
    return {
        "written": len(index_sections),
        "fallback_chunked_sections": True,
        "fallback_strategy": strategy,
        "fallback_target_chars": FALLBACK_TARGET_CHARS,
        "fallback_max_pages_per_section": FALLBACK_MAX_PAGES_PER_SECTION,
        "fallback_reason": reason,
    }


def segment_markdown_file(
    md_path: Path,
    output_root: Path,
    *,
    book_prefix: str | None = None,
    stage: str = "",
    subject: str = "",
    publisher: str = "",
    grade: str = "",
    book_name: str | None = None,
    keep_images: bool = True,
    filter_math_columns: bool = False,
    overwrite: bool = False,
) -> dict[str, object]:
    """Segment one converted textbook Markdown file using the K12 rules.

    The signature and manifest shape match the previous FaMAS segmentation API.
    """

    del filter_math_columns  # The K12 implementations own their filtering rules.

    md_path = Path(md_path).resolve()
    output_root = Path(output_root).resolve()
    if not md_path.exists():
        raise FileNotFoundError(f"missing markdown file: {md_path}")
    if md_path.suffix.lower() != ".md":
        raise ValueError(f"input must be a markdown file: {md_path}")

    impl = _select_impl(stage, grade)
    prefix = book_prefix or sanitize_token(md_path.stem)
    record = impl.BookRecord(
        book_prefix=prefix,
        source_md=md_path,
        stage=stage,
        subject=subject,
        publisher=publisher,
        grade=grade,
        book_name=book_name or md_path.stem,
        source_input=None,
    )

    ok, status, info = impl.write_book_outputs(record, output_root, overwrite=overwrite)
    book_dir = output_root.resolve() / "segmentation" / prefix
    sections_dir = book_dir / "sections"

    if ok:
        written = _ensure_ordered_index(book_dir, sections_dir, int(info.get("written", 0) or 0))
        info = {**info, "written": written, "index_synced_to_files": True}
        images_dir, images_copied = _copy_images(md_path, sections_dir) if keep_images else (str(sections_dir / "images"), 0)
    elif status in {"no_segments", "no_blocks_from_index"}:
        fallback_info = _write_chunked_section_fallback(
            md_path=md_path,
            book_dir=book_dir,
            sections_dir=sections_dir,
            prefix=prefix,
            stage=stage,
            subject=subject,
            publisher=publisher,
            grade=grade,
            book_name=book_name or md_path.stem,
            reason=status,
        )
        if fallback_info.get("written"):
            ok = True
            status = "fallback_chunked_sections"
            info = {**info, **fallback_info}
            images_dir, images_copied = _copy_images(md_path, sections_dir) if keep_images else (str(sections_dir / "images"), 0)
        else:
            info = {**info, **fallback_info}
            images_dir, images_copied = str(sections_dir / "images"), 0
    else:
        images_dir, images_copied = str(sections_dir / "images"), 0

    return {
        "ok": ok,
        "status": status,
        "book_prefix": prefix,
        "source_md": str(md_path),
        "output_dir": str(book_dir),
        "sections_dir": str(sections_dir),
        "sections_index": str(book_dir / "sections_index.json"),
        "metadata": str(book_dir / "metadata.md"),
        "images_dir": images_dir,
        "images_copied": images_copied,
        "sectioner": impl.__name__,
        "info": info,
    }
