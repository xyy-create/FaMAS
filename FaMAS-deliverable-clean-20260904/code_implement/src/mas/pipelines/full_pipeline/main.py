"""End-to-end PDF to KG orchestration for FaMAS.

This module is intentionally a thin coordinator. It reuses the existing
PDF-to-Markdown, segmentation, ITA, IPA, and KG extraction modules, then writes
one human-readable audit report for the whole run.
"""

from __future__ import annotations

import argparse
import importlib.util
from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import time
from typing import Any, Sequence

from mas.common import progress
from mas.config.models import get_model
from mas.config.pipeline import load_config
from mas.pipelines.common.cost import estimate_cost_rmb
from mas.pipelines.common.usage_tracker import reset_usage, usage_snapshot
from mas.pipelines.common.standards_registry import resolve_published_schema_path
from mas.pipelines.image_processing.run import run_pipeline as run_ipa_pipeline
from mas.pipelines.image_taxonomy.run import TaxonomyRunConfig, run_pipeline as run_taxonomy_pipeline
from mas.pipelines.kg_extraction.agents import (
    DEFAULT_TEXT_MODEL,
    DEFAULT_VALIDATION_API_KEY_ENV,
    DEFAULT_VALIDATION_BASE_URL,
    DEFAULT_VALIDATION_MODEL,
    DEFAULT_VALIDATION_PROVIDER,
)
from mas.pipelines.kg_extraction.models import KgExtractionRunConfig
from mas.pipelines.kg_extraction.run import run_pipeline as run_kg_pipeline
from mas.pipelines.k12_sectioner import segment_markdown_file, sanitize_token
from mas.pipelines.pdf_to_md.prepare import prepare_from_pdf
from mas.pipelines.schema_agent.run import SchemaRunConfig, run_pipeline as run_schema_agent_pipeline


CODE_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_TEXTBOOK_DIR = Path("textbook")
DEFAULT_REPORT_DIR = CODE_ROOT / "data" / "output" / "full_pipeline_reports"
DEFAULT_STANDARDS_DIR = CODE_ROOT / "data" / "standards"
DEFAULT_SCHEMA_PATH = DEFAULT_STANDARDS_DIR / "kg_schema_label_property_v2.json"
DEFAULT_API_KEY_FILE = None
DEFAULT_RUN_PREFIX = "full_pipeline"
PDF_FALLBACK_OUTPUT_ROOT = CODE_ROOT / "data" / "output" / "markdown" / "pdf_text_fallback"
DEFAULT_SCHEMA_AGENT_INPUT_DIR = CODE_ROOT / "data" / "input" / "schema_agent"
DEFAULT_SA_HUMAN_RULES = DEFAULT_SCHEMA_AGENT_INPUT_DIR / "human_standards" / "human_rules_template.md"
DEFAULT_SA_BASE_SCHEMA = DEFAULT_SCHEMA_AGENT_INPUT_DIR / "human_standards" / "base_schema_template.json"
DEFAULT_ITA_MODEL_CONFIG = get_model("ita_vision")
DEFAULT_IPA_GENERATOR_CONFIG = get_model("ipa_generator")
DEFAULT_IPA_VERIFIER_CONFIG = get_model("ipa_verifier")
DEFAULT_SCHEMA_AGENT_CONFIG = get_model("schema_agent")
DEFAULT_VISION_MODEL = str(DEFAULT_ITA_MODEL_CONFIG.get("name", "qwen3-vl-flash"))
DEFAULT_VISION_API_KEY_ENV = str(DEFAULT_ITA_MODEL_CONFIG.get("api_key_env", "DASHSCOPE_API_KEY"))
DEFAULT_IPA_GENERATOR_API_KEY_ENV = str(DEFAULT_IPA_GENERATOR_CONFIG.get("api_key_env", "DASHSCOPE_API_KEY"))
DEFAULT_VERIFY_VISION_MODEL = str(DEFAULT_IPA_VERIFIER_CONFIG.get("name", "qwen-vl-plus"))
DEFAULT_VERIFY_VISION_API_KEY_ENV = str(DEFAULT_IPA_VERIFIER_CONFIG.get("api_key_env", "DASHSCOPE_API_KEY"))
DEFAULT_SCHEMA_AGENT_MODEL = str(DEFAULT_SCHEMA_AGENT_CONFIG.get("name", "qwen3.5-flash"))


@dataclass
class FullPipelineConfig:
    """Configuration for one end-to-end FaMAS run."""

    pdf_path: Path
    api_key_file: Path | None = DEFAULT_API_KEY_FILE
    report_dir: Path = DEFAULT_REPORT_DIR
    standards_dir: Path = DEFAULT_STANDARDS_DIR
    schema_path: Path = DEFAULT_SCHEMA_PATH
    run_id: str | None = None
    run_id_explicit: bool = False
    subject: str = ""
    grade: str = "high_school"
    publisher: str = "sujiao"
    mock: bool = False
    stop_at: str = "kg"
    overwrite_pdf_md: bool = False
    allow_pdf_text_fallback: bool = True
    taxonomy_sample_size: int = 200
    taxonomy_sample_size_explicit: bool = False
    taxonomy_sample_ratio: float = 0.6
    taxonomy_batch_size: int = 20
    taxonomy_max_parallel_workers: int = 2
    ipa_batch_size: int = 10
    vision_model: str = DEFAULT_VISION_MODEL
    verify_vision_model: str = DEFAULT_VERIFY_VISION_MODEL
    critic_revision_rounds: int = 5
    ipa_resume: bool = True
    per_image_hard_timeout_seconds: int = 600
    enable_schema_agent: bool = True
    reuse_schema_path_when_schema_agent_disabled: bool = False
    publish_schema_standards: bool = True
    sa_human_rules: Path = DEFAULT_SA_HUMAN_RULES
    sa_base_schema: Path = DEFAULT_SA_BASE_SCHEMA
    sa_rounds: int = 3
    node_model: str = DEFAULT_TEXT_MODEL
    edge_model: str = DEFAULT_TEXT_MODEL
    standard_model: str = DEFAULT_TEXT_MODEL
    sa_model: str = DEFAULT_SCHEMA_AGENT_MODEL
    validation_provider: str = DEFAULT_VALIDATION_PROVIDER
    validation_model: str = DEFAULT_VALIDATION_MODEL
    validation_base_url: str = DEFAULT_VALIDATION_BASE_URL
    validation_api_key_env: str = DEFAULT_VALIDATION_API_KEY_ENV
    max_revision_rounds: int = 5
    allow_schema_mismatch: bool = False
    llm_seed: int | None = None
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
    resume: bool = True
    segment_output_root: Path = CODE_ROOT / "data" / "intermediate" / "markdown_segments" / "full_pipeline"
    taxonomy_output_root: Path = CODE_ROOT / "data" / "intermediate" / "taxonomy_outputs" / "full_pipeline"
    ipa_output_root: Path = CODE_ROOT / "data" / "intermediate" / "ipa_outputs" / "full_pipeline"
    schema_agent_work_root: Path = CODE_ROOT / "data" / "intermediate" / "schema_outputs" / "full_pipeline"
    schema_agent_output_root: Path = CODE_ROOT / "data" / "output" / "schema_outputs" / "full_pipeline"
    kg_work_root: Path = CODE_ROOT / "data" / "intermediate" / "kg_extraction_outputs"
    kg_output_root: Path = CODE_ROOT / "data" / "output" / "kg_extraction_outputs"


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def _today_stamp() -> str:
    return datetime.now().strftime("%Y%m%d")


def make_full_run_id(label: str | None = None) -> str:
    book_name = sanitize_token(label) if label else DEFAULT_RUN_PREFIX
    return f"{book_name}_{_today_stamp()}"


def discover_default_pdf(textbook_dir: Path = DEFAULT_TEXTBOOK_DIR) -> Path:
    """Return the only PDF in the default high-school textbook directory."""

    pdfs = sorted(Path(textbook_dir).glob("*.pdf"))
    if len(pdfs) == 1:
        return pdfs[0]
    if not pdfs:
        raise ValueError(f"no PDF found in {textbook_dir}; pass --pdf <path> to specify one")
    listing = "\n".join(f"  - {pdf}" for pdf in pdfs)
    raise ValueError(
        f"found {len(pdfs)} PDFs in {textbook_dir}; pass --pdf <path> to choose one.\n"
        f"candidates:\n{listing}"
    )


def verify_schema_matches_published(schema_path: Path, standards_dir: Path) -> dict[str, Any]:
    """Check schema_path against the published schema_agent slot file."""

    from mas.pipelines.common.standards_registry import resolve_published_schema_path

    schema_path = Path(schema_path)
    published = resolve_published_schema_path(Path(standards_dir))
    info: dict[str, Any] = {
        "schema_path": str(schema_path),
        "published_path": str(published),
        "match": False,
        "schema_version": "",
        "published_version": "",
    }
    if not schema_path.exists():
        raise RuntimeError(f"schema_path does not exist: {schema_path}")
    if not published.exists():
        info["warning"] = "no published schema_agent slot found; skipped strict check"
        info["match"] = True
        return info

    def _version(path: Path) -> str:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return ""
        if not isinstance(data, dict):
            return ""
        return str(data.get("schema_version", ""))

    info["schema_version"] = _version(schema_path)
    info["published_version"] = _version(published)
    same_path = schema_path.resolve() == published.resolve()
    same_version = bool(info["schema_version"]) and info["schema_version"] == info["published_version"]
    info["match"] = same_path or same_version
    return info


def load_api_keys_to_env(api_key_file: Path | None) -> dict[str, Any]:
    """Load qwen/deepseek keys into env vars without returning secret values."""

    if api_key_file is None:
        return {"loaded": False, "env_vars": [], "source": ""}
    path = Path(api_key_file)
    if not path.exists():
        return {"loaded": False, "env_vars": [], "source": str(path), "warning": "api key file not found"}
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    env_vars: list[str] = []
    if lines:
        os.environ["DASHSCOPE_API_KEY"] = lines[0]
        env_vars.append("DASHSCOPE_API_KEY")
    if len(lines) >= 2:
        os.environ["DEEPSEEK_API_KEY"] = lines[1]
        env_vars.append("DEEPSEEK_API_KEY")
    return {"loaded": bool(env_vars), "env_vars": env_vars, "source": str(path), "line_count": len(lines)}


