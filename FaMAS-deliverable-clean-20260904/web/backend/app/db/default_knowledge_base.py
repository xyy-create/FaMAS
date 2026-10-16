from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

DEFAULT_KNOWLEDGE_BASE_NAME = "小初高知识全集"
DEFAULT_KNOWLEDGE_BASE_SLUG = "xiaochugao-zhishiku-quanji"
DEFAULT_KNOWLEDGE_BASE_SOURCE_DIR_NAME = "默认知识库"
CHEMISTRY_KNOWLEDGE_BASE_NAME = "化学"
CHEMISTRY_KNOWLEDGE_BASE_SLUG = "chemistry"
CHEMISTRY_BOOK_TITLE = "普通高中教科书·化学必修第一册"
CHEMISTRY_BOOK_SOURCE_DIR_NAME = "02_high_school_化学_passed_普通高中教科书·化学必修第一册"
CHEMISTRY_BOOK_FILENAME = "普通高中教科书·化学必修第一册.pdf"


@dataclass(frozen=True)
class DefaultKnowledgeBookSpec:
    index: int
    stage_key: str
    stage_label: str
    subject: str
    status: str
    title: str
    directory: Path
    filename: str
    grade: str
    publisher: str
    textbook_version: str


def default_knowledge_base_source_root(project_dir: Path) -> Path:
    return project_dir / DEFAULT_KNOWLEDGE_BASE_SOURCE_DIR_NAME


def load_default_knowledge_book_specs(project_dir: Path) -> list[DefaultKnowledgeBookSpec]:
    source_root = default_knowledge_base_source_root(project_dir)
    if not source_root.exists():
        return []

    specs: list[DefaultKnowledgeBookSpec] = []
    for directory in sorted(path for path in source_root.iterdir() if path.is_dir()):
        spec = _parse_book_directory(directory)
        if spec is not None:
            specs.append(spec)
    return specs


def _parse_book_directory(directory: Path) -> DefaultKnowledgeBookSpec | None:
    parts = directory.name.split("_", 4)
    if len(parts) != 5:
        return None

    index_text, stage_key, subject, status, title = parts
    try:
        index = int(index_text)
    except ValueError:
        return None

    return DefaultKnowledgeBookSpec(
        index=index,
        stage_key=stage_key,
        stage_label=_stage_label(stage_key),
        subject=subject,
        status=status,
        title=title,
        directory=directory,
        filename=f"{title}.pdf",
        grade=_grade_label(title, stage_key),
        publisher="苏教版",
        textbook_version=_textbook_version(title),
    )


def _stage_label(stage_key: str) -> str:
    return {
        "high_school": "高中",
        "junior_high": "初中",
        "primary_school": "小学",
    }.get(stage_key, stage_key)


def _grade_label(title: str, stage_key: str) -> str:
    junior_match = re.search(r"([一二三四五六七八九十\d]+年级[上下]册)", title)
    if junior_match:
        return junior_match.group(1)

    high_school_match = re.search(
        r"(选择性必修\s*[一二三四五六七八九十\d]+|选择性必修\d+|必修\s*[一二三四五六七八九十\d]+册|必修\s*[一二三四五六七八九十\d]+)",
        title,
    )
    if high_school_match:
        return " ".join(high_school_match.group(1).split())

    return _stage_label(stage_key)


def _textbook_version(title: str) -> str:
    if "选择性必修" in title:
        return "选择性必修"
    if "必修" in title:
        return "必修"
    return "义务教育"
