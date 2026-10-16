#!/usr/bin/env python3
"""Convert PDFs under the FaMAS input directory to Markdown with MinerU.

This stage is adapted from K12-KGraph's ``src/kg/prepare_textbooks.py``. It
keeps the same MinerU-first behavior and Markdown selection logic, but uses MAS
paths:

- input PDFs: ``data/input/pdf``
- prepared Markdown: ``data/output/markdown``
- intermediate MinerU output and manifests: ``workspace/pdf_to_md``
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from mas.config.pipeline import PipelineConfig, load_config
from mas.utils.io import write_json

IGNORED_MARKDOWN_SUFFIXES = ("_content_list", "_model", "sections_index")


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _local_model_dir(project_root: Path) -> Optional[Path]:
    candidates: list[Path] = []
    for models_root in [
        project_root / ".models" / "modelscope" / "models",
        Path(os.getenv("MODELSCOPE_CACHE", "")) / "models" if os.getenv("MODELSCOPE_CACHE") else None,
        Path.home() / ".cache" / "modelscope" / "models",
    ]:
        if models_root is not None:
            candidates.extend(_model_dir_candidates(models_root))

    configured_dir = _model_dir_from_mineru_user_config()
    if configured_dir is not None:
        candidates.append(configured_dir)

    existing = [path for path in candidates if path.exists() and path.is_dir()]
    if not existing:
        return None
    return max(existing, key=lambda path: (path.stat().st_mtime_ns, path.as_posix()))


def _model_dir_candidates(models_root: Path) -> list[Path]:
    candidates: list[Path] = []
    if not models_root.exists():
        return candidates
    legacy_parent = models_root / "OpenDataLab"
    snapshot_parent = models_root / "OpenDataLab--PDF-Extract-Kit-1.0" / "snapshots"
    if legacy_parent.is_dir():
        candidates.extend(
            path for path in legacy_parent.iterdir() if path.is_dir() and path.name.startswith("PDF-Extract-Kit-1")
        )
    if snapshot_parent.is_dir():
        candidates.extend(path for path in snapshot_parent.iterdir() if path.is_dir())
    return candidates


def _model_dir_from_mineru_user_config() -> Optional[Path]:
    config_path = Path.home() / "mineru.json"
    if not config_path.exists():
        return None
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    model_dir = config.get("models-dir", {}).get("pipeline")
    if not model_dir:
        return None
    return Path(str(model_dir))


def _ensure_mineru_config(project_root: Path) -> Path:
    config_path = project_root / "config" / "mineru.json"
    model_dir = _local_model_dir(project_root)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config: Dict[str, Any] = {}
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            config = {}

    config.setdefault(
        "bucket_info",
        {
            "bucket-name-1": ["ak", "sk", "endpoint"],
            "bucket-name-2": ["ak", "sk", "endpoint"],
        },
    )
    config.setdefault(
        "latex-delimiter-config",
        {"display": {"left": "$$", "right": "$$"}, "inline": {"left": "$", "right": "$"}},
    )
    config.setdefault(
        "llm-aided-config",
        {
            "title_aided": {
                "api_key": "your_api_key",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "model": "qwen3.5-plus",
                "enable_thinking": False,
                "enable": False,
            }
        },
    )
    models_dir = config.setdefault("models-dir", {})
    if model_dir is not None:
        models_dir["pipeline"] = str(model_dir)
    models_dir.setdefault("vlm", "")
    config["config_version"] = "1.3.2"
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=4), encoding="utf-8")
    return config_path


def _default_mineru_device_mode() -> str:
    try:
        import torch

        return "cuda" if torch.cuda.is_available() else "cpu"
    except Exception:
        return "cpu"


def _mineru_subprocess_env() -> Dict[str, str]:
    project_root = _project_root()
    local_cache = project_root / ".cache"
    local_models = project_root / ".models"
    local_tmp = project_root / ".tmp"
    for path in [
        local_cache / "pip",
        local_cache / "uv",
        local_models / "huggingface",
        local_models / "huggingface" / "hub",
        local_models / "modelscope",
        local_tmp,
    ]:
        path.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    scripts_dir = project_root / ".venv" / "Scripts"
    env["PATH"] = str(scripts_dir) + os.pathsep + env.get("PATH", "")
    env.setdefault("MINERU_MODEL_SOURCE", "local")
    env.setdefault("MINERU_DEVICE_MODE", _default_mineru_device_mode())
    env["MINERU_TOOLS_CONFIG_JSON"] = str(_ensure_mineru_config(project_root))
    env["PIP_CACHE_DIR"] = str(local_cache / "pip")
    env["UV_CACHE_DIR"] = str(local_cache / "uv")
    env["HF_HOME"] = str(local_models / "huggingface")
    env["HUGGINGFACE_HUB_CACHE"] = str(local_models / "huggingface" / "hub")
    env["MODELSCOPE_CACHE"] = str(local_models / "modelscope")
    env["TEMP"] = str(local_tmp)
    env["TMP"] = str(local_tmp)
    return env


def _resolve_mineru_command(command: str) -> List[str]:
    parts = shlex.split(command)
    if not parts:
        parts = ["mineru"]
    executable = Path(parts[0])
    if parts[0].lower() == "mineru" and not executable.is_absolute():
        local_python = _project_root() / ".venv" / "Scripts" / "python.exe"
        if local_python.exists():
            parts = [
                str(local_python),
                "-m",
                "mas.pipelines.pdf_to_md.mineru_pipeline_runner",
                *parts[1:],
            ]
    return parts


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Convert FaMAS input PDFs to Markdown with MinerU.")
    parser.add_argument("--config", default=None, help="Pipeline config path. Defaults to config/default.yaml.")
    parser.add_argument(
        "--pdf",
        action="append",
        default=None,
        help="Specific PDF path to process. Can be repeated. Defaults to every *.pdf in input_pdf_dir.",
    )
    parser.add_argument(
        "--filter-prefix",
        action="append",
        default=None,
        help="Only process PDFs whose stem matches one of these values.",
    )
    parser.add_argument("--limit", type=int, default=None, help="Process at most N PDFs.")
    parser.add_argument("--no-overwrite", action="store_true", help="Do not overwrite existing Markdown outputs.")
    parser.add_argument("--failure-report", default=None, help="Optional path to write failures as JSONL.")
    return parser.parse_args()


def _is_candidate_markdown(path: Path) -> bool:
    if path.suffix.lower() != ".md":
        return False
    return not any(token in path.stem for token in IGNORED_MARKDOWN_SUFFIXES)


def _markdown_sort_key(path: Path, root: Path, preferred_stem: str) -> Tuple[int, int, int, int, str]:
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    rel_text = rel.as_posix().lower()
    exact_stem = 0 if path.stem == preferred_stem else 1
    hybrid_hint = 0 if "hybrid" in rel_text else 1
    depth = len(rel.parts)
    try:
        size_score = -path.stat().st_size
    except OSError:
        size_score = 0
    return (exact_stem, hybrid_hint, depth, size_score, rel.as_posix())


def discover_markdown_output(raw_dir: Path, pdf_stem: str) -> Optional[Path]:
    """Pick the most likely Markdown file from a MinerU output directory."""
    candidates = [path for path in raw_dir.rglob("*.md") if _is_candidate_markdown(path)]
    if not candidates:
        return None
    candidates.sort(key=lambda path: _markdown_sort_key(path, raw_dir, pdf_stem))
    return candidates[0]


def _write_command_logs(book_dir: Path, stdout: str, stderr: str) -> None:
    (book_dir / "prepare_stdout.txt").write_text(stdout, encoding="utf-8")
    (book_dir / "prepare_stderr.txt").write_text(stderr, encoding="utf-8")


def _render_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


def denoise_markdown(text: str) -> str:
    text = str(text).replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    lines = []
    for line in text.split("\n"):
        stripped = re.sub(r" {2,}", " ", line).rstrip(" \t")
        if re.match(r"^\s*\d{1,4}\s*$", stripped):
            continue
        lines.append(stripped)
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() + "\n"


def _count_image_files(path: Path) -> int:
    if not path.exists() or not path.is_dir():
        return 0
    return sum(1 for item in path.iterdir() if item.is_file())


def _find_images_dir(root: Path) -> Path | None:
    if not root.exists():
        return None
    image_dirs = [path for path in root.rglob("images") if path.is_dir()]
    image_dirs.sort(key=_count_image_files, reverse=True)
    for candidate in image_dirs:
        if _count_image_files(candidate) > 0:
            return candidate
    return None


def _clear_publish_dir(config: PipelineConfig, book_prefix: str) -> None:
    publish_dir = Path(config.generated_book_md_for(book_prefix)).parent.resolve()
    output_root = Path(config.output_markdown_dir).resolve()
    if publish_dir == output_root or output_root not in publish_dir.parents:
        raise RuntimeError(f"refusing to clear unsafe publish directory: {publish_dir}")
    if publish_dir.exists():
        shutil.rmtree(publish_dir)


def _content_list_image_map(output_md: Path, mineru_raw_dir: Path) -> list[dict[str, Any]]:
    content_lists = sorted(path for path in mineru_raw_dir.glob("*_content_list.json") if path.is_file())
    if not content_lists:
        return []
    try:
        data = json.loads(content_lists[0].read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    counters: dict[int, int] = {}
    mappings: list[dict[str, Any]] = []
    for item in sorted(
        (entry for entry in data if isinstance(entry, dict) and entry.get("img_path")),
        key=lambda entry: int(entry.get("page_idx", 0)),
    ):
        page_idx = int(item.get("page_idx", 0))
        counters[page_idx] = counters.get(page_idx, 0) + 1
        old_rel = str(item.get("img_path", "")).replace("\\", "/")
        old_name = Path(old_rel).name
        new_name = f"page{page_idx:03d}_img{counters[page_idx]:03d}{Path(old_name).suffix or '.jpg'}"
        mappings.append(
            {
                "from": old_name,
                "to": new_name,
                "type": item.get("type"),
                "page_idx": page_idx,
                "from_rel": old_rel,
                "to_rel": f"images/{new_name}",
            }
        )
    return mappings


def _fallback_image_map_from_markdown(output_md: Path) -> list[dict[str, Any]]:
    # Used only when content_list is missing or unreadable; merge by set union if both sources are needed later.
    text = output_md.read_text(encoding="utf-8", errors="ignore")
    seen: dict[str, dict[str, Any]] = {}
    for match in re.finditer(r"!\[[^\]]*\]\((images/[^)]+)\)", text):
        old_rel = match.group(1).replace("\\", "/")
        old_name = Path(old_rel).name
        if old_rel in seen:
            continue
        seq = len(seen) + 1
        new_name = f"img_{seq:04d}{Path(old_name).suffix or '.jpg'}"
        seen[old_rel] = {
            "from": old_name,
            "to": new_name,
            "page_idx": None,
            "from_rel": old_rel,
            "to_rel": f"images/{new_name}",
        }
    return list(seen.values())


def _replace_markdown_image_url(text: str, from_rel: str, to_rel: str) -> str:
    pattern = re.compile(rf"(!\[(?:\\.|[^\]\\])*\]\()({re.escape(from_rel)})(\))")
    return pattern.sub(lambda match: f"{match.group(1)}{to_rel}{match.group(3)}", text)


def _rename_images_and_update_md(output_md: Path, mineru_raw_dir: Path) -> list[dict[str, Any]]:
    images_dir = output_md.parent / "images"
    mappings = _content_list_image_map(output_md, mineru_raw_dir) or _fallback_image_map_from_markdown(output_md)
    text = output_md.read_text(encoding="utf-8", errors="ignore")
    rename_map: list[dict[str, Any]] = []
    for mapping in mappings:
        old_rel = str(mapping["from_rel"])
        new_rel = str(mapping["to_rel"])
        source = images_dir / str(mapping["from"])
        target = images_dir / str(mapping["to"])
        text = _replace_markdown_image_url(text, old_rel, new_rel)
        record = {
            "from": str(mapping["from"]),
            "to": str(mapping["to"]),
            "page_idx": mapping.get("page_idx"),
            "type": mapping.get("type"),
        }
        if source.exists():
            source.replace(target)
        else:
            record["warning"] = "source image missing"
        rename_map.append(record)
    output_md.write_text(text, encoding="utf-8")
    next_seq = 1
    for image in sorted(images_dir.iterdir()) if images_dir.exists() else []:
        if not image.is_file() or not re.fullmatch(r"[0-9a-fA-F]{64}", image.stem):
            continue
        while (images_dir / f"img_{next_seq:04d}{image.suffix}").exists():
            next_seq += 1
        target = images_dir / f"img_{next_seq:04d}{image.suffix}"
        image.rename(target)
        rename_map.append({"from": image.name, "to": target.name, "page_idx": None})
        next_seq += 1
    return rename_map


def _cached_prepare_info(config: PipelineConfig, book_prefix: str, output_md: Path, book_dir: Path) -> Dict[str, Any]:
    info: Dict[str, Any] = {"prepared_markdown": str(output_md)}
    manifest_path = config.generated_book_manifest_for(book_prefix)
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        manifest = {}
    if isinstance(manifest, dict):
        for key in ["raw_dir", "selected_markdown", "source_md"]:
            value = manifest.get(key)
            if value:
                info[key] = str(value)
        images_dir = manifest.get("images_dir")
        if images_dir:
            info["image_source_dir"] = str(images_dir)
            info["images_dir"] = str(images_dir)
    if "raw_dir" not in info:
        raw_candidate = book_dir / "mineru_output"
        if raw_candidate.exists():
            info["raw_dir"] = str(raw_candidate)
    if "image_source_dir" not in info and info.get("raw_dir"):
        found = _find_images_dir(Path(str(info["raw_dir"])))
        if found is not None:
            info["image_source_dir"] = str(found)
    if "image_source_dir" not in info:
        fallback = _find_images_dir(Path("code_implement") / "workspace" / "pdf_to_md" / book_prefix / "mineru_output")
        if fallback is not None:
            info["image_source_dir"] = str(fallback)
    return info


def prepare_from_pdf(
    config: PipelineConfig,
    source_pdf: Path,
    output_md: Optional[Path] = None,
    *,
    overwrite: bool = True,
) -> Tuple[bool, str, Dict[str, Any]]:
    """Run MinerU for one PDF and copy the selected Markdown to FaMAS output."""
    source_pdf = source_pdf.resolve()
    book_prefix = source_pdf.stem
    output_md = output_md or config.generated_book_md_for(book_prefix)
    book_dir = config.pdf_to_md_book_dir(book_prefix)

    if output_md.exists() and not overwrite:
        return True, "skipped_existing", _cached_prepare_info(config, book_prefix, output_md, book_dir)

    if overwrite and output_md == config.generated_book_md_for(book_prefix):
        _clear_publish_dir(config, book_prefix)

    raw_dir = book_dir / "mineru_output"
    raw_dir.mkdir(parents=True, exist_ok=True)

    mineru_command = str(config.mineru.get("command", "mineru")).strip() or "mineru"
    cmd = _resolve_mineru_command(mineru_command) + ["-p", str(source_pdf), "-o", str(raw_dir)]

    try:
        proc = subprocess.run(
            cmd,
            check=False,
            env=_mineru_subprocess_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except FileNotFoundError:
        manifest = {
            "book_prefix": book_prefix,
            "status": "mineru_not_found",
            "source_pdf": str(source_pdf),
            "command": cmd,
        }
        write_json(config.generated_book_manifest_for(book_prefix), manifest)
        return False, "mineru_not_found", {"command": cmd}

    _write_command_logs(book_dir, proc.stdout, proc.stderr)
    if proc.returncode != 0:
        manifest = {
            "book_prefix": book_prefix,
            "status": "mineru_failed",
            "source_pdf": str(source_pdf),
            "command": cmd,
            "returncode": proc.returncode,
        }
        write_json(config.generated_book_manifest_for(book_prefix), manifest)
        return False, "mineru_failed", {"command": cmd, "returncode": proc.returncode}

    chosen_md = discover_markdown_output(raw_dir, pdf_stem=source_pdf.stem)
    if chosen_md is None:
        manifest = {
            "book_prefix": book_prefix,
            "status": "markdown_not_found",
            "source_pdf": str(source_pdf),
            "command": cmd,
            "raw_dir": str(raw_dir),
        }
        write_json(config.generated_book_manifest_for(book_prefix), manifest)
        return False, "markdown_not_found", {"raw_dir": str(raw_dir)}

    output_md.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(chosen_md, output_md)
    output_md.write_text(denoise_markdown(output_md.read_text(encoding="utf-8", errors="ignore")), encoding="utf-8")
    images_dir = output_md.parent / "images"
    source_images = chosen_md.parent / "images"
    if source_images.exists() and source_images.is_dir():
        shutil.copytree(source_images, images_dir, dirs_exist_ok=True)
    image_rename_map = _rename_images_and_update_md(output_md, chosen_md.parent) if images_dir.exists() else []
    image_count = _count_image_files(images_dir)
    manifest = {
        "book_prefix": book_prefix,
        "status": "ok",
        "source_pdf": str(source_pdf),
        "source_md": _render_path(output_md),
        "source_kind": "pdf",
        "command": cmd,
        "raw_dir": str(raw_dir),
        "selected_markdown": str(chosen_md),
        "prepared_markdown": str(output_md),
        "images_dir": str(images_dir),
        "image_count": image_count,
        "image_rename_map": image_rename_map,
    }
    write_json(config.generated_book_manifest_for(book_prefix), manifest)
    return True, "ok", {
        "prepared_markdown": str(output_md),
        "selected_markdown": str(chosen_md),
        "images_dir": str(images_dir),
        "image_count": image_count,
        "image_rename_map": image_rename_map,
    }


def discover_pdfs(config: PipelineConfig, pdf_args: Optional[Sequence[str]]) -> List[Path]:
    """Return explicit PDFs or every top-level PDF in the configured input directory."""
    if pdf_args:
        return [Path(item).resolve() for item in pdf_args]
    return sorted(config.input_pdf_dir.glob("*.pdf"))


def selected_pdfs(
    pdfs: Iterable[Path],
    filter_prefixes: Optional[Sequence[str]],
    limit: Optional[int],
) -> List[Path]:
    wanted = {item.strip() for item in (filter_prefixes or []) if item.strip()}
    selected: List[Path] = []
    for pdf in pdfs:
        if wanted and pdf.stem not in wanted:
            continue
        selected.append(pdf)
        if limit and len(selected) >= limit:
            break
    return selected


def process_all(
    config_path: Optional[str],
    pdf_args: Optional[Sequence[str]],
    filter_prefixes: Optional[Sequence[str]],
    limit: Optional[int],
    overwrite: bool,
) -> Dict[str, Any]:
    config = load_config(config_path)
    summary: Dict[str, Any] = {
        "processed": 0,
        "success": 0,
        "skipped": 0,
        "failed": 0,
        "failures": [],
    }

    for source_pdf in selected_pdfs(discover_pdfs(config, pdf_args), filter_prefixes, limit):
        summary["processed"] += 1
        if not source_pdf.exists():
            status = "missing_source_pdf"
            info = {"source_pdf": str(source_pdf)}
            ok = False
        else:
            ok, status, info = prepare_from_pdf(config, source_pdf, overwrite=overwrite)

        if ok and status == "skipped_existing":
            summary["skipped"] += 1
            print(f"[SKIP] {source_pdf.stem} -> existing markdown")
        elif ok:
            summary["success"] += 1
            print(f"[OK] {source_pdf.stem} -> {info.get('prepared_markdown', '')}")
        else:
            summary["failed"] += 1
            failure = {
                "book_prefix": source_pdf.stem,
                "source_pdf": str(source_pdf),
                "status": status,
                "info": info,
            }
            summary["failures"].append(failure)
            print(f"[FAIL] {source_pdf.stem} ({status})")

    return summary


def main() -> None:
    args = parse_args()
    summary = process_all(
        config_path=args.config,
        pdf_args=args.pdf,
        filter_prefixes=args.filter_prefix,
        limit=args.limit,
        overwrite=not args.no_overwrite,
    )

    if args.failure_report:
        report_path = Path(args.failure_report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("w", encoding="utf-8") as handle:
            for item in summary["failures"]:
                handle.write(json.dumps(item, ensure_ascii=False) + "\n")

    print("\n===== SUMMARY =====")
    print(json.dumps({k: v for k, v in summary.items() if k != "failures"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