def _candidate_image_dirs_from_selected(selected_markdown: Path) -> list[Path]:
    parent = selected_markdown.parent
    return [
        parent / "images",
        parent.parent / "images",
        parent / "auto" / "images",
        parent.parent / "auto" / "images",
    ]


def _count_files(path: Path) -> int:
    try:
        return sum(1 for item in path.iterdir() if item.is_file())
    except OSError:
        return 0


def _warn(message: str) -> None:
    print(f"[WARN] {message}", file=os.sys.stderr)


def find_image_source_dir(pdf_info: dict[str, Any]) -> Path | None:
    """Find the MinerU image directory supporting the selected Markdown."""

    selected = pdf_info.get("selected_markdown") or pdf_info.get("prepared_markdown")
    if selected:
        selected_path = Path(str(selected))
        for candidate in _candidate_image_dirs_from_selected(selected_path):
            if candidate.exists() and any(item.is_file() for item in candidate.iterdir()):
                return candidate
    raw_dir = pdf_info.get("raw_dir")
    if raw_dir:
        raw = Path(str(raw_dir))
        auto_images = raw / "auto" / "images"
        if auto_images.exists() and any(item.is_file() for item in auto_images.iterdir()):
            return auto_images
        image_dirs = [path for path in raw.rglob("images") if path.is_dir()]
        image_dirs.sort(key=_count_files, reverse=True)
        for candidate in image_dirs:
            if any(item.is_file() for item in candidate.iterdir()):
                return candidate
    stem = ""
    source_pdf = pdf_info.get("source_pdf")
    if source_pdf:
        stem = Path(str(source_pdf)).stem
    if not stem and selected:
        stem = Path(str(selected)).stem
    if stem:
        try:
            workspace = load_config(None).pdf_to_md_workspace_dir
        except Exception:
            workspace = Path("code_implement") / "workspace" / "pdf_to_md"
        fallback_root = Path(workspace) / stem / "mineru_output"
        image_dirs = [path for path in fallback_root.rglob("images") if path.is_dir()] if fallback_root.exists() else []
        image_dirs.sort(key=_count_files, reverse=True)
        for candidate in image_dirs:
            if any(item.is_file() for item in candidate.iterdir()):
                return candidate
    return None


def _extract_pdf_text_with_pypdf(pdf_path: Path) -> tuple[str, int]:
    from pypdf import PdfReader  # type: ignore

    reader = PdfReader(str(pdf_path))
    pages = [(page.extract_text() or "").strip() for page in reader.pages]
    markdown, _info = _format_pdf_pages_as_markdown(Path(pdf_path).stem, pages)
    return markdown.strip(), len(reader.pages)


def _extract_pdf_text_with_pdfplumber(pdf_path: Path) -> tuple[str, int]:
    import pdfplumber  # type: ignore

    pages = []
    with pdfplumber.open(str(pdf_path)) as pdf:
        for page in pdf.pages:
            pages.append((page.extract_text() or "").strip())
        markdown, _info = _format_pdf_pages_as_markdown(Path(pdf_path).stem, pages)
        return markdown.strip(), len(pdf.pages)


def _extract_pdf_text_with_fitz(pdf_path: Path) -> tuple[str, int]:
    import fitz  # type: ignore

    doc = fitz.open(str(pdf_path))
    pages = []
    try:
        for page in doc:
            pages.append((page.get_text("text") or "").strip())
        markdown, _info = _format_pdf_pages_as_markdown(Path(pdf_path).stem, pages)
        return markdown.strip(), len(doc)
    finally:
        doc.close()


MOJIBAKE_MARKERS = (
    "涓",
    "鍥",
    "鏂",
    "绗",
    "鈥",
    "锛",
    "锘",
    "鐨",
    "鏄",
    "瀛",
    "闈",
    "浠",
    "殑",
    "€",
)


def _cjk_count(text: str) -> int:
    return sum("\u4e00" <= char <= "\u9fff" for char in text)


def _mojibake_marker_count(text: str) -> int:
    return sum(str(text).count(marker) for marker in MOJIBAKE_MARKERS)


def _repair_pdf_text_mojibake(text: str) -> tuple[str, dict[str, Any]]:
    """Repair common pypdf Chinese mojibake without touching normal text."""

    original = str(text)
    original_markers = _mojibake_marker_count(original)
    original_cjk = _cjk_count(original)
    if original_markers < 20:
        return original, {
            "applied": False,
            "reason": "few_mojibake_markers",
            "markers_before": original_markers,
            "markers_after": original_markers,
        }

    best = original
    best_markers = original_markers
    best_cjk = original_cjk
    best_encoding = ""
    for encoding in ["gb18030", "gbk", "cp936"]:
        try:
            candidate = original.encode(encoding, errors="replace").decode("utf-8", errors="replace")
        except (LookupError, UnicodeError):
            continue
        candidate_markers = _mojibake_marker_count(candidate)
        candidate_cjk = _cjk_count(candidate)
        if candidate_markers < best_markers and candidate_cjk >= max(1, int(original_cjk * 0.6)):
            best = candidate
            best_markers = candidate_markers
            best_cjk = candidate_cjk
            best_encoding = encoding

    applied = best is not original and best_markers <= max(5, int(original_markers * 0.35))
    if not applied:
        return original, {
            "applied": False,
            "reason": "repair_not_confident",
            "markers_before": original_markers,
            "markers_after": best_markers,
            "cjk_before": original_cjk,
            "cjk_after": best_cjk,
        }
    return best, {
        "applied": True,
        "encoding": best_encoding,
        "markers_before": original_markers,
        "markers_after": best_markers,
        "cjk_before": original_cjk,
        "cjk_after": best_cjk,
    }


