"""Small config loader for the package-local K12 sectioner CLIs."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import yaml


_ENV_VAR_RE = re.compile(r"\$\{(\w+)\}")


def _expand_env(value: str) -> str:
    def _repl(match: re.Match[str]) -> str:
        return os.environ.get(match.group(1), "")

    return _ENV_VAR_RE.sub(_repl, value)


def _resolve_value(value: Any) -> Any:
    if isinstance(value, str):
        return _expand_env(value)
    if isinstance(value, dict):
        return {key: _resolve_value(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_resolve_value(child) for child in value]
    return value


class PipelineConfig:
    """Parsed K12 segmentation config with paths resolved from the config file."""

    def __init__(self, raw: dict[str, Any], config_dir: Path) -> None:
        self._raw = _resolve_value(raw or {})
        self._config_dir = config_dir.resolve()

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return (self._config_dir / path).resolve()

    @property
    def books_yaml(self) -> Path:
        return self._resolve_path(self._raw.get("paths", {}).get("books_yaml", "../books.yaml"))

    @property
    def workspace_dir(self) -> Path:
        return self._resolve_path(self._raw.get("paths", {}).get("workspace_dir", "../workspace"))

    @property
    def output_dir(self) -> Path:
        return self._resolve_path(self._raw.get("paths", {}).get("output_dir", "../data"))

    @property
    def input_dir(self) -> Path:
        return self._resolve_path(self._raw.get("paths", {}).get("input_dir", "."))

    def load_books(self, *, require_source: bool = False) -> list[dict[str, Any]]:
        data = yaml.safe_load(self.books_yaml.read_text(encoding="utf-8")) or {}
        books = data.get("books", [])
        if not isinstance(books, list):
            raise ValueError("books.yaml must contain a top-level 'books' list")

        required = {"book_prefix", "subject", "stage", "grade", "publisher"}
        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for idx, raw_book in enumerate(books, start=1):
            if not isinstance(raw_book, dict):
                raise ValueError(f"books[{idx}] must be an object")
            missing = [key for key in required if not str(raw_book.get(key, "")).strip()]
            has_any_source = any(str(raw_book.get(key, "")).strip() for key in ("source_pdf", "source_md"))
            if require_source and not has_any_source:
                missing.append("source_pdf|source_md")
            if missing:
                raise ValueError(f"books[{idx}] missing required fields: {', '.join(missing)}")
            book = dict(raw_book)
            book["book_prefix"] = str(book["book_prefix"]).strip()
            if book["book_prefix"] in seen:
                raise ValueError(f"duplicate book_prefix in books.yaml: {book['book_prefix']}")
            seen.add(book["book_prefix"])
            for key in ("source_pdf", "source_md"):
                if key in book:
                    book[key] = str(book.get(key, "")).strip()
            normalized.append(book)
        return normalized

    def _resolve_book_path(self, book: dict[str, Any], *keys: str) -> Path | None:
        for key in keys:
            value = str(book.get(key, "")).strip()
            if not value:
                continue
            path = Path(value)
            if path.is_absolute():
                return path
            return (self.books_yaml.parent / path).resolve()
        return None

    def resolve_book_source(self, book: dict[str, Any]) -> Path | None:
        return self._resolve_book_path(book, "source_pdf", "source_md")

    def resolve_book_markdown(self, book: dict[str, Any]) -> Path | None:
        return self._resolve_book_path(book, "source_md")


def load_config(config_path: str | None = None) -> PipelineConfig:
    if config_path is None:
        config_path_obj = Path(__file__).resolve().parents[4] / "config" / "k12_section_high.yaml"
    else:
        config_path_obj = Path(config_path)
    raw = yaml.safe_load(config_path_obj.read_text(encoding="utf-8")) or {}
    return PipelineConfig(raw, config_path_obj.parent)
