"""Configuration for MAS pipeline stages."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

import yaml


def project_root() -> Path:
    """Return the MAS project root."""
    return Path(__file__).resolve().parents[3]


class PipelineConfig:
    """Parsed pipeline config with resolved filesystem paths."""

    def __init__(self, raw: Dict[str, Any], config_dir: Path) -> None:
        self._raw = raw
        self._config_dir = config_dir.resolve()

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return (self._config_dir / path).resolve()

    @property
    def input_pdf_dir(self) -> Path:
        return self._resolve_path(self._raw.get("paths", {}).get("input_pdf_dir", "../data/input/pdf"))

    @property
    def output_markdown_dir(self) -> Path:
        return self._resolve_path(
            self._raw.get("paths", {}).get("output_markdown_dir", "../data/output/markdown")
        )

    @property
    def workspace_dir(self) -> Path:
        return self._resolve_path(self._raw.get("paths", {}).get("workspace_dir", "../workspace"))

    @property
    def pdf_to_md_workspace_dir(self) -> Path:
        return self.workspace_dir / "pdf_to_md"

    @property
    def mineru(self) -> Dict[str, Any]:
        return self._raw.get("mineru", {})

    def pdf_to_md_book_dir(self, book_prefix: str) -> Path:
        return self.pdf_to_md_workspace_dir / book_prefix

    def generated_book_dir_for(self, book_prefix: str) -> Path:
        return self.output_markdown_dir / book_prefix

    def generated_book_md_for(self, book_prefix: str) -> Path:
        return self.generated_book_dir_for(book_prefix) / f"{book_prefix}.md"

    def generated_book_manifest_for(self, book_prefix: str) -> Path:
        return self.pdf_to_md_book_dir(book_prefix) / "manifest.json"


def load_config(config_path: Optional[str] = None) -> PipelineConfig:
    """Load MAS pipeline config from YAML."""
    config_file = Path(config_path) if config_path else project_root() / "config" / "default.yaml"
    with config_file.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return PipelineConfig(raw, config_file.parent)