def _normalize_pdf_heading_text(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text)).strip()
    text = text.replace("\ue010", ".")
    text = re.sub(r"([０-９])\s*[．.]\s*([０-９])", r"\1．\2", text)
    text = re.sub(r"([0-9])\s*[．.]\s*([0-9])", r"\1.\2", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _is_page_noise(line: str) -> bool:
    compact = re.sub(r"\s+", "", line)
    if not compact:
        return True
    if compact in {"书书书"}:
        return True
    if re.fullmatch(r"[０-９0-9]+", compact):
        return True
    if re.fullmatch(r"[０-９0-9]+第[０-９0-9]+章", compact):
        return True
    if "选择性必修第二册数学" in compact:
        return True
    return False


def _looks_like_pdf_heading(line: str) -> bool:
    text = _normalize_pdf_heading_text(line)
    compact = re.sub(r"\s+", "", text)
    if re.fullmatch(r"第[０-９0-9一二三四五六七八九十]+章.+", compact):
        return True
    if re.fullmatch(r"[０-９0-9]+[．.][０-９0-9]+([．.][０-９0-9]+)?\s*.+", text):
        return True
    if re.fullmatch(r"(问题与探究|阅读|应用与建模|专题|案例分析|课题推荐|附录)\s+.+", text):
        return True
    return False


def _looks_like_structural_pdf_heading(line: str) -> bool:
    if not _looks_like_pdf_heading(line):
        return False
    text = _normalize_pdf_heading_text(line)
    if re.fullmatch(r"[\d０-９\s．.－-]+", text):
        return False
    normalized = text.translate(str.maketrans("０１２３４５６７８９．", "0123456789."))
    match = re.match(r"^(?P<num>\d+\.\d+(?:\s*\.\s*\d+)?)\s*(?P<title>.*)$", normalized)
    if match:
        parts = [int(part) for part in re.findall(r"\d+", match.group("num"))]
        title = match.group("title").strip()
        if not parts or parts[0] not in {6, 7, 8, 9}:
            return False
        if not title or not re.match(r"[\u4e00-\u9fff]", title):
            return False
    if re.match(r"^(案例分析|课题推荐)\s+", text) and len(text) > 40:
        return False
    return True


def _strip_toc_suffix(line: str) -> str:
    text = _normalize_pdf_heading_text(line)
    text = re.sub(r"[ 　]*[０-９0-9 ]+[.．…·・⋯]+$", "", text).strip()
    text = re.sub(r"[ 　]*[.．…·・⋯]+$", "", text).strip()
    return text


def _clean_pdf_page_text(page_text: str) -> list[str]:
    lines = []
    for raw in str(page_text).splitlines():
        line = _normalize_pdf_heading_text(raw)
        if not line or _is_page_noise(line):
            continue
        lines.append(line)
    return lines


def _format_pdf_pages_as_markdown(book_title: str, pages: Sequence[str]) -> tuple[str, dict[str, Any]]:
    """Format extracted PDF page text as section-oriented Markdown."""

    lines: list[str] = [f"# {book_title}"]
    written_heading_keys: set[str] = set()
    toc_heading_keys: set[str] = set()
    structured_headings = 0
    fallback_pages = 0
    in_toc = False
    body_started = False

    for page_index, page_text in enumerate(pages, start=1):
        page_lines = _clean_pdf_page_text(page_text)
        if not page_lines:
            continue
        if any("目" in line and "录" in line for line in page_lines[:3]):
            in_toc = True
            for line in page_lines:
                if _looks_like_structural_pdf_heading(line):
                    heading = _strip_toc_suffix(line)
                    key = re.sub(r"\s+", "", heading)
                    toc_heading_keys.add(key)
            continue
        body_written = False
        for line in page_lines:
            if _looks_like_structural_pdf_heading(line):
                heading = _strip_toc_suffix(line)
                key = re.sub(r"\s+", "", heading)
                if in_toc:
                    if key.startswith("第") and "章" in key:
                        in_toc = False
                        body_started = True
                    else:
                        toc_heading_keys.add(key)
                        continue
                elif not body_started and key in toc_heading_keys:
                    continue
                else:
                    body_started = True
                if key not in written_heading_keys:
                    lines.extend(["", f"## {heading}"])
                    written_heading_keys.add(key)
                    structured_headings += 1
                body_written = True
                continue
            if in_toc:
                continue
            lines.append(line)
            body_written = True
        if not body_written and not in_toc:
            lines.extend(["", f"## Page {page_index}", *page_lines])
            fallback_pages += 1
    if structured_headings == 0:
        lines = [f"# {book_title}"]
        for page_index, page_text in enumerate(pages, start=1):
            text = str(page_text).strip()
            if text:
                lines.extend(["", f"## Page {page_index}", "", text])
                fallback_pages += 1
    return "\n".join(lines).strip() + "\n", {
        "structured_headings": structured_headings,
        "fallback_pages": fallback_pages,
    }


def _available_pdf_text_extractors() -> list[tuple[str, Any]]:
    extractors: list[tuple[str, Any]] = []
    if importlib.util.find_spec("pypdf"):
        extractors.append(("pypdf", _extract_pdf_text_with_pypdf))
    if importlib.util.find_spec("pdfplumber"):
        extractors.append(("pdfplumber", _extract_pdf_text_with_pdfplumber))
    if importlib.util.find_spec("fitz"):
        extractors.append(("fitz", _extract_pdf_text_with_fitz))
    return extractors


def fallback_pdf_to_markdown(
    source_pdf: Path,
    output_root: Path = PDF_FALLBACK_OUTPUT_ROOT,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Convert PDF to text-only Markdown when MinerU is unavailable."""

    extractors = _available_pdf_text_extractors()
    if not extractors:
        raise RuntimeError("No fallback PDF text extractor is available. Install pypdf, pdfplumber, or PyMuPDF.")
    errors: list[str] = []
    for name, extractor in extractors:
        try:
            text, page_count = extractor(Path(source_pdf))
        except Exception as exc:
            errors.append(f"{name}: {exc}")
            continue
        if not text.strip():
            errors.append(f"{name}: extracted empty text")
            continue
        text, text_repair = _repair_pdf_text_mojibake(text)
        run_dir = Path(output_root) / sanitize_token(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        output_md = run_dir / f"{sanitize_token(Path(source_pdf).stem)}.md"
        output_md.write_text(text.strip() + "\n", encoding="utf-8")
        manifest = {
            "status": "ok",
            "source_kind": "pdf_text_fallback",
            "extractor": name,
            "source_pdf": str(Path(source_pdf).resolve()),
            "prepared_markdown": str(output_md),
            "page_count": page_count,
            "text_repair": text_repair,
        }
        (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest
    raise RuntimeError("Fallback PDF text extraction failed: " + "; ".join(errors))


def scan_secret_leaks(output_paths: Sequence[Path], secret_values: Sequence[str]) -> dict[str, Any]:
    """Scan files for secret values, reporting paths only."""

    secrets = [secret for secret in secret_values if secret]
    leaked: list[str] = []
    scanned = 0
    for raw_path in output_paths:
        path = Path(raw_path)
        if not path.exists() or not path.is_file():
            continue
        scanned += 1
        text = path.read_text(encoding="utf-8", errors="ignore")
        if any(secret in text for secret in secrets):
            leaked.append(str(path))
    return {"ok": not leaked, "scanned_files": scanned, "leaked_files": leaked}


def _iter_files(paths: Sequence[Path]) -> list[Path]:
    files: list[Path] = []
    for raw in paths:
        path = Path(raw)
        if path.is_file():
            files.append(path)
        elif path.is_dir():
            files.extend(item for item in path.rglob("*") if item.is_file())
    return files


def _stage(name: str, stage_status: str, started: float, **details: Any) -> dict[str, Any]:
    return {
        "name": name,
        "status": stage_status,
        "elapsed_seconds": round(time.time() - started, 2),
        "details": _jsonable(details),
    }


def _exception_details(exc: Exception) -> dict[str, str]:
    return {"error_type": type(exc).__name__, "error_message": str(exc)}


def _record_stage_error(final_manifest: dict[str, Any], stage_name: str, exc: Exception) -> None:
    final_manifest.setdefault("stage_errors", []).append({"stage": stage_name, **_exception_details(exc)})


def _derive_pipeline_status(stages: Sequence[dict[str, Any]]) -> str:
    statuses = [str(stage.get("status", "")) for stage in stages]
    if any(status == "failed" for status in statuses):
        return "failed"
    if any(status == "degraded" for status in statuses):
        return "degraded"
    return "passed"


def _finalize_with_status(
    config: FullPipelineConfig,
    stages: list[dict[str, Any]],
    final_manifest: dict[str, Any],
    report_path: Path,
    secret_scan: dict[str, Any],
    *,
    run_id: str,
    total_stages: int,
) -> dict[str, Any]:
    final_manifest["status"] = _derive_pipeline_status(stages)
    return _finalize_stages(
        config,
        stages,
        final_manifest,
        report_path,
        secret_scan,
        run_id=run_id,
        total_stages=total_stages,
    )


def _manifest_count(manifest: dict[str, Any], *keys: str) -> int:
    for key in keys:
        value = manifest.get(key)
        if isinstance(value, (list, tuple, dict)):
            return len(value)
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def _section_count(segment_summary: dict[str, Any]) -> int:
    sections = segment_summary.get("sections")
    if isinstance(sections, list):
        return len(sections)
    try:
        return int(sections)
    except (TypeError, ValueError):
        pass
    info = segment_summary.get("info")
    if isinstance(info, dict):
        for key in ["written", "sections", "section_count"]:
            try:
                return int(info.get(key))
            except (TypeError, ValueError):
                continue
    return 0


def _taxonomy_class_count(taxonomy_manifest: dict[str, Any]) -> int:
    taxonomy_path = taxonomy_manifest.get("selected_taxonomy")
    if not taxonomy_path:
        return 0
    try:
        data = json.loads(Path(str(taxonomy_path)).read_text(encoding="utf-8"))
        for key in ["items", "classes", "taxonomy", "image_types"]:
            value = data.get(key) if isinstance(data, dict) else None
            if isinstance(value, (list, tuple, dict)):
                return len(value)
    except Exception:
        return 0
    return 0


def _block(title: str, color: str, body: list[str]) -> str:
    return (
        f'<div style="border-left: 6px solid {color}; background: #f8fafc; '
        'padding: 12px 14px; margin: 14px 0;">\n\n'
        f"### {title}\n\n"
        + "\n".join(body)
        + "\n\n</div>"
    )


def _fmt_dict(data: dict[str, Any]) -> str:
    return "```json\n" + json.dumps(_jsonable(data), ensure_ascii=False, indent=2) + "\n```"


def _fmt_rmb(value: Any) -> str:
    if value is None:
        return "null"
    try:
        return f"{float(value):.6f}"
    except (TypeError, ValueError):
        return str(value)


def _cost_report_lines(cost_rmb: dict[str, Any]) -> list[str]:
    rows = [
        "| model | prompt_tokens | completion_tokens | cost_rmb |",
        "| --- | ---: | ---: | ---: |",
    ]
    by_model = cost_rmb.get("by_model", []) if isinstance(cost_rmb, dict) else []
    for item in by_model if isinstance(by_model, list) else []:
        if not isinstance(item, dict):
            continue
        rows.append(
            "| "
            + " | ".join(
                [
                    f"`{item.get('model', '')}`",
                    str(item.get("prompt_tokens", 0)),
                    str(item.get("completion_tokens", 0)),
                    _fmt_rmb(item.get("cost_rmb")),
                ]
            )
            + " |"
        )
    rows.extend(
        [
            f"- total_rmb: `{_fmt_rmb(cost_rmb.get('total_rmb') if isinstance(cost_rmb, dict) else None)}`",
            f"- note: {cost_rmb.get('note', '') if isinstance(cost_rmb, dict) else ''}",
        ]
    )
    return rows


def _kg_artifact_status(kg_manifest: dict[str, Any] | None) -> dict[str, Any]:
    outputs = (kg_manifest or {}).get("standard_outputs", {}) if isinstance(kg_manifest, dict) else {}
    result: dict[str, Any] = {}
    for key in ["merged_nodes", "merged_edges", "triples"]:
        path = Path(str(outputs.get(key, ""))) if outputs.get(key) else None
        exists = bool(path and path.exists())
        result[f"{key}_path"] = str(path) if path else ""
        result[f"{key}_exists"] = exists
    return result


def _pdf_markdown_usable(pdf_info: dict[str, Any] | None) -> bool:
    if not isinstance(pdf_info, dict):
        return False
    markdown = pdf_info.get("prepared_markdown") or pdf_info.get("selected_markdown")
    if not markdown:
        return False
    path = Path(str(markdown))
    return path.exists() and path.is_file() and path.suffix.lower() == ".md"


def _segment_output_usable(segment_summary: dict[str, Any] | None) -> bool:
    if not isinstance(segment_summary, dict):
        return False
    sections_dir_value = segment_summary.get("sections_dir")
    sections_index_value = segment_summary.get("sections_index")
    if not sections_dir_value or not sections_index_value:
        return False
    sections_dir = Path(str(sections_dir_value))
    sections_index = Path(str(sections_index_value))
    return sections_dir.is_dir() and any(sections_dir.glob("*.md")) and sections_index.exists()


def _taxonomy_output_usable(taxonomy_manifest: dict[str, Any] | None) -> bool:
    if not isinstance(taxonomy_manifest, dict):
        return False
    taxonomy_path = taxonomy_manifest.get("selected_taxonomy")
    if not taxonomy_path:
        return False
    path = Path(str(taxonomy_path))
    return path.exists() and path.is_file()


def _ipa_output_usable(ipa_manifest: dict[str, Any] | None) -> bool:
    if not isinstance(ipa_manifest, dict):
        return False
    try:
        return bool(_enhanced_markdown_paths(ipa_manifest))
    except Exception:
        return False


def _schema_output_usable(schema_manifest: dict[str, Any] | None) -> bool:
    if not isinstance(schema_manifest, dict):
        return False
    output_dir = schema_manifest.get("output_dir")
    if output_dir and (Path(str(output_dir)) / "final_schema.json").exists():
        return True
    publish = schema_manifest.get("standards_publish")
    if isinstance(publish, dict) and publish.get("published"):
        return True
    return False


def _schema_path_from_manifest(schema_manifest: dict[str, Any] | None) -> Path | None:
    if not isinstance(schema_manifest, dict):
        return None
    output_dir = schema_manifest.get("output_dir")
    if output_dir:
        candidate = Path(str(output_dir)) / "final_schema.json"
        if candidate.exists():
            return candidate
    publish = schema_manifest.get("standards_publish")
    if isinstance(publish, dict):
        files = publish.get("files")
        if isinstance(files, dict):
            candidate_value = files.get("kg_schema_label_property_v2.json") or files.get("schema_json")
            if candidate_value:
                candidate = Path(str(candidate_value))
                if candidate.exists():
                    return candidate
    schema_path = schema_manifest.get("schema_path")
    if schema_path:
        candidate = Path(str(schema_path))
        if candidate.exists():
            return candidate
    return None


def _subject_uses_published_schema(subject: str) -> bool:
    normalized = sanitize_token(subject or "").lower()
    return normalized in {"", "chemistry", "chemical", "huaxue"}


def _fallback_schema_path_for_subject(config: FullPipelineConfig, published_schema: Path) -> Path:
    if _subject_uses_published_schema(config.subject):
        return published_schema
    base_schema = Path(config.sa_base_schema)
    if base_schema.exists():
        return base_schema
    return published_schema


def _stage_output_usable(stage_name: str, output: dict[str, Any] | None) -> bool:
    if stage_name == "pdf":
        return _pdf_markdown_usable(output)
    if stage_name == "segment":
        return _segment_output_usable(output)
    if stage_name == "ita":
        return _taxonomy_output_usable(output)
    if stage_name == "ipa":
        return _ipa_output_usable(output)
    if stage_name == "schema":
        return _schema_output_usable(output)
    return bool(output)


def write_full_report(
    *,
    report_path: Path,
    run_id: str,
    config: FullPipelineConfig,
    stages: list[dict[str, Any]],
    final_manifest: dict[str, Any],
    secret_scan: dict[str, Any],
) -> None:
    """Write the Markdown experiment report with color-coded blocks."""

    report_path.parent.mkdir(parents=True, exist_ok=True)
    kg = final_manifest.get("kg_manifest") or {}
    kg_artifacts = final_manifest.get("kg_artifacts") or {}
    all_ok = all(stage["status"] == "passed" for stage in stages)
    automation_status = "达到自动化 KG 跑通预期" if all_ok and kg_artifacts.get("triples_exists") else "未完全达到自动化 KG 跑通预期"
    lines = [
        f"# FaMAS 全流程实验报告：{run_id}",
        "",
        _block(
            "总览",
            "#2563eb",
            [
                f"- run_id: `{run_id}`",
                f"- 教材 PDF: `{config.pdf_path}`",
                f"- mock: `{config.mock}`",
                f"- 自动化 KG 评估: **{automation_status}**",
                f"- KG nodes: `{kg.get('accepted_nodes', '')}`",
                f"- KG edges: `{kg.get('accepted_edges', '')}`",
                f"- KG counted nodes: `{kg.get('counted_nodes', '')}`",
                f"- KG counted edges: `{kg.get('counted_edges', '')}`",
                f"- KG triples: `{kg.get('triples', '')}`",
            ],
        ),
        _block(
            "环境与模型",
            "#7c3aed",
            [
                f"- vision_model: `{config.vision_model or 'not used'}`",
                f"- NEA/EEA/SdA text models: `{config.node_model}`, `{config.edge_model}`, `{config.standard_model}`",
                f"- VA provider/model: `{config.validation_provider}` / `{config.validation_model}`",
                f"- VA revision rounds: `{config.max_revision_rounds}`",
                "- API key: 仅临时环境变量读取，报告不记录 key 值。",
            ],
        ),
    ]
    color_map = {
        "passed": "#16a34a",
        "failed": "#dc2626",
        "skipped": "#ca8a04",
        "degraded": "#ca8a04",
    }
    for stage in stages:
        status = stage.get("status", "")
        details = stage.get("details", {})
        lines.append(
            _block(
                f"{stage.get('name')}：{status}",
                color_map.get(status, "#64748b"),
                [
                    f"- elapsed_seconds: `{stage.get('elapsed_seconds')}`",
                    _fmt_dict(details if isinstance(details, dict) else {"details": details}),
                ],
            )
        )
    lines.extend(
        [
            _block(
                "KG 三件套输出",
                "#0891b2",
                [
                    f"- merged_nodes.json: `{kg_artifacts.get('merged_nodes_path', '')}` exists=`{kg_artifacts.get('merged_nodes_exists')}`",
                    f"- merged_edges.json: `{kg_artifacts.get('merged_edges_path', '')}` exists=`{kg_artifacts.get('merged_edges_exists')}`",
                    f"- triples.json: `{kg_artifacts.get('triples_path', '')}` exists=`{kg_artifacts.get('triples_exists')}`",
                ],
            ),
            _block(
                "LLM 成本估算",
                "#9333ea",
                _cost_report_lines(final_manifest.get("cost_rmb") or {}),
            ),
            _block(
                "API Key 泄漏扫描",
                "#0f766e" if secret_scan.get("ok") else "#dc2626",
                [
                    f"- ok: `{secret_scan.get('ok')}`",
                    f"- scanned_files: `{secret_scan.get('scanned_files')}`",
                    f"- leaked_files: `{secret_scan.get('leaked_files')}`",
                ],
            ),
            _block(
                "结论",
                "#334155",
                [
                    f"- 自动化 KG 结论: **{automation_status}**",
                    "- 本报告记录单次新教材迁移运行，不包含 prompt 多轮调参实验。",
                    "- 若某阶段失败，应优先查看该阶段 details 中的 error_type、error_message 和输出路径。",
                ],
            ),
        ]
    )
    report_path.write_text("\n\n".join(lines), encoding="utf-8")


def _secret_values_from_env() -> list[str]:
    return [os.environ.get("DASHSCOPE_API_KEY", ""), os.environ.get("DEEPSEEK_API_KEY", "")]


def _enhanced_markdown_paths(ipa_manifest: dict[str, Any]) -> list[Path]:
    run_dir = Path(str(ipa_manifest["run_dir"]))
    enhanced_dir = run_dir / "enhanced_markdown" / "sections"
    return sorted(enhanced_dir.glob("*.md"))


def find_existing_ipa_output(ipa_output_root: Path, run_id: str) -> Path | None:
    root = Path(ipa_output_root)
    if not run_id or not root.exists() or not root.is_dir():
        return None
    candidates: list[Path] = []
    for item in root.iterdir():
        if not item.is_dir() or not item.name.endswith(f"_{run_id}"):
            continue
        enhanced_dir = item / "enhanced_markdown" / "sections"
        manifest_path = item / "manifest.json"
        if not enhanced_dir.is_dir() or not any(enhanced_dir.glob("*.md")):
            continue
        try:
            json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        candidates.append(item)
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def section_markdown_has_images(sections_dir: Path) -> bool:
    for path in sorted(Path(sections_dir).glob("*.md")):
        if "![" in path.read_text(encoding="utf-8", errors="ignore"):
            return True
    return False


def image_source_dir_has_images(image_source_dir: Path | None) -> bool:
    if image_source_dir is None:
        return False
    source = Path(image_source_dir)
    if not source.is_dir():
        return False
    return any(item.is_file() for item in source.iterdir())


def copy_sections_as_enhanced_markdown(
    *,
    sections_dir: Path,
    sections_index: Path,
    output_root: Path,
    run_id: str,
) -> dict[str, Any]:
    """Create an IPA-like package for text-only sections."""

    base = Path(output_root).resolve()
    run_dir = base / f"ipa_text_only_{sanitize_token(run_id)}"
    if run_dir.exists():
        suffix = 2
        while (base / f"{run_dir.name}_{suffix}").exists():
            suffix += 1
        run_dir = base / f"{run_dir.name}_{suffix}"
    enhanced_dir = run_dir / "enhanced_markdown" / "sections"
    input_sections = run_dir / "inputs" / "sections"
    enhanced_dir.mkdir(parents=True, exist_ok=True)
    input_sections.mkdir(parents=True, exist_ok=True)
    if Path(sections_index).exists():
        shutil.copy2(sections_index, run_dir / "inputs" / "sections_index.json")
    count = 0
    for section in sorted(Path(sections_dir).glob("*.md")):
        shutil.copy2(section, enhanced_dir / section.name)
        shutil.copy2(section, input_sections / section.name)
        count += 1
    manifest = {
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "mock": False,
        "mode": "no_images_passthrough",
        "sections": count,
        "images": 0,
        "textualized": 0,
        "valuable_non_textual": 0,
        "sections_dir": str(sections_dir),
        "sections_index": str(sections_index),
    }
    (run_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _finalize_stages(
    config: FullPipelineConfig,
    stages: list[dict[str, Any]],
    final_manifest: dict[str, Any],
    report_path: Path,
    secret_scan: dict[str, Any],
    *,
    run_id: str,
    total_stages: int,
) -> dict[str, Any]:
    final_manifest["stages"] = stages
    final_manifest.setdefault(
        "reproducibility",
        {
            "llm_seed": config.llm_seed,
            "node_model": config.node_model,
            "edge_model": config.edge_model,
            "standard_model": config.standard_model,
            "sa_model": config.sa_model,
            "validation_model": config.validation_model,
            "pdf_extractor_used": (final_manifest.get("pdf_to_md") or {}).get("extractor", ""),
        },
    )
    try:
        scan_roots = [config.report_dir]
        for key in ["pdf_to_md", "segmentation", "taxonomy_manifest", "ipa_manifest", "schema_agent", "kg_manifest"]:
            item = final_manifest.get(key)
            if isinstance(item, dict):
                for value_key in ["run_dir", "output_dir", "work_dir"]:
                    if item.get(value_key):
                        scan_roots.append(Path(str(item[value_key])))
        if final_manifest.get("kg_artifacts"):
            scan_roots.extend(Path(str(v)) for k, v in final_manifest["kg_artifacts"].items() if k.endswith("_path") and v)
        secret_scan = scan_secret_leaks(_iter_files(scan_roots), _secret_values_from_env())
    except Exception as scan_exc:
        secret_scan = {
            "ok": False,
            "scanned_files": 0,
            "leaked_files": [],
            "scan_error": type(scan_exc).__name__,
        }
    token_usage = usage_snapshot()
    final_manifest["token_usage"] = token_usage
    final_manifest["cost_rmb"] = estimate_cost_rmb(token_usage)
    final_manifest["secret_scan"] = secret_scan
    final_manifest.setdefault("kg_artifacts", _kg_artifact_status(final_manifest.get("kg_manifest")))
    final_manifest["report_path"] = str(report_path)
    try:
        write_full_report(
            report_path=report_path,
            run_id=run_id,
            config=config,
            stages=stages,
            final_manifest=final_manifest,
            secret_scan=secret_scan,
        )
    except Exception as report_exc:
        final_manifest["report_error"] = type(report_exc).__name__
    if final_manifest.get("status") != "failed" and not secret_scan.get("ok"):
        final_manifest["status"] = "failed"
        final_manifest.setdefault("error_type", "SecretScanFailed")
        final_manifest.setdefault(
            "error_message",
            "secret scan reported leak or failed to run; see secret_scan field",
        )
    manifest_path = report_path.with_name(f"{run_id}_full_pipeline_manifest.json")
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    final_manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(_jsonable(final_manifest), ensure_ascii=False, indent=2), encoding="utf-8")
    return final_manifest


def run_full_pipeline(config: FullPipelineConfig) -> dict[str, Any]:
    """Run PDF->MD->sections->ITA->IPA->KG with stage-level fault tolerance."""

    reset_usage()
    run_id = config.run_id or make_full_run_id(config.pdf_path.stem)
    total_stages = 6
    stages: list[dict[str, Any]] = []
    final_manifest: dict[str, Any] = {
        "schema_version": "mas.full_pipeline.v1",
        "run_id": run_id,
        "config": _jsonable(asdict(config)),
        "ipa_reused": False,
        "ipa_reused_from": "",
    }
    key_info = load_api_keys_to_env(config.api_key_file)
    final_manifest["api_key_env"] = key_info
    report_path = config.report_dir / f"{run_id}_full_pipeline_report.md"
    secret_scan = {"ok": True, "scanned_files": 0, "leaked_files": []}

    def fail_stage(
        *,
        display_name: str,
        stage_number: int,
        stage_name: str,
        started: float,
        exc: Exception,
        **details: Any,
    ) -> dict[str, Any]:
        progress.stage_failed(display_name, stage_number, total_stages, str(exc))
        _record_stage_error(final_manifest, stage_name, exc)
        stages.append(_stage(stage_name, "failed", started, **details, **_exception_details(exc)))
        final_manifest["error_type"] = type(exc).__name__
        final_manifest["error_message"] = str(exc)
        return _finalize_with_status(
            config,
            stages,
            final_manifest,
            report_path,
            secret_scan,
            run_id=run_id,
            total_stages=total_stages,
        )

    pdf_info: dict[str, Any] = {}
    pdf_status = ""
    prepared_md: Path | None = None
    image_source_dir: Path | None = None
    started = time.time()
    progress.stage_banner("PDF 转 Markdown（MinerU GPU）", 1, total_stages)
    progress.step("整本可能需数分钟，可另开终端用 nvidia-smi 观察 GPU 是否在跑")
    try:
        pipeline_config = load_config(None)
        ok, pdf_status, pdf_info = prepare_from_pdf(
            pipeline_config,
            config.pdf_path,
            overwrite=config.overwrite_pdf_md,
        )
        if pdf_status == "skipped_existing":
            progress.step("复用已有 Markdown，跳过解析")
        if not ok:
            if pdf_status == "mineru_not_found":
                if not config.allow_pdf_text_fallback:
                    raise RuntimeError(
                        "MinerU is required for Web PDF processing with images, but it was not found. "
                        "Create code_implement/.venv and install the root requirements.txt before running Build Graph."
                    )
                pdf_info = fallback_pdf_to_markdown(config.pdf_path, PDF_FALLBACK_OUTPUT_ROOT, run_id=run_id)
                pdf_status = "pdf_text_fallback"
            else:
                raise RuntimeError(f"PDF to Markdown failed: {pdf_status}")
        if not _stage_output_usable("pdf", pdf_info):
            raise RuntimeError("PDF to Markdown produced no usable Markdown file")
        prepared_md = Path(str(pdf_info.get("prepared_markdown") or pdf_info.get("selected_markdown")))
        image_source_dir = find_image_source_dir(pdf_info)
    except Exception as exc:
        if not _stage_output_usable("pdf", pdf_info):
            return fail_stage(
                display_name="PDF 转 Markdown",
                stage_number=1,
                stage_name="PDF 转 Markdown",
                started=started,
                exc=exc,
                status=pdf_status,
            )
        prepared_md = Path(str(pdf_info.get("prepared_markdown") or pdf_info.get("selected_markdown")))
        image_source_dir = None
        _record_stage_error(final_manifest, "PDF 转 Markdown", exc)
        stages.append(
            _stage(
                "PDF 转 Markdown",
                "degraded",
                started,
                status=pdf_status,
                prepared_markdown=prepared_md,
                image_source_dir=image_source_dir,
                **_exception_details(exc),
            )
        )
        final_manifest["pdf_to_md"] = pdf_info
        progress.stage_done("PDF 转 Markdown", 1, total_stages, time.time() - started, extra=f"status={pdf_status}; degraded")
    else:
        stages.append(_stage("PDF 转 Markdown", "passed", started, status=pdf_status, prepared_markdown=prepared_md, image_source_dir=image_source_dir))
        final_manifest["pdf_to_md"] = pdf_info
        progress.stage_done("PDF 转 Markdown", 1, total_stages, time.time() - started, extra=f"status={pdf_status}")

    if config.stop_at == "pdf":
        print("[STOP] --stop-at=pdf，跳过后续阶段", file=os.sys.stderr)
        return _finalize_with_status(
            config,
            stages,
            final_manifest,
            report_path,
            secret_scan,
            run_id=run_id,
            total_stages=total_stages,
        )

    segment_summary: dict[str, Any] = {}
    sections_dir: Path | None = None
    sections_index: Path | None = None
    started = time.time()
    progress.stage_banner("Markdown 分段", 2, total_stages)
    try:
        if prepared_md is None:
            raise RuntimeError("missing prepared Markdown for segmentation")
        segment_summary = segment_markdown_file(
            prepared_md,
            config.segment_output_root,
            book_prefix=sanitize_token(run_id),
            stage=config.grade,
            subject=config.subject,
            publisher=config.publisher,
            grade=config.grade,
            book_name=config.pdf_path.stem,
            keep_images=True,
            overwrite=False,
        )
        if not segment_summary.get("ok") and not _stage_output_usable("segment", segment_summary):
            raise RuntimeError(f"Markdown segmentation failed: {segment_summary.get('status')}")
        if not _stage_output_usable("segment", segment_summary):
            raise RuntimeError("Markdown segmentation produced no usable sections")
        sections_dir = Path(str(segment_summary["sections_dir"]))
        sections_index = Path(str(segment_summary["sections_index"]))
    except Exception as exc:
        if not _stage_output_usable("segment", segment_summary):
            return fail_stage(
                display_name="Markdown 分段",
                stage_number=2,
                stage_name="Markdown 切分",
                started=started,
                exc=exc,
                **segment_summary,
            )
        sections_dir = Path(str(segment_summary["sections_dir"]))
        sections_index = Path(str(segment_summary["sections_index"]))
        _record_stage_error(final_manifest, "Markdown 切分", exc)
        stages.append(_stage("Markdown 切分", "degraded", started, **segment_summary, **_exception_details(exc)))
        final_manifest["segmentation"] = segment_summary
        progress.stage_done("Markdown 分段", 2, total_stages, time.time() - started, extra=f"sections={_section_count(segment_summary)}; degraded")
    else:
        segment_status = "passed" if segment_summary.get("ok", True) else "degraded"
        stages.append(_stage("Markdown 切分", segment_status, started, **segment_summary))
        final_manifest["segmentation"] = segment_summary
        progress.stage_done("Markdown 分段", 2, total_stages, time.time() - started, extra=f"sections={_section_count(segment_summary)}")

    if config.stop_at == "segment":
        print("[STOP] --stop-at=segment，跳过 ITA、IPA、SA 和 KG", file=os.sys.stderr)
        return _finalize_with_status(
            config,
            stages,
            final_manifest,
            report_path,
            secret_scan,
            run_id=run_id,
            total_stages=total_stages,
        )

    assert sections_dir is not None
    assert sections_index is not None
    try:
        has_section_images = section_markdown_has_images(sections_dir)
        has_source_images = image_source_dir_has_images(image_source_dir)
        has_images = has_section_images or has_source_images
        if has_source_images and not has_section_images:
            _warn("image_source_dir 存在图片但 section Markdown 没有图片引用，IPA 将生成 not_in_section_markdown 追溯记录")
    except Exception as exc:
        _record_stage_error(final_manifest, "Markdown 切分", exc)
        has_section_images = False
        has_source_images = False
        has_images = False

    reused_ipa_dir = find_existing_ipa_output(config.ipa_output_root, run_id) if config.run_id_explicit else None
    ipa_reused = reused_ipa_dir is not None
    ipa_reuse_reason = f"reused existing IPA output: {reused_ipa_dir}" if reused_ipa_dir else ""
    taxonomy_manifest: dict[str, Any] = {}
    taxonomy_path_for_ipa: Path | None = None

    if ipa_reused:
        started = time.time()
        progress.stage_banner("ITA 图像分类法", 3, total_stages)
        taxonomy_manifest = {
            "run_id": f"taxonomy_skipped_{sanitize_token(run_id)}",
            "mode": "ipa_reused",
            "selected_taxonomy": "",
            "reason": ipa_reuse_reason,
        }
        stages.append(_stage("ITA 图片 taxonomy", "skipped", started, **taxonomy_manifest))
        final_manifest["taxonomy_manifest"] = taxonomy_manifest
        progress.stage_done("ITA 图像分类法", 3, total_stages, time.time() - started, extra=ipa_reuse_reason)
    elif has_section_images:
        started = time.time()
        progress.stage_banner("ITA 图像分类法", 3, total_stages)
        try:
            if image_source_dir is None or not Path(image_source_dir).exists():
                _warn("image_source_dir 为空但存在图片引用，IPA 将看不到任何图片，KG 图片证据会缺失")
            if not config.vision_model:
                raise RuntimeError("Visual ITA/IPA stages require --vision-model; KG extraction itself never re-reads images.")
            taxonomy_manifest = run_taxonomy_pipeline(
                TaxonomyRunConfig(
                    sections_dir=sections_dir,
                    sections_index=sections_index,
                    image_source_dir=image_source_dir,
                    output_root=config.taxonomy_output_root,
                    mock=config.mock,
                    sample_size=config.taxonomy_sample_size,
                    sample_ratio=config.taxonomy_sample_ratio,
                    use_ratio_sampling=True,
                    sample_size_explicit=config.taxonomy_sample_size_explicit,
                    batch_size=config.taxonomy_batch_size,
                    max_parallel_workers=config.taxonomy_max_parallel_workers,
                    run_label=run_id,
                    model_name=config.vision_model,
                    model_config={
                        "name": config.vision_model,
                        "api_key_env": DEFAULT_VISION_API_KEY_ENV,
                        "timeout_seconds": config.qwen_timeout_seconds,
                        "retry_attempts": config.qwen_retry_attempts,
                        "timeout_retry_attempts": config.qwen_timeout_retry_attempts,
                        "timeout_retry_budget_seconds": config.qwen_timeout_retry_budget_seconds,
                        "seed": config.llm_seed,
                        "usage_stage": "ITA",
                    },
                )
            )
            if not _stage_output_usable("ita", taxonomy_manifest):
                raise RuntimeError("ITA did not generate usable taxonomy file")
        except Exception as exc:
            _record_stage_error(final_manifest, "ITA 图片 taxonomy", exc)
            if _stage_output_usable("ita", taxonomy_manifest):
                taxonomy_path_for_ipa = Path(str(taxonomy_manifest["selected_taxonomy"]))
                reason = "ITA failed after producing taxonomy"
                stage_details = {**taxonomy_manifest, "reason": reason, **_exception_details(exc)}
            else:
                reason = "ITA failed, using built-in default taxonomy"
                taxonomy_manifest = {
                    "run_id": f"taxonomy_degraded_{sanitize_token(run_id)}",
                    "mode": "built_in_default",
                    "selected_taxonomy": "",
                    "reason": reason,
                    **_exception_details(exc),
                }
                taxonomy_path_for_ipa = None
                stage_details = taxonomy_manifest
            stages.append(_stage("ITA 图片 taxonomy", "degraded", started, **stage_details))
            final_manifest["taxonomy_manifest"] = taxonomy_manifest
            progress.stage_done("ITA 图像分类法", 3, total_stages, time.time() - started, extra=reason)
        else:
            taxonomy_path_for_ipa = Path(str(taxonomy_manifest["selected_taxonomy"]))
            failed_batches = _manifest_count(taxonomy_manifest, "observation_failed_batches")
            taxonomy_status = "degraded" if failed_batches or taxonomy_manifest.get("status") == "degraded" else "passed"
            stages.append(_stage("ITA 图片 taxonomy", taxonomy_status, started, **taxonomy_manifest))
            final_manifest["taxonomy_manifest"] = taxonomy_manifest
            progress.stage_done(
                "ITA 图像分类法",
                3,
                total_stages,
                time.time() - started,
                extra=(
                    f"sample={_manifest_count(taxonomy_manifest, 'sample_size', 'effective_sample_size')}, "
                    f"taxonomy={_taxonomy_class_count(taxonomy_manifest)} 类"
                ),
            )
    else:
        started = time.time()
        progress.stage_banner("ITA 图像分类法", 3, total_stages)
        taxonomy_manifest = {
            "run_id": f"taxonomy_skipped_{sanitize_token(run_id)}",
            "mode": "no_section_markdown_images" if has_source_images else "no_images",
            "total_images_available": _count_files(image_source_dir) if has_source_images and image_source_dir else 0,
            "selected_taxonomy": "",
        }
        stages.append(_stage("ITA 图片 taxonomy", "skipped", started, **taxonomy_manifest))
        final_manifest["taxonomy_manifest"] = taxonomy_manifest
        progress.stage_done(
            "ITA 图像分类法",
            3,
            total_stages,
            time.time() - started,
            extra="section 无图，源图进入 IPA 追溯" if has_source_images else "无图，跳过",
        )

    if config.stop_at == "ita":
        print("[STOP] --stop-at=ita，跳过 IPA、SA 和 KG", file=os.sys.stderr)
        return _finalize_with_status(
            config,
            stages,
            final_manifest,
            report_path,
            secret_scan,
            run_id=run_id,
            total_stages=total_stages,
        )

    ipa_manifest: dict[str, Any] = {}
    enhanced_paths: list[Path] = []
    started = time.time()
    progress.stage_banner("IPA 图像处理", 4, total_stages)
    ipa_stage_status = "passed"
    ipa_stage_extra: dict[str, Any] = {}
    try:
        if ipa_reused:
            if reused_ipa_dir is None:
                raise RuntimeError("missing reusable IPA directory")
            ipa_manifest = json.loads((reused_ipa_dir / "manifest.json").read_text(encoding="utf-8"))
            final_manifest["ipa_reused"] = True
            final_manifest["ipa_reused_from"] = str(reused_ipa_dir)
            ipa_stage_status = "skipped"
            ipa_stage_extra["reason"] = ipa_reuse_reason
        elif has_images:
            ipa_manifest = run_ipa_pipeline(
                input_md=None,
                sections_dir=sections_dir,
                sections_index=sections_index,
                image_source_dir=image_source_dir,
                source_pdf=config.pdf_path,
                output_root=config.ipa_output_root,
                mock=config.mock,
                batch_size=config.ipa_batch_size,
                run_label=run_id,
                model_config={
                    "name": config.vision_model,
                    "api_key_env": DEFAULT_IPA_GENERATOR_API_KEY_ENV,
                    "timeout_seconds": config.qwen_timeout_seconds,
                    "retry_attempts": config.qwen_retry_attempts,
                    "timeout_retry_attempts": config.qwen_timeout_retry_attempts,
                    "timeout_retry_budget_seconds": config.qwen_timeout_retry_budget_seconds,
                    "seed": config.llm_seed,
                    "usage_stage": "IPA Generator",
                },
                verify_model_config={
                    "name": config.verify_vision_model,
                    "api_key_env": DEFAULT_VERIFY_VISION_API_KEY_ENV,
                    "timeout_seconds": config.qwen_timeout_seconds,
                    "retry_attempts": config.qwen_retry_attempts,
                    "timeout_retry_attempts": config.qwen_timeout_retry_attempts,
                    "timeout_retry_budget_seconds": config.qwen_timeout_retry_budget_seconds,
                    "seed": config.llm_seed,
                    "usage_stage": "IPA Verifier",
                },
                critic_revision_rounds=config.critic_revision_rounds,
                taxonomy_path=taxonomy_path_for_ipa,
                resume=config.ipa_resume,
                per_image_hard_timeout_seconds=config.per_image_hard_timeout_seconds,
            )
            if ipa_manifest.get("status") == "degraded":
                ipa_stage_status = "degraded"
        else:
            progress.step("无图，复制分段 Markdown 作为增强 Markdown")
            ipa_manifest = copy_sections_as_enhanced_markdown(
                sections_dir=sections_dir,
                sections_index=sections_index,
                output_root=config.ipa_output_root,
                run_id=run_id,
            )
        if not _stage_output_usable("ipa", ipa_manifest):
            raise RuntimeError("IPA did not generate enhanced Markdown files")
        enhanced_paths = _enhanced_markdown_paths(ipa_manifest)
    except Exception as exc:
        _record_stage_error(final_manifest, "IPA 增强 Markdown", exc)
        if not _stage_output_usable("ipa", ipa_manifest):
            recovered_ipa_dir = find_existing_ipa_output(config.ipa_output_root, run_id)
            if recovered_ipa_dir is not None:
                try:
                    ipa_manifest = json.loads((recovered_ipa_dir / "manifest.json").read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError):
                    ipa_manifest = {}
        if not _stage_output_usable("ipa", ipa_manifest):
            return fail_stage(
                display_name="IPA 图像处理",
                stage_number=4,
                stage_name="IPA 增强 Markdown",
                started=started,
                exc=exc,
                **ipa_manifest,
            )
        enhanced_paths = _enhanced_markdown_paths(ipa_manifest)
        stages.append(_stage("IPA 增强 Markdown", "degraded", started, **ipa_manifest, **_exception_details(exc), enhanced_md_count=len(enhanced_paths)))
        final_manifest["ipa_manifest"] = ipa_manifest
        progress.stage_done("IPA 图像处理", 4, total_stages, time.time() - started, extra="degraded")
    else:
        stages.append(_stage("IPA 增强 Markdown", ipa_stage_status, started, **ipa_stage_extra, **ipa_manifest, enhanced_md_count=len(enhanced_paths)))
        final_manifest["ipa_manifest"] = ipa_manifest
        progress.stage_done(
            "IPA 图像处理",
            4,
            total_stages,
            time.time() - started,
            extra=(
                f"images={_manifest_count(ipa_manifest, 'images')}, "
                f"textualized={_manifest_count(ipa_manifest, 'textualized')}, "
                f"rejected={_manifest_count(ipa_manifest, 'rejected_by_verifier')}"
            ),
        )
    if config.stop_at == "ipa":
        print("[STOP] --stop-at=ipa，跳过 SA 和 KG", file=os.sys.stderr)
        return _finalize_with_status(
            config,
            stages,
            final_manifest,
            report_path,
            secret_scan,
            run_id=run_id,
            total_stages=total_stages,
        )

    schema_manifest: dict[str, Any] = {}
    if config.enable_schema_agent:
        started = time.time()
        progress.stage_banner("SA 生成 schema", 5, total_stages)
        published_schema = resolve_published_schema_path(config.standards_dir)
        try:
            schema_manifest = run_schema_agent_pipeline(
                SchemaRunConfig(
                    enhanced_md=enhanced_paths,
                    sections_index=sections_index,
                    human_rules=config.sa_human_rules,
                    base_schema=config.sa_base_schema,
                    standards_dir=config.standards_dir,
                    work_root=config.schema_agent_work_root,
                    output_root=config.schema_agent_output_root,
                    rounds=config.sa_rounds,
                    model_name=config.sa_model,
                    mock=config.mock,
                    seed=config.llm_seed if config.llm_seed is not None else 42,
                    run_label=run_id,
                    publish_standards=config.publish_schema_standards,
                    standards_publish_dir=config.standards_dir,
                )
            )
            if not _stage_output_usable("schema", schema_manifest):
                if published_schema.exists():
                    fallback_schema = _fallback_schema_path_for_subject(config, published_schema)
                    config.schema_path = fallback_schema
                    fallback_mode = (
                        "published_schema_reuse"
                        if fallback_schema.resolve() == published_schema.resolve()
                        else "base_schema_reuse"
                    )
                    schema_manifest = {
                        **schema_manifest,
                        "mode": fallback_mode,
                        "schema_path": str(fallback_schema),
                        "reason": (
                            "SA produced no schema, using previously published schema"
                            if fallback_mode == "published_schema_reuse"
                            else "SA produced no schema, using subject-neutral base schema"
                        ),
                    }
                    stages.append(_stage("Schema Agent", "degraded", started, **schema_manifest))
                else:
                    raise RuntimeError("Schema Agent produced no usable schema file")
            else:
                runtime_schema = _schema_path_from_manifest(schema_manifest)
                if runtime_schema is not None:
                    config.schema_path = runtime_schema
                    schema_manifest = {**schema_manifest, "schema_path": str(runtime_schema)}
                stages.append(_stage("Schema Agent", "passed", started, **schema_manifest))
            final_manifest["schema_agent"] = schema_manifest
            progress.stage_done("SA 生成 schema", 5, total_stages, time.time() - started)
        except Exception as exc:
            _record_stage_error(final_manifest, "Schema Agent", exc)
            if _stage_output_usable("schema", schema_manifest):
                runtime_schema = _schema_path_from_manifest(schema_manifest)
                if runtime_schema is not None:
                    config.schema_path = runtime_schema
                schema_manifest = {**schema_manifest, "reason": "SA failed after producing schema"}
                if runtime_schema is not None:
                    schema_manifest["schema_path"] = str(runtime_schema)
                stages.append(_stage("Schema Agent", "degraded", started, **schema_manifest, **_exception_details(exc)))
                final_manifest["schema_agent"] = schema_manifest
                progress.stage_done("SA 生成 schema", 5, total_stages, time.time() - started, extra="degraded")
            elif published_schema.exists():
                fallback_schema = _fallback_schema_path_for_subject(config, published_schema)
                config.schema_path = fallback_schema
                fallback_mode = (
                    "published_schema_reuse"
                    if fallback_schema.resolve() == published_schema.resolve()
                    else "base_schema_reuse"
                )
                schema_manifest = {
                    "run_id": f"schema_agent_degraded_{sanitize_token(run_id)}",
                    "mode": fallback_mode,
                    "schema_path": str(fallback_schema),
                    "reason": (
                        "SA failed, using previously published schema"
                        if fallback_mode == "published_schema_reuse"
                        else "SA failed, using subject-neutral base schema"
                    ),
                    **_exception_details(exc),
                }
                stages.append(_stage("Schema Agent", "degraded", started, **schema_manifest))
                final_manifest["schema_agent"] = schema_manifest
                progress.stage_done("SA 生成 schema", 5, total_stages, time.time() - started, extra=schema_manifest["reason"])
            else:
                return fail_stage(
                    display_name="SA 生成 schema",
                    stage_number=5,
                    stage_name="Schema Agent",
                    started=started,
                    exc=exc,
                    **schema_manifest,
                )
    else:
        started = time.time()
        progress.stage_banner("SA 生成 schema", 5, total_stages)
        provided_schema = Path(config.schema_path)
        if config.reuse_schema_path_when_schema_agent_disabled and provided_schema.exists():
            config.schema_path = provided_schema
            schema_mode = "cached_schema_reuse"
            schema_reason = "--no-schema-agent，复用上一次可用 schema"
        else:
            config.schema_path = _fallback_schema_path_for_subject(
                config,
                resolve_published_schema_path(config.standards_dir),
            )
            schema_mode = "disabled"
            schema_reason = "--no-schema-agent，跳过"
        schema_manifest = {
            "run_id": f"schema_agent_disabled_{sanitize_token(run_id)}",
            "mode": schema_mode,
            "schema_path": str(config.schema_path),
        }
        stages.append(_stage("Schema Agent", "skipped", started, **schema_manifest))
        final_manifest["schema_agent"] = schema_manifest
        progress.stage_done("SA 生成 schema", 5, total_stages, time.time() - started, extra=schema_reason)

    try:
        published_schema = resolve_published_schema_path(config.standards_dir)
        using_published_schema = Path(config.schema_path).resolve() == published_schema.resolve()
        schema_check = verify_schema_matches_published(config.schema_path, config.standards_dir)
        schema_check["runtime_schema"] = not using_published_schema
        final_manifest["schema_check"] = schema_check
        if using_published_schema and not schema_check["match"] and not config.allow_schema_mismatch:
            raise RuntimeError(
                "schema version mismatch between schema_path and published schema_agent slot; "
                f"schema_version={schema_check['schema_version']!r} "
                f"published_version={schema_check['published_version']!r}. "
                "Re-publish schema or pass --allow-schema-mismatch."
            )
    except Exception as exc:
        _record_stage_error(final_manifest, "Schema Agent", exc)
        for stage in reversed(stages):
            if stage.get("name") == "Schema Agent":
                stage["status"] = "failed"
                details = stage.setdefault("details", {})
                if isinstance(details, dict):
                    details.update(_exception_details(exc))
                break
        final_manifest["error_type"] = type(exc).__name__
        final_manifest["error_message"] = str(exc)
        progress.stage_failed("SA 生成 schema", 5, total_stages, str(exc))
        return _finalize_with_status(
            config,
            stages,
            final_manifest,
            report_path,
            secret_scan,
            run_id=run_id,
            total_stages=total_stages,
        )

    if config.stop_at == "schema":
        print("[STOP] --stop-at=schema，跳过 KG", file=os.sys.stderr)
        return _finalize_with_status(
            config,
            stages,
            final_manifest,
            report_path,
            secret_scan,
            run_id=run_id,
            total_stages=total_stages,
        )

    kg_manifest: dict[str, Any] = {}
    started = time.time()
    progress.stage_banner("KG 抽取", 6, total_stages)
    try:
        kg_manifest = run_kg_pipeline(
            KgExtractionRunConfig(
                enhanced_md_paths=enhanced_paths,
                sections_index_path=sections_index,
                standards_dir=config.standards_dir,
                schema_path=config.schema_path,
                run_id=f"kg_{run_id}",
                mock=config.mock,
                node_model=config.node_model,
                edge_model=config.edge_model,
                standard_model=config.standard_model,
                validation_provider=config.validation_provider,
                validation_model=config.validation_model,
                validation_base_url=config.validation_base_url,
                validation_api_key_env=config.validation_api_key_env,
                max_revision_rounds=config.max_revision_rounds,
                work_root=config.kg_work_root,
                output_root=config.kg_output_root,
                node_batch_size=config.node_batch_size,
                qwen_timeout_seconds=config.qwen_timeout_seconds,
                qwen_retry_attempts=config.qwen_retry_attempts,
                qwen_timeout_retry_attempts=config.qwen_timeout_retry_attempts,
                qwen_timeout_retry_budget_seconds=config.qwen_timeout_retry_budget_seconds,
                qwen_max_tokens=config.qwen_max_tokens,
                qwen_max_input_tokens=config.qwen_max_input_tokens,
                source_context_ids=[str(item).strip() for item in config.source_context_ids if str(item).strip()],
                section_char_limit=config.section_char_limit,
                edge_batch_size=config.edge_batch_size,
                resume=config.resume,
            )
        )
    except Exception as exc:
        return fail_stage(
            display_name="KG 抽取",
            stage_number=6,
            stage_name="KG Extraction",
            started=started,
            exc=exc,
            **kg_manifest,
        )
    kg_status = str(kg_manifest.get("status", "passed"))
    stages.append(_stage("KG Extraction", kg_status, started, **kg_manifest))
    final_manifest["kg_manifest"] = kg_manifest
    final_manifest["kg_artifacts"] = _kg_artifact_status(kg_manifest)
    progress.stage_done(
        "KG 抽取",
        6,
        total_stages,
        time.time() - started,
        extra=(
            f"counted_nodes={_manifest_count(kg_manifest, 'counted_nodes')}, "
            f"counted_edges={_manifest_count(kg_manifest, 'counted_edges')}, "
            f"total_nodes={_manifest_count(kg_manifest, 'accepted_nodes')}, "
            f"total_edges={_manifest_count(kg_manifest, 'accepted_edges')}, "
            f"triples={_manifest_count(kg_manifest, 'triples')}"
        ),
    )
    return _finalize_with_status(
        config,
        stages,
        final_manifest,
        report_path,
        secret_scan,
        run_id=run_id,
        total_stages=total_stages,
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the FaMAS PDF-to-KG pipeline.")
    parser.add_argument("--pdf", default=None, help="PDF path. Defaults to the only PDF in textbook.")
    parser.add_argument(
        "--api-key-file",
        default=None,
        help="Optional two-line API key file. Defaults to API keys from environment variables.",
    )
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--standards-dir", default=str(DEFAULT_STANDARDS_DIR))
    parser.add_argument("--schema-path", default=str(DEFAULT_SCHEMA_PATH))
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--subject", default="")
    parser.add_argument("--grade", default="high_school")
    parser.add_argument("--publisher", default="sujiao")
    parser.add_argument("--mock", action="store_true")
    parser.add_argument(
        "--stop-at",
        default="kg",
        choices=["pdf", "segment", "ita", "ipa", "schema", "kg"],
        help="提前退出。默认 kg=跑完全部。ipa=跑到 IPA 结束、跳过 SA/KG。",
    )
    parser.add_argument("--quiet", action="store_true", help="Suppress progress output on stderr.")
    parser.add_argument("--overwrite-pdf-md", action="store_true")
    parser.add_argument(
        "--no-pdf-text-fallback",
        action="store_true",
        help="Fail when MinerU is unavailable instead of falling back to text-only PDF extraction.",
    )
    parser.add_argument("--taxonomy-sample-size", type=int, default=None)
    parser.add_argument("--taxonomy-sample-ratio", type=float, default=0.6)
    parser.add_argument("--taxonomy-batch-size", type=int, default=20)
    parser.add_argument("--taxonomy-max-parallel-workers", type=int, default=2)
    parser.add_argument("--ipa-batch-size", type=int, default=10)
    parser.add_argument("--vision-model", default=DEFAULT_VISION_MODEL)
    parser.add_argument("--verify-vision-model", default=DEFAULT_VERIFY_VISION_MODEL)
    parser.add_argument("--critic-revision-rounds", type=int, default=5)
    parser.add_argument("--no-ipa-resume", action="store_true", help="禁用 IPA per-image checkpoint resume,默认启用")
    parser.add_argument(
        "--per-image-hard-timeout-seconds",
        type=int,
        default=600,
        help="IPA 单图 round2 处理硬总时长上限,超过即跳过该图",
    )
    parser.add_argument("--no-schema-agent", action="store_true")
    parser.add_argument(
        "--reuse-schema-path-when-schema-agent-disabled",
        action="store_true",
        help="When --no-schema-agent is set, use --schema-path directly if that file exists.",
    )
    parser.add_argument(
        "--no-publish-schema-standards",
        action="store_true",
        help="Run Schema Agent without publishing its output into the shared standards directory.",
    )
    parser.add_argument("--sa-human-rules", default=str(DEFAULT_SA_HUMAN_RULES))
    parser.add_argument("--sa-base-schema", default=str(DEFAULT_SA_BASE_SCHEMA))
    parser.add_argument("--sa-rounds", type=int, default=3)
    parser.add_argument("--node-model", default=DEFAULT_TEXT_MODEL)
    parser.add_argument("--edge-model", default=DEFAULT_TEXT_MODEL)
    parser.add_argument("--standard-model", default=DEFAULT_TEXT_MODEL)
    parser.add_argument("--sa-model", default=DEFAULT_SCHEMA_AGENT_MODEL)
    parser.add_argument("--validation-provider", default=DEFAULT_VALIDATION_PROVIDER)
    parser.add_argument("--validation-model", default=DEFAULT_VALIDATION_MODEL)
    parser.add_argument("--validation-base-url", default=DEFAULT_VALIDATION_BASE_URL)
    parser.add_argument("--validation-api-key-env", default=DEFAULT_VALIDATION_API_KEY_ENV)
    parser.add_argument("--max-revision-rounds", type=int, default=5)
    parser.add_argument("--allow-schema-mismatch", action="store_true")
    parser.add_argument("--llm-seed", type=int, default=None)
    parser.add_argument("--node-batch-size", type=int, default=1)
    parser.add_argument("--edge-batch-size", type=int, default=1)
    parser.add_argument("--qwen-timeout-seconds", type=int, default=120)
    parser.add_argument("--qwen-retry-attempts", type=int, default=3)
    parser.add_argument("--qwen-timeout-retry-attempts", type=int, default=2)
    parser.add_argument("--qwen-timeout-retry-budget-seconds", type=int, default=300)
    parser.add_argument("--qwen-max-tokens", type=int, default=8192)
    parser.add_argument("--qwen-max-input-tokens", type=int, default=64000)
    parser.add_argument("--source-context-id", action="append", default=[])
    parser.add_argument("--section-char-limit", type=int, default=80000)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--segment-output-root", default=None)
    parser.add_argument("--taxonomy-output-root", default=None)
    parser.add_argument("--ipa-output-root", default=None)
    parser.add_argument("--schema-agent-work-root", default=None)
    parser.add_argument("--schema-agent-output-root", default=None)
    parser.add_argument("--kg-work-root", default=None)
    parser.add_argument("--kg-output-root", default=None)
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> FullPipelineConfig:
    pdf_path = Path(args.pdf) if args.pdf else discover_default_pdf()
    api_key_file = Path(args.api_key_file) if args.api_key_file else None
    kwargs: dict[str, Any] = dict(
        pdf_path=pdf_path,
        api_key_file=api_key_file,
        report_dir=Path(args.report_dir),
        standards_dir=Path(args.standards_dir),
        schema_path=Path(args.schema_path),
        run_id=args.run_id,
        run_id_explicit=True,
        subject=args.subject,
        grade=args.grade,
        publisher=args.publisher,
        mock=bool(args.mock),
        stop_at=args.stop_at,
        overwrite_pdf_md=bool(args.overwrite_pdf_md),
        allow_pdf_text_fallback=not bool(args.no_pdf_text_fallback),
        taxonomy_sample_size=args.taxonomy_sample_size if args.taxonomy_sample_size is not None else 200,
        taxonomy_sample_size_explicit=args.taxonomy_sample_size is not None,
        taxonomy_sample_ratio=args.taxonomy_sample_ratio,
        taxonomy_batch_size=args.taxonomy_batch_size,
        taxonomy_max_parallel_workers=args.taxonomy_max_parallel_workers,
        ipa_batch_size=args.ipa_batch_size,
        vision_model=args.vision_model,
        verify_vision_model=args.verify_vision_model,
        critic_revision_rounds=args.critic_revision_rounds,
        ipa_resume=not args.no_ipa_resume,
        per_image_hard_timeout_seconds=args.per_image_hard_timeout_seconds,
        enable_schema_agent=not args.no_schema_agent,
        reuse_schema_path_when_schema_agent_disabled=bool(args.reuse_schema_path_when_schema_agent_disabled),
        publish_schema_standards=not bool(args.no_publish_schema_standards),
        sa_human_rules=Path(args.sa_human_rules),
        sa_base_schema=Path(args.sa_base_schema),
        sa_rounds=args.sa_rounds,
        node_model=args.node_model,
        edge_model=args.edge_model,
        standard_model=args.standard_model,
        sa_model=args.sa_model,
        validation_provider=args.validation_provider,
        validation_model=args.validation_model,
        validation_base_url=args.validation_base_url,
        validation_api_key_env=args.validation_api_key_env,
        max_revision_rounds=args.max_revision_rounds,
        allow_schema_mismatch=bool(args.allow_schema_mismatch),
        llm_seed=args.llm_seed,
        node_batch_size=args.node_batch_size,
        edge_batch_size=args.edge_batch_size,
        qwen_timeout_seconds=args.qwen_timeout_seconds,
        qwen_retry_attempts=args.qwen_retry_attempts,
        qwen_timeout_retry_attempts=args.qwen_timeout_retry_attempts,
        qwen_timeout_retry_budget_seconds=args.qwen_timeout_retry_budget_seconds,
        qwen_max_tokens=args.qwen_max_tokens,
        qwen_max_input_tokens=args.qwen_max_input_tokens,
        source_context_ids=[str(item).strip() for item in args.source_context_id if str(item).strip()],
        section_char_limit=args.section_char_limit,
        resume=not args.no_resume,
    )
    if args.segment_output_root:
        kwargs["segment_output_root"] = Path(args.segment_output_root)
    if args.taxonomy_output_root:
        kwargs["taxonomy_output_root"] = Path(args.taxonomy_output_root)
    if args.ipa_output_root:
        kwargs["ipa_output_root"] = Path(args.ipa_output_root)
    if args.schema_agent_work_root:
        kwargs["schema_agent_work_root"] = Path(args.schema_agent_work_root)
    if args.schema_agent_output_root:
        kwargs["schema_agent_output_root"] = Path(args.schema_agent_output_root)
    if args.kg_work_root:
        kwargs["kg_work_root"] = Path(args.kg_work_root)
    if args.kg_output_root:
        kwargs["kg_output_root"] = Path(args.kg_output_root)
    return FullPipelineConfig(**kwargs)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if getattr(args, "quiet", False):
        progress.set_quiet(True)
    config = config_from_args(args)
    manifest = run_full_pipeline(config)
    printable = {
        "run_id": manifest.get("run_id"),
        "status": manifest.get("status"),
        "report_path": manifest.get("report_path"),
        "manifest_path": manifest.get("manifest_path"),
        "kg_artifacts": manifest.get("kg_artifacts"),
        "secret_scan": manifest.get("secret_scan"),
        "error_type": manifest.get("error_type", ""),
        "error_message": manifest.get("error_message", ""),
    }
    print(json.dumps(printable, ensure_ascii=False, indent=2))
    return 0 if manifest.get("status") == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
