"""Build SectionContext objects and sample markdown windows for Schema Agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
import json
import random
from pathlib import Path
from typing import Any


@dataclass
class SectionContext:
    section_id: str
    markdown_path: str
    markdown_file: str
    markdown_text_or_window: str
    textbook: str
    subject: str
    publisher: str
    grade: str
    section: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SampleWindow:
    window_index: int
    start_block: int
    end_block: int
    estimated_tokens: int

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SampleUnit:
    sample_id: str
    round_id: str
    section_context: SectionContext
    window: SampleWindow

    def to_json(self) -> dict[str, Any]:
        return {
            "sample_id": self.sample_id,
            "round_id": self.round_id,
            "section_context": self.section_context.to_json(),
            "window": self.window.to_json(),
        }


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // 2)


def load_sections_index(path: Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("sections_index must be a JSON object")
    sections = data.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ValueError("sections_index requires non-empty sections")
    for section in sections:
        if not isinstance(section, dict) or not section.get("file"):
            raise ValueError("each section metadata item requires file")
    return data


def build_section_contexts(enhanced_md_paths: list[Path], sections_index_path: Path) -> list[SectionContext]:
    if not enhanced_md_paths:
        raise ValueError("at least one --enhanced-md path is required")
    index = load_sections_index(sections_index_path)
    by_file = {str(item["file"]): item for item in index["sections"]}
    contexts: list[SectionContext] = []
    for raw_path in enhanced_md_paths:
        path = Path(raw_path)
        markdown_file = path.name
        section = by_file.get(markdown_file)
        if section is None:
            raise ValueError(f"no section metadata found for enhanced markdown file: {markdown_file}")
        if not path.exists() or not path.is_file():
            raise ValueError(f"enhanced markdown file does not exist: {path}")
        order = int(section.get("order", len(contexts) + 1))
        contexts.append(
            SectionContext(
                section_id=f"s{order:03d}",
                markdown_path=str(path.resolve()),
                markdown_file=markdown_file,
                markdown_text_or_window=path.read_text(encoding="utf-8"),
                textbook=str(index.get("textbook", "")),
                subject=str(index.get("subject", "")),
                publisher=str(index.get("publisher", "")),
                grade=str(index.get("grade", "")),
                section={str(key): value for key, value in section.items()},
            )
        )
    return contexts


def split_markdown_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    blocks: list[str] = []
    current: list[str] = []
    in_ipa_note = False

    def flush() -> None:
        nonlocal current
        if current:
            blocks.append("\n".join(current).strip())
            current = []

    for line in lines:
        if "[!NOTE] Image Processing Agent" in line:
            flush()
            current = [line]
            in_ipa_note = True
            continue
        if in_ipa_note:
            if line.startswith(">") or not line.strip():
                current.append(line)
                continue
            flush()
            in_ipa_note = False
            current.append(line)
            continue
        if not line.strip():
            flush()
            continue
        if line.startswith("#"):
            flush()
        current.append(line)
    flush()
    return [block for block in blocks if block]


def _windows_for_context(context: SectionContext, max_window_tokens: int) -> list[tuple[str, SampleWindow]]:
    blocks = split_markdown_blocks(context.markdown_text_or_window)
    if not blocks:
        blocks = [context.markdown_text_or_window]
    windows: list[tuple[str, SampleWindow]] = []
    current: list[str] = []
    start_block = 0
    current_tokens = 0
    for index, block in enumerate(blocks):
        block_tokens = _estimate_tokens(block)
        if current and current_tokens + block_tokens > max_window_tokens:
            text = "\n\n".join(current)
            windows.append(
                (
                    text,
                    SampleWindow(
                        window_index=len(windows),
                        start_block=start_block,
                        end_block=index - 1,
                        estimated_tokens=_estimate_tokens(text),
                    ),
                )
            )
            current = []
            current_tokens = 0
            start_block = index
        current.append(block)
        current_tokens += block_tokens
    if current:
        text = "\n\n".join(current)
        windows.append(
            (
                text,
                SampleWindow(
                    window_index=len(windows),
                    start_block=start_block,
                    end_block=len(blocks) - 1,
                    estimated_tokens=_estimate_tokens(text),
                ),
            )
        )
    return windows


def sample_section_windows(
    contexts: list[SectionContext],
    rounds: int,
    seed: int,
    max_input_tokens: int,
) -> list[SampleUnit]:
    if rounds <= 0:
        raise ValueError("rounds must be positive")
    if max_input_tokens <= 0:
        raise ValueError("max_input_tokens must be positive")
    if not contexts:
        raise ValueError("contexts must be non-empty")
    max_window_tokens = max(512, max_input_tokens // max(1, min(rounds, len(contexts))) // 2)
    all_windows: list[tuple[SectionContext, str, SampleWindow]] = []
    for context in contexts:
        for window_text, window in _windows_for_context(context, max_window_tokens):
            all_windows.append((context, window_text, window))
    rng = random.Random(seed)
    samples: list[SampleUnit] = []
    for round_index in range(1, rounds + 1):
        round_id = f"round_{round_index:03d}"
        if round_index <= len(contexts):
            preferred = [item for item in all_windows if item[0].section_id == contexts[round_index - 1].section_id]
            context, window_text, window = preferred[0]
        else:
            context, window_text, window = rng.choice(all_windows)
        section_context = replace(context, markdown_text_or_window=window_text)
        sample_id = f"{round_id}_{context.section_id}_w{window.window_index:03d}"
        samples.append(SampleUnit(sample_id=sample_id, round_id=round_id, section_context=section_context, window=window))
    return samples
