"""CLI and orchestration for Image Taxonomy Agent v1."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime
import json
import shutil
import time
from pathlib import Path
from typing import Any, Sequence

import yaml

from mas.common.progress import step
from mas.config.models import get_model
from mas.pipelines.common.usage_tracker import usage_snapshot

from .logger import JsonlLogger, TaxonomyLogRecord, utc_timestamp
from .observation_builder import build_evidence_pack, build_merge_prompt, build_observation_prompt
from .sampler import SampledImage, collect_images, resolve_sample_size, sample_images, shuffle_for_batches
from .taxonomy_agent import ModelNotConfiguredError, process_merge, process_observation_batch
from .taxonomy_auditor import (
    audit_merge_json,
    audit_observation_json_with_result,
    audit_selected_taxonomy,
)
from .taxonomy_io import ensure_run_tree, jsonable, unique_run_dir, write_json, write_jsonl


DEFAULT_SAMPLE_SIZE = 200
DEFAULT_BATCH_SIZE = 50
DEFAULT_SEED = 42
DEFAULT_MAX_PARALLEL_WORKERS = 2
DEFAULT_OBSERVATION_FAILURE_RATE_THRESHOLD = 0.3
_ITA_MODEL = get_model("ita_vision")
DEFAULT_MODEL = str(_ITA_MODEL.get("name", "qwen3-vl-flash"))
DEFAULT_API_KEY_ENV = str(_ITA_MODEL.get("api_key_env", "DASHSCOPE_API_KEY"))
DEFAULT_MAX_VISUAL_TOKENS_PER_IMAGE = 384


@dataclass
class TaxonomyRunConfig:
    sections_dir: Path
    sections_index: Path | None
    image_source_dir: Path | None
    output_root: Path
    mock: bool = False
    sample_size: int = DEFAULT_SAMPLE_SIZE
    sample_ratio: float = 0.6
    use_ratio_sampling: bool = True
    sample_size_explicit: bool = False
    batch_size: int = DEFAULT_BATCH_SIZE
    max_parallel_workers: int = DEFAULT_MAX_PARALLEL_WORKERS
    seed: int = DEFAULT_SEED
    run_label: str | None = None
    model_name: str = DEFAULT_MODEL
    max_visual_tokens_per_image: int = DEFAULT_MAX_VISUAL_TOKENS_PER_IMAGE
    model_config: dict[str, Any] | None = None


def make_run_id(mock: bool, label: str | None = None, now: datetime | None = None) -> str:
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    prefix = "taxonomy_mock" if mock else "taxonomy_real"
    suffix = f"_{label}" if label else ""
    return f"{prefix}_{stamp}{suffix}"


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Image Taxonomy Agent v1.")
    parser.add_argument("--sections-dir", required=True, help="markdown_segmenter sections/ directory.")
    parser.add_argument("--sections-index", default=None, help="Optional sections_index.json.")
    parser.add_argument("--image-source-dir", default=None, help="Optional source images directory.")
    parser.add_argument(
        "--output-root",
        default=str(Path("code_implement") / "data" / "intermediate" / "taxonomy_outputs"),
        help="Taxonomy output root.",
    )
    parser.add_argument("--config", default=None, help="Optional YAML config path.")
    parser.add_argument("--mock", action="store_true", default=None, help="Enable mock taxonomy model mode.")
    parser.add_argument("--no-mock", action="store_false", dest="mock", help="Disable mock taxonomy model mode.")
    parser.add_argument("--sample-size", type=int, default=None, help=f"Default {DEFAULT_SAMPLE_SIZE}.")
    parser.add_argument("--sample-ratio", type=float, default=None, help="Default 0.6 when sample size is not explicit.")
    parser.add_argument("--batch-size", type=int, default=None, help=f"Default {DEFAULT_BATCH_SIZE}.")
    parser.add_argument("--max-parallel-workers", type=int, default=None, help=f"Default {DEFAULT_MAX_PARALLEL_WORKERS}.")
    parser.add_argument("--seed", type=int, default=None, help=f"Default {DEFAULT_SEED}.")
    parser.add_argument("--run-id", default=None, help="Optional run id label appended after timestamp.")
    parser.add_argument("--model", default=None, help=f"Default {DEFAULT_MODEL}.")
    parser.add_argument(
        "--max-visual-tokens-per-image",
        type=int,
        default=None,
        help=f"Default {DEFAULT_MAX_VISUAL_TOKENS_PER_IMAGE}.",
    )
    return parser.parse_args(argv)


def load_taxonomy_agent_config(config_path: str | Path | None) -> dict[str, Any]:
    if not config_path:
        return {}
    path = Path(config_path)
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data.get("taxonomy_agent", data)


def _config_model_value(config: dict[str, Any], key: str, default: Any) -> Any:
    model = config.get("model")
    if isinstance(model, dict) and key in model:
        return model[key]
    return config.get(key, default)


def config_from_args(args: argparse.Namespace) -> TaxonomyRunConfig:
    config = load_taxonomy_agent_config(args.config)
    mock = bool(args.mock) if args.mock is not None else bool(config.get("mock", False))
    model_name = str(args.model or _config_model_value(config, "name", DEFAULT_MODEL))
    model_config = dict(config.get("model", {})) if isinstance(config.get("model"), dict) else {}
    model_config.setdefault("name", model_name)
    model_config.setdefault("api_key_env", DEFAULT_API_KEY_ENV)
    sample_size_explicit = args.sample_size is not None or "sample_size" in config
    return TaxonomyRunConfig(
        sections_dir=Path(args.sections_dir),
        sections_index=Path(args.sections_index) if args.sections_index else None,
        image_source_dir=Path(args.image_source_dir) if args.image_source_dir else None,
        output_root=Path(args.output_root),
        mock=mock,
        sample_size=int(args.sample_size or config.get("sample_size", DEFAULT_SAMPLE_SIZE)),
        sample_ratio=float(args.sample_ratio if args.sample_ratio is not None else config.get("sample_ratio", 0.6)),
        use_ratio_sampling=bool(config.get("use_ratio_sampling", True)),
        sample_size_explicit=sample_size_explicit,
        batch_size=int(args.batch_size or config.get("batch_size", DEFAULT_BATCH_SIZE)),
        max_parallel_workers=int(args.max_parallel_workers or config.get("max_parallel_workers", DEFAULT_MAX_PARALLEL_WORKERS)),
        seed=int(args.seed or config.get("seed", DEFAULT_SEED)),
        run_label=args.run_id,
        model_name=model_name,
        max_visual_tokens_per_image=int(
            args.max_visual_tokens_per_image
            or _config_model_value(config, "max_visual_tokens_per_image", DEFAULT_MAX_VISUAL_TOKENS_PER_IMAGE)
        ),
        model_config=model_config,
    )


def chunk_images(items: list[Any], batch_size: int) -> list[list[Any]]:
    if batch_size <= 0:
        raise ValueError("batch_size must be positive")
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


def _copy_optional_inputs(config: TaxonomyRunConfig, run_dir: Path) -> None:
    if config.sections_index and config.sections_index.exists():
        shutil.copy2(config.sections_index, run_dir / "inputs" / "sections_index.json")


def _warn_large_batch(config: TaxonomyRunConfig) -> str:
    visual_budget = config.batch_size * config.max_visual_tokens_per_image
    if config.batch_size >= 100 or visual_budget > 24000:
        return (
            f"batch_size={config.batch_size} may exceed Qwen2.5-VL-3B context after metadata/prompt tokens; "
            "consider lowering batch_size or max_visual_tokens_per_image"
        )
    return ""


def _sleep_retry(attempt: int, config: TaxonomyRunConfig) -> None:
    if getattr(config, "mock", False):
        return
    time.sleep(1.5 * attempt)


def _process_observation_batch_with_retry(
    *,
    batch: list[SampledImage],
    batch_id: str,
    config: TaxonomyRunConfig,
    run_dir: Path,
    logger: JsonlLogger,
    max_attempts: int = 3,
) -> tuple[Any | None, dict[str, Any]]:
    """Run one observation batch with retry and provenance files."""

    image_ids = [image.image_id for image in batch]
    last_error = ""
    for attempt in range(1, max_attempts + 1):
        prompt = build_observation_prompt(batch_id=batch_id, images=batch)
        try:
            response = process_observation_batch(
                prompt,
                image_ids,
                mock=config.mock,
                model_config=config.model_config,
            )
        except Exception as exc:
            last_error = f"call_failed: {type(exc).__name__}: {exc}"
            if attempt < max_attempts:
                _sleep_retry(attempt, config)
            continue
        write_json(run_dir / "observations" / f"{batch_id}_prompt_attempt{attempt}.json", prompt)
        (run_dir / "observations" / f"{batch_id}_response_attempt{attempt}.json").write_text(
            response.raw_response,
            encoding="utf-8",
        )
        try:
            audit_result = audit_observation_json_with_result(
                response.raw_response,
                batch_id,
                len(batch),
                set(image_ids),
                tolerant=True,
            )
        except ValueError as exc:
            last_error = f"audit_failed: {exc}"
            if attempt < max_attempts:
                _sleep_retry(attempt, config)
            continue
        if audit_result.observation is None:
            last_error = f"observation_none: {audit_result.error}"
            if attempt < max_attempts:
                _sleep_retry(attempt, config)
            continue

        write_json(run_dir / "observations" / f"{batch_id}_prompt.json", prompt)
        (run_dir / "observations" / f"{batch_id}_response.json").write_text(
            response.raw_response,
            encoding="utf-8",
        )
        audit_record = {
            "batch_id": batch_id,
            "status": audit_result.status,
            "image_count": len(batch),
            "group_count_used": len(audit_result.observation.observed_groups),
            "warnings": audit_result.warnings,
            "dropped_groups": audit_result.dropped_groups,
            "filtered_example_image_ids": audit_result.filtered_example_image_ids,
            "attempts": attempt,
        }
        if audit_result.error:
            audit_record["error"] = audit_result.error
        return audit_result.observation, audit_record

    audit_record = {
        "batch_id": batch_id,
        "status": "failed",
        "image_count": len(batch),
        "group_count_used": 0,
        "warnings": [],
        "attempts": max_attempts,
        "error": last_error,
    }
    return None, audit_record


def _run_observation_batches_parallel(
    *,
    batches: list[tuple[int, list[SampledImage]]],
    config: TaxonomyRunConfig,
    run_dir: Path,
    logger: JsonlLogger,
    run_id: str,
    worker: Any = _process_observation_batch_with_retry,
) -> tuple[list[Any], list[dict[str, Any]]]:
    observations: list[Any] = []
    observation_audit: list[dict[str, Any]] = []
    if not batches:
        return observations, observation_audit
    max_workers = min(len(batches), config.max_parallel_workers)
    if max_workers <= 0:
        raise ValueError("max_parallel_workers must be positive")

    def _run_one(batch_num: int, batch: list[SampledImage]) -> tuple[int, tuple[Any | None, dict[str, Any]]]:
        batch_id = f"batch_{batch_num:03d}"
        return batch_num, worker(batch=batch, batch_id=batch_id, config=config, run_dir=run_dir, logger=logger)

    results: dict[int, tuple[Any | None, dict[str, Any]]] = {}
    batch_by_num = {batch_num: batch for batch_num, batch in batches}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_run_one, batch_num, batch) for batch_num, batch in batches]
        for future in futures:
            batch_num, result = future.result()
            results[batch_num] = result

    completed = 0
    total_batches = len(results)
    for batch_num in sorted(results):
        completed += 1
        step(f"观察批次完成 [{completed}/{total_batches}]")
        batch_id = f"batch_{batch_num:03d}"
        batch = batch_by_num[batch_num]
        observation, audit_record = results[batch_num]
        observation_audit.append(audit_record)
        logger.write(
            TaxonomyLogRecord(
                run_id=run_id,
                timestamp=utc_timestamp(),
                stage="observation",
                batch_id=batch_id,
                status=audit_record["status"],
                message=audit_record.get("error", "; ".join(audit_record.get("warnings", []))),
                metadata={
                    "image_count": len(batch),
                    "mock": config.mock,
                    "attempts": audit_record.get("attempts"),
                },
            )
        )
        if observation is None:
            continue
        observations.append(observation)
        write_json(run_dir / "observations" / f"{batch_id}_observation.json", observation)
    return observations, observation_audit


def run_pipeline(config: TaxonomyRunConfig) -> dict[str, Any]:
    if config.sample_size <= 0:
        raise ValueError("sample_size must be positive")
    run_id = make_run_id(mock=config.mock, label=config.run_label)
    run_dir = unique_run_dir(config.output_root.resolve(), run_id)
    ensure_run_tree(run_dir)
    logger = JsonlLogger(run_dir / "logs" / f"{run_dir.name}.jsonl")
    warning = _warn_large_batch(config)
    if warning:
        logger.write(TaxonomyLogRecord(run_id=run_dir.name, timestamp=utc_timestamp(), stage="config", message=warning))

    _copy_optional_inputs(config, run_dir)
    all_images = collect_images(
        sections_dir=config.sections_dir,
        sections_index=config.sections_index,
        image_source_dir=config.image_source_dir,
    )
    available_images = [image for image in all_images if image.exists]
    if config.use_ratio_sampling and not config.sample_size_explicit:
        effective_sample_size = resolve_sample_size(
            len(available_images),
            ratio=config.sample_ratio,
            batch_size=config.batch_size,
        )
        sampling_mode = "ratio"
    else:
        effective_sample_size = config.sample_size
        sampling_mode = "explicit"
    sampled = sample_images(available_images, sample_size=effective_sample_size, seed=config.seed)
    # Use a derived seed so sampling and batch-assignment shuffling remain reproducible but independent.
    sampled = shuffle_for_batches(sampled, seed=config.seed + 1)
    write_json(run_dir / "inputs" / "sampled_images.json", [image.to_json() for image in sampled])
    write_jsonl(run_dir / "inputs" / "sampled_images.jsonl", [image.to_json() for image in sampled])

    batches = list(enumerate(chunk_images(sampled, config.batch_size), start=1))
    step(f"采样 {len(sampled)} 张图，分 {len(batches)} 批，并行观察...")
    observations, observation_audit = _run_observation_batches_parallel(
        batches=batches,
        config=config,
        run_dir=run_dir,
        logger=logger,
        run_id=run_dir.name,
    )

    write_json(run_dir / "audit" / "observation_audit.json", observation_audit)
    total_observation_batches = len(observation_audit)
    failed_observation_batches = sum(1 for item in observation_audit if item.get("status") == "failed")
    observation_failure_rate = (
        failed_observation_batches / total_observation_batches if total_observation_batches else 0.0
    )
    if failed_observation_batches:
        logger.write(
            TaxonomyLogRecord(
                run_id=run_dir.name,
                timestamp=utc_timestamp(),
                stage="observation",
                status="warning",
                message=(
                    "observation failure rate "
                    f"{observation_failure_rate:.2%} ({failed_observation_batches}/{total_observation_batches})"
                ),
                metadata={
                    "failed_batches": failed_observation_batches,
                    "total_batches": total_observation_batches,
                    "failure_rate": observation_failure_rate,
                    "failure_rate_threshold": DEFAULT_OBSERVATION_FAILURE_RATE_THRESHOLD,
                },
            )
        )
    if (
        total_observation_batches
        and observation_failure_rate > DEFAULT_OBSERVATION_FAILURE_RATE_THRESHOLD
    ):
        raise RuntimeError(
            "observation failure rate "
            f"{observation_failure_rate:.2%} exceeded threshold "
            f"{DEFAULT_OBSERVATION_FAILURE_RATE_THRESHOLD:.0%} "
            f"({failed_observation_batches}/{total_observation_batches} batches failed)"
        )
    if not observations:
        raise ValueError("no usable observation batches; cannot build taxonomy evidence")

    evidence_pack = build_evidence_pack(observations)
    write_json(run_dir / "merge" / "evidence_pack.json", evidence_pack)
    merge_prompt = build_merge_prompt(evidence_pack=evidence_pack)
    step("Merging final taxonomy...")
    merge_response = process_merge(
        merge_prompt,
        mock=config.mock,
        model_config=config.model_config,
    )
    write_json(run_dir / "merge" / "merge_prompt.json", merge_prompt)
    (run_dir / "merge" / "merge_response.json").write_text(merge_response.raw_response, encoding="utf-8")
    selected = audit_merge_json(merge_response.raw_response)
    selected["source"] = {
        "run_id": run_dir.name,
        "stage": "merge",
        "model": config.model_name,
        "mock": config.mock,
        "sample_size": len(sampled),
        "batch_size": config.batch_size,
    }
    audit_selected_taxonomy(selected)
    write_json(run_dir / "selected" / "selected_image_taxonomy.json", selected)
    write_json(run_dir / "audit" / "merge_taxonomy_audit.json", {"status": "passed", "item_count": len(selected["items"])})
    write_json(run_dir / "audit" / "selected_taxonomy_audit.json", {"status": "passed"})
    manifest = {
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "mock": config.mock,
        "model": config.model_name,
        "sample_size": len(sampled),
        "sample_ratio": config.sample_ratio,
        "effective_sample_size": effective_sample_size,
        "sampling_mode": sampling_mode,
        "batch_size": config.batch_size,
        "max_parallel_workers": config.max_parallel_workers,
        "parallel_workers_used": min(len(batches), config.max_parallel_workers) if batches else 0,
        "seed": config.seed,
        "total_images_available": len(all_images),
        "available_images_count": len(available_images),
        "usable_observation_batches": [observation.batch_id for observation in observations],
        "failed_observation_batches": [
            item["batch_id"] for item in observation_audit if item.get("status") == "failed"
        ],
        "observation_failed_batches": failed_observation_batches,
        "observation_total_batches": total_observation_batches,
        "observation_failure_rate": observation_failure_rate,
        "warning": warning,
        "selected_taxonomy": str(run_dir / "selected" / "selected_image_taxonomy.json"),
        "token_usage": usage_snapshot(),
    }
    write_json(run_dir / "manifest.json", manifest)
    logger.write(
        TaxonomyLogRecord(
            run_id=run_dir.name,
            timestamp=utc_timestamp(),
            stage="complete",
            metadata=jsonable(manifest),
        )
    )
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config = config_from_args(args)
    try:
        manifest = run_pipeline(config)
    except ModelNotConfiguredError as exc:
        print(f"Taxonomy Agent model error: {exc}")
        return 2
    print(json.dumps(jsonable(manifest), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
