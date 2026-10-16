"""Shared data models for KG Extraction MAS."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
import hashlib
from pathlib import Path
from typing import Any, Sequence


CODE_ROOT = Path(__file__).resolve().parents[4]


@dataclass
class IpaImageEvidence:
    """Parsed IPA image-note evidence from enhanced Markdown.

    Args:
        evidence_key: Stable key built from source path, file, section, image, and local id.
        local_image_id: Local image sequence id within a section context.
        image_markdown: Original Markdown image link.
        image_path: Image path from Markdown.
        source_markdown_path: Enhanced Markdown source path.
        markdown_file: Enhanced Markdown filename.
        section_id: Bound section id.
        image_type: IPA image type id.
        kg_value: IPA KG value.
        result_text: IPA final result text.
        result_status: Normalized result status.
        eligible_for_fact_evidence: Whether this note can support KG facts.
        supplementary_for_fact_evidence: Whether this note can support KG facts only as downgraded supplementary evidence.
        nearest_heading: Nearest heading around the note.
        before_blocks: Nearby preceding Markdown blocks.
        after_blocks: Nearby following Markdown blocks.
    """

    evidence_key: str
    local_image_id: str
    image_markdown: str
    image_path: str
    source_markdown_path: str
    markdown_file: str
    section_id: str
    image_type: str
    kg_value: str
    result_text: str
    result_status: str
    eligible_for_fact_evidence: bool
    nearest_heading: str
    before_blocks: list[str]
    after_blocks: list[str]
    supplementary_for_fact_evidence: bool = False

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-safe representation."""

        return jsonable(self)


@dataclass
class ExtractionSectionContext:
    """Source unit shared by KG extraction agents.

    Args:
        source_context_id: Stable context id including section and filename.
        section_id: Section id such as `s001`.
        markdown_path: Enhanced Markdown path.
        markdown_file: Enhanced Markdown filename.
        markdown_text: Full enhanced Markdown text.
        textbook_profile: Textbook metadata from sections_index.
        section_metadata: Matching section metadata object.
        ipa_image_evidence: Parsed IPA image evidence records.
    """

    source_context_id: str
    section_id: str
    markdown_path: Path
    markdown_file: str
    markdown_text: str
    textbook_profile: dict[str, Any]
    section_metadata: dict[str, Any]
    ipa_image_evidence: list[IpaImageEvidence]

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-safe representation."""

        return jsonable(self)


@dataclass
class ValidationFeedback:
    """Distilled VA feedback returned to NEA or EEA.

    Args:
        target_type: `node` or `edge`.
        target_id: Candidate id.
        source_context_id: Source context id.
        issue_type: Stable issue type.
        field_path: Affected field path.
        reason: Concise validation reason.
        expected_fix: What extractor should change.
        evidence_hint: Evidence hint for repair.
        original_item: Complete original candidate item.
    """

    target_type: str
    target_id: str
    source_context_id: str
    issue_type: str
    field_path: str
    reason: str
    expected_fix: str
    evidence_hint: str
    original_item: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        """Return a JSON-safe representation."""

        return jsonable(self)


@dataclass
class KgExtractionRunConfig:
    """Configuration for one KG Extraction MAS run.

    Args:
        enhanced_md_paths: IPA enhanced Markdown file paths.
        sections_index_path: Section metadata JSON path.
        standards_dir: Shared standards directory.
        schema_path: Published schema v2 path.
        run_id: Optional explicit run id.
        mock: Whether to use deterministic mock agents.
        node_model: NEA model name.
        edge_model: EEA model name.
        standard_model: SdA model name.
        validation_provider: VA provider id.
        validation_model: VA model name.
        validation_base_url: VA OpenAI-compatible base URL.
        validation_api_key_env: Environment variable name for VA API key.
        max_revision_rounds: Maximum VA revision rounds.
        work_root: Intermediate output root.
        output_root: Final KG output root.
        node_batch_size: Number of section contexts per NEA call.
        qwen_timeout_seconds: Text-agent provider timeout seconds.
        qwen_retry_attempts: Text-agent provider retry attempts.
        qwen_timeout_retry_attempts: Text-agent provider timeout retry attempts.
        qwen_timeout_retry_budget_seconds: Text-agent provider timeout retry wall-clock budget.
        qwen_max_tokens: Text-agent provider output token cap.
        qwen_max_input_tokens: Text-agent provider input token cap.
        section_char_limit: Maximum Markdown characters per NEA section slice.
        edge_batch_size: Number of section contexts per EEA call.
        revision_context_window: Characters to keep before/after failed-node evidence in revision prompts.
        revision_stall_threshold: Consecutive same-issue rounds before rejecting a stuck revision item.
        resume: Whether to reuse successful extraction batch checkpoints.
    """

    enhanced_md_paths: list[Path]
    sections_index_path: Path
    standards_dir: Path
    schema_path: Path
    run_id: str | None
    mock: bool
    node_model: str
    edge_model: str
    standard_model: str
    validation_provider: str | None
    validation_model: str | None
    validation_base_url: str | None
    validation_api_key_env: str | None
    max_revision_rounds: int
    work_root: Path = CODE_ROOT / "data" / "intermediate" / "kg_extraction_outputs"
    output_root: Path = CODE_ROOT / "data" / "output" / "kg_extraction_outputs"
    node_batch_size: int = 1
    qwen_timeout_seconds: int = 120
    qwen_retry_attempts: int = 3
    qwen_timeout_retry_attempts: int = 2
    qwen_timeout_retry_budget_seconds: int = 300
    qwen_max_tokens: int = 8192
    qwen_max_input_tokens: int = 64000
    source_context_ids: list[str] = field(default_factory=list)
    section_char_limit: int = 80000
    edge_batch_size: int = 1
    revision_context_window: int = 1000
    revision_stall_threshold: int = 2
    resume: bool = True


def jsonable(value: Any) -> Any:
    """Convert Extraction MAS values into JSON-serializable objects.

    Args:
        value: Dataclass, Path, list, dict, or scalar value.

    Returns:
        JSON-serializable value.
    """

    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value):
        return jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def make_stable_id(prefix: str, parts: Sequence[str]) -> str:
    """Build a deterministic short hash id.

    Args:
        prefix: Stable id prefix.
        parts: Ordered identity parts. Empty parts are ignored.

    Returns:
        ID in `<prefix>_<hash12>` form.
    """

    normalized = "␟".join(str(part).strip() for part in parts if str(part).strip())
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}_{digest}"
