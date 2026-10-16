"""Fixed-slot publishing rules for shared MAS standards.

Each standard-producing agent owns one registered slot in the shared
standards directory. Publishing a slot overwrites that slot's fixed files and
does not delete or mutate files from any other slot.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


@dataclass(frozen=True)
class StandardSlot:
    slot_id: str
    owner_agent: str
    description: str
    filenames: list[str]


STANDARD_SLOTS: dict[str, StandardSlot] = {
    "ipa_note": StandardSlot(
        slot_id="ipa_note",
        owner_agent="IPA",
        description="IPA enhanced Markdown note format standard.",
        filenames=["ipa_enhanced_markdown_note_v1.md"],
    ),
    "schema_agent": StandardSlot(
        slot_id="schema_agent",
        owner_agent="SA",
        description="Schema Agent label/property KG schema standard.",
        filenames=["kg_schema_label_property_v2.json", "kg_schema_label_property_v2_note.md"],
    ),
}


def resolve_published_schema_path(standards_dir: Path) -> Path:
    """Return the canonical published schema_agent JSON path in standards_dir."""

    slot = STANDARD_SLOTS["schema_agent"]
    json_name = next(filename for filename in slot.filenames if filename.endswith(".json"))
    return Path(standards_dir) / json_name


def _validate_slot_files(slot: StandardSlot, files: Mapping[str, str]) -> None:
    expected = set(slot.filenames)
    actual = set(files)
    if actual != expected:
        raise ValueError(
            f"published file set does not match registered slot {slot.slot_id!r}; "
            f"expected {sorted(expected)}, got {sorted(actual)}"
        )
    for filename, content in files.items():
        if Path(filename).name != filename:
            raise ValueError(f"standard slot filename must be a plain filename: {filename}")
        if not isinstance(content, str):
            raise TypeError(f"standard slot content for {filename} must be text")


def write_standard_slot(slot_id: str, files: Mapping[str, str], standards_dir: Path) -> dict[str, Any]:
    """Overwrite the fixed files registered for one standards slot.

    The writer is intentionally strict: callers must provide exactly the
    filenames registered to the slot. This prevents one agent from accidentally
    adding timestamped variants or overwriting another agent's standard.
    """

    if slot_id not in STANDARD_SLOTS:
        raise ValueError(f"unknown standard slot: {slot_id}")
    slot = STANDARD_SLOTS[slot_id]
    _validate_slot_files(slot, files)

    standards_dir = Path(standards_dir)
    standards_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    for filename in slot.filenames:
        path = standards_dir / filename
        path.write_text(files[filename], encoding="utf-8")
        written[filename] = str(path.resolve())

    return {
        "published": True,
        "slot_id": slot.slot_id,
        "owner_agent": slot.owner_agent,
        "files": written,
    }


def publish_ipa_note_standard(content: str, standards_dir: Path) -> dict[str, Any]:
    """Publish the IPA note standard into its fixed shared-standards slot."""

    return write_standard_slot(
        "ipa_note",
        {"ipa_enhanced_markdown_note_v1.md": content},
        standards_dir,
    )
