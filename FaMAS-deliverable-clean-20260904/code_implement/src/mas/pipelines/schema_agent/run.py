"""CLI and one-shot orchestration for Schema Agent v2."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable, Sequence

from mas.config.models import get_model
from mas.pipelines.common.usage_tracker import usage_snapshot

from .agent import ModelNotConfiguredError, process_merge, process_observation
from .auditor import audit_merge_json, audit_observation_json_with_result, merge_base_and_extensions
from .prompt_builder import (
    build_merge_prompt,
    build_observation_prompt,
    load_json_file,
    load_standards,
    load_text_file,
)
from .publish_standard import PublishValidationError, publish_schema_standard
from .sampler import SampleUnit, build_section_contexts, sample_section_windows
from .schema_io import (
    ensure_work_tree,
    jsonable,
    make_run_id,
    unique_run_dir,
    write_final_package,
    write_input_snapshot,
    write_json,
)


_SCHEMA_MODEL = get_model("schema_agent")
DEFAULT_MODEL = str(_SCHEMA_MODEL.get("name", "qwen3.5-flash"))
DEFAULT_API_KEY_ENV = str(_SCHEMA_MODEL.get("api_key_env", "DASHSCOPE_API_KEY"))
DEFAULT_ROUNDS = 3
DEFAULT_MAX_INPUT_TOKENS = 64000
DEFAULT_MAX_OUTPUT_TOKENS = 8192
DEFAULT_SEED = 42
SCHEMA_CONTRACT = "label_property_v2"
DEFAULT_STANDARDS_DIR = Path("code_implement") / "data" / "standards"

FINAL_SCHEMA_KEYS = [
    "schema_version",
    "textbook_profile",
    "node_labels",
    "edge_labels",
    "shared_property_types",
    "evidence_policy",
    "confidence_policy",
    "extraction_boundaries",
]


@dataclass
class SchemaRunConfig:
    enhanced_md: list[Path]
    sections_index: Path
    human_rules: Path
    base_schema: Path
    standards_dir: Path
    work_root: Path
    output_root: Path
    rounds: int = DEFAULT_ROUNDS
    max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS
    model_name: str = DEFAULT_MODEL
    mock: bool = False
    seed: int = DEFAULT_SEED
    run_label: str | None = None
    model_config: dict[str, Any] | None = None
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS
    sa_report_root: Path | None = None
    publish_standards: bool = True
    standards_publish_dir: Path = DEFAULT_STANDARDS_DIR


PromptTransform = Callable[[dict[str, Any], str], dict[str, Any]]


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Schema Agent v2.")
    parser.add_argument("--enhanced-md", action="append", required=True, help="IPA enhanced Markdown file path.")
    parser.add_argument("--sections-index", required=True, help="sections_index.json path.")
    parser.add_argument("--human-rules", required=True, help="Human rules markdown path.")
    parser.add_argument("--base-schema", required=True, help="Human base schema JSON path.")
    parser.add_argument(
        "--standards-dir",
        default=str(Path("code_implement") / "data" / "standards"),
        help="Shared standards directory.",
    )
    parser.add_argument(
        "--work-root",
        default=str(Path("code_implement") / "data" / "intermediate" / "schema_outputs"),
        help="Intermediate schema output root.",
    )
    parser.add_argument(
        "--output-root",
        default=str(Path("code_implement") / "data" / "output" / "schema_outputs"),
        help="Final schema output root.",
    )
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS, help=f"Default {DEFAULT_ROUNDS}.")
    parser.add_argument(
        "--max-input-tokens",
        type=int,
        default=DEFAULT_MAX_INPUT_TOKENS,
        help=f"Default {DEFAULT_MAX_INPUT_TOKENS}.",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Default {DEFAULT_MODEL}.")
    parser.add_argument(
        "--max-output-tokens",
        type=int,
        default=DEFAULT_MAX_OUTPUT_TOKENS,
        help=f"Default {DEFAULT_MAX_OUTPUT_TOKENS}.",
    )
    parser.add_argument("--mock", action="store_true", help="Enable mock model mode for tests.")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"Default {DEFAULT_SEED}.")
    parser.add_argument("--run-id", default=None, help="Optional run id label appended after timestamp.")
    parser.add_argument(
        "--sa-report-root",
        default=None,
        help="Reserved for experiment runner report export; one-shot run ignores it.",
    )
    parser.add_argument(
        "--standards-publish-dir",
        default=str(DEFAULT_STANDARDS_DIR),
        help="Shared standards directory for automatic final schema publishing.",
    )
    parser.add_argument(
        "--no-publish-standards",
        action="store_true",
        help="Disable automatic publishing of clean real final schema into standards.",
    )
    return parser.parse_args(argv)


def config_from_args(args: argparse.Namespace) -> SchemaRunConfig:
    model_config = {
        "name": args.model,
        "api_key_env": DEFAULT_API_KEY_ENV,
        "max_input_tokens": args.max_input_tokens,
        "max_tokens": args.max_output_tokens,
    }
    return SchemaRunConfig(
        enhanced_md=[Path(item) for item in args.enhanced_md],
        sections_index=Path(args.sections_index),
        human_rules=Path(args.human_rules),
        base_schema=Path(args.base_schema),
        standards_dir=Path(args.standards_dir),
        work_root=Path(args.work_root),
        output_root=Path(args.output_root),
        rounds=args.rounds,
        max_input_tokens=args.max_input_tokens,
        model_name=args.model,
        mock=bool(args.mock),
        seed=args.seed,
        run_label=args.run_id,
        model_config=model_config,
        max_output_tokens=args.max_output_tokens,
        sa_report_root=Path(args.sa_report_root) if args.sa_report_root else None,
        publish_standards=not bool(args.no_publish_standards),
        standards_publish_dir=Path(args.standards_publish_dir),
    )


def _samples_by_round(samples: list[SampleUnit]) -> dict[str, list[SampleUnit]]:
    grouped: dict[str, list[SampleUnit]] = {}
    for sample in samples:
        grouped.setdefault(sample.round_id, []).append(sample)
    return grouped


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_contract_schema(merged_schema: dict[str, Any]) -> dict[str, Any]:
    return {key: jsonable(merged_schema.get(key, [] if key.endswith("labels") else {})) for key in FINAL_SCHEMA_KEYS if key in merged_schema}


def _model_config(config: SchemaRunConfig) -> dict[str, Any]:
    model_config = config.model_config or {
        "name": config.model_name,
        "max_input_tokens": config.max_input_tokens,
        "max_tokens": config.max_output_tokens,
        "api_key_env": DEFAULT_API_KEY_ENV,
    }
    model_config = dict(model_config)
    model_config.setdefault("usage_stage", "SA")
    return model_config


def _run_observations(
    *,
    samples: list[SampleUnit],
    human_rules: str,
    base_schema: dict[str, Any],
    standards: list[dict[str, str]],
    work_dir: Path,
    config: SchemaRunConfig,
    prompt_transform: PromptTransform | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    observations: list[dict[str, Any]] = []
    observation_audit: list[dict[str, Any]] = []
    model_config = _model_config(config)
    for round_id, round_samples in _samples_by_round(samples).items():
        prompt = build_observation_prompt(
            round_id=round_id,
            sample_units=round_samples,
            human_rules=human_rules,
            base_schema=base_schema,
            standards=standards,
        )
        if prompt_transform is not None:
            prompt = prompt_transform(prompt, "observation")
        write_json(work_dir / "observations" / f"{round_id}_prompt.json", prompt)
        try:
            response = process_observation(
                prompt,
                round_samples,
                mock=config.mock,
                model_config=model_config,
            )
            response_path = work_dir / "observations" / f"{round_id}_response.json"
            response_path.parent.mkdir(parents=True, exist_ok=True)
            response_path.write_text(response.raw_response, encoding="utf-8")
            result = audit_observation_json_with_result(
                response.raw_response,
                round_id,
                {sample.sample_id for sample in round_samples},
                tolerant=True,
            )
        except (ModelNotConfiguredError, ValueError, json.JSONDecodeError) as exc:
            observation_audit.append(
                {
                    "round_id": round_id,
                    "status": "failed",
                    "error": str(exc),
                    "sample_ids": [sample.sample_id for sample in round_samples],
                }
            )
            continue
        if result.observation is None:
            observation_audit.append(
                {
                    "round_id": round_id,
                    "status": "failed",
                    "error": result.error,
                    "sample_ids": [sample.sample_id for sample in round_samples],
                    "warnings": result.warnings,
                    "dropped_candidates": result.dropped_candidates,
                }
            )
            continue
        observations.append(result.observation)
        write_json(work_dir / "observations" / f"{round_id}_observation.json", result.observation)
        observation_audit.append(
            {
                "round_id": round_id,
                "status": result.status,
                "sample_ids": [sample.sample_id for sample in round_samples],
                "warnings": result.warnings,
                "dropped_candidates": result.dropped_candidates,
            }
        )
    return observations, observation_audit


def _run_merge(
    *,
    observations: list[dict[str, Any]],
    human_rules: str,
    base_schema: dict[str, Any],
    standards: list[dict[str, str]],
    work_dir: Path,
    config: SchemaRunConfig,
    prompt_transform: PromptTransform | None = None,
) -> tuple[dict[str, Any], str, dict[str, Any]]:
    prompt = build_merge_prompt(
        observations=observations,
        human_rules=human_rules,
        base_schema=base_schema,
        standards=standards,
    )
    if prompt_transform is not None:
        prompt = prompt_transform(prompt, "merge")
    write_json(work_dir / "merge" / "merge_prompt.json", prompt)
    response = process_merge(
        prompt,
        observations,
        base_schema,
        mock=config.mock,
        model_config=_model_config(config),
    )
    response_path = work_dir / "merge" / "merge_response.json"
    response_path.parent.mkdir(parents=True, exist_ok=True)
    response_path.write_text(response.raw_response, encoding="utf-8")
    merge_data = audit_merge_json(response.raw_response)
    merged_schema, merge_audit = merge_base_and_extensions(base_schema, merge_data["schema_extensions"])
    report = str(merge_data.get("schema_design_report") or "# Schema Design Report\n\nNo model report provided.")
    return merged_schema, report, merge_audit


def run_pipeline(
    config: SchemaRunConfig,
    *,
    human_rules_override: str | None = None,
    base_schema_override: dict[str, Any] | None = None,
    prompt_transform: PromptTransform | None = None,
    run_id_override: str | None = None,
) -> dict[str, Any]:
    if config.rounds <= 0:
        raise ValueError("rounds must be positive")
    if config.max_input_tokens <= 0:
        raise ValueError("max_input_tokens must be positive")
    if config.max_output_tokens <= 0:
        raise ValueError("max_output_tokens must be positive")

    run_id = run_id_override or make_run_id(mock=config.mock, label=config.run_label)
    work_dir = unique_run_dir(config.work_root.resolve(), run_id)
    output_dir = unique_run_dir(config.output_root.resolve(), work_dir.name)
    ensure_work_tree(work_dir)

    human_rules = human_rules_override if human_rules_override is not None else load_text_file(config.human_rules)
    base_schema = base_schema_override if base_schema_override is not None else load_json_file(config.base_schema)
    standards = load_standards(config.standards_dir)
    contexts = build_section_contexts(config.enhanced_md, config.sections_index)
    samples = sample_section_windows(
        contexts,
        rounds=config.rounds,
        seed=config.seed,
        max_input_tokens=config.max_input_tokens,
    )
    write_input_snapshot(
        run_dir=work_dir,
        section_contexts=contexts,
        sample_units=samples,
        standards=standards,
    )

    observations, observation_audit = _run_observations(
        samples=samples,
        human_rules=human_rules,
        base_schema=base_schema,
        standards=standards,
        work_dir=work_dir,
        config=config,
        prompt_transform=prompt_transform,
    )
    write_json(work_dir / "audit" / "observation_audit.json", observation_audit)
    if not observations:
        raise ValueError("no usable observations; cannot build final schema")

    merged_schema, report, merge_audit = _run_merge(
        observations=observations,
        human_rules=human_rules,
        base_schema=base_schema,
        standards=standards,
        work_dir=work_dir,
        config=config,
        prompt_transform=prompt_transform,
    )
    role_decisions = merged_schema.get("ontology_role_decisions", [])
    write_json(work_dir / "audit" / "ontology_role_decisions.json", role_decisions)
    write_json(work_dir / "audit" / "merge_audit.json", merge_audit)
    final_schema = _clean_contract_schema(merged_schema)

    manifest = {
        "run_id": work_dir.name,
        "work_dir": str(work_dir),
        "output_dir": str(output_dir),
        "schema_contract": SCHEMA_CONTRACT,
        "mock": config.mock,
        "model": config.model_name,
        "rounds": config.rounds,
        "max_input_tokens": config.max_input_tokens,
        "max_output_tokens": config.max_output_tokens,
        "seed": config.seed,
        "created_at": _utc_timestamp(),
        "enhanced_md": [str(Path(path).resolve()) for path in config.enhanced_md],
        "sections_index": str(config.sections_index.resolve()),
        "human_rules": str(config.human_rules.resolve()),
        "base_schema": str(config.base_schema.resolve()),
        "standards": [{"file": item["file"], "path": item["path"], "chars": len(item["content"])} for item in standards],
        "source_inputs": {
            "section_context_count": len(contexts),
            "sample_unit_count": len(samples),
            "standards_files": [standard["file"] for standard in standards],
        },
        "usable_observation_rounds": [observation["round_id"] for observation in observations],
        "failed_observation_rounds": [
            item["round_id"] for item in observation_audit if item.get("status") == "failed"
        ],
        "audit_summary": {
            "observation_audit": observation_audit,
            "merge_audit": merge_audit,
            "ontology_role_decision_count": len(role_decisions) if isinstance(role_decisions, list) else 0,
            "schema_extensions": merged_schema.get("schema_extensions", {}),
        },
        "standards_publish": {"published": False, "reason": "pending"},
        "token_usage": usage_snapshot(),
    }
    write_final_package(output_dir, final_schema, report, manifest)
    if not config.publish_standards:
        manifest["standards_publish"] = {"published": False, "reason": "disabled by --no-publish-standards"}
    elif config.mock:
        manifest["standards_publish"] = {"published": False, "reason": "mock runs are not published"}
    else:
        try:
            manifest["standards_publish"] = publish_schema_standard(output_dir, config.standards_publish_dir)
        except PublishValidationError as exc:
            manifest["standards_publish"] = {"published": False, "reason": str(exc)}
    write_final_package(output_dir, final_schema, report, manifest)
    write_json(work_dir / "manifest.json", manifest)
    return jsonable(manifest)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    config = config_from_args(args)
    try:
        manifest = run_pipeline(config)
    except ModelNotConfiguredError as exc:
        print(f"Schema Agent model error: {exc}")
        return 2
    print(json.dumps(jsonable(manifest), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
