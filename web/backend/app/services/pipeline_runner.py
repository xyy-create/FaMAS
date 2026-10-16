from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import traceback

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decrypt_secret_with_metadata, encrypt_secret
from app.core.time import utc_now_naive
from app.db.session import SessionLocal
from app.models.api_setting import ApiSetting
from app.models.document import Document
from app.models.document_schema_version import DocumentSchemaVersion
from app.models.processing_job import ProcessingJob
from app.models.user_api_setting import UserApiSetting
from app.services.storage_paths import (
    job_log_dir,
    knowledge_graph_run_artifacts_dir,
    knowledge_graph_run_images_dir,
    knowledge_graph_run_report_dir,
    document_pipeline_dir,
    pipeline_pdf_path,
)

PIPELINE_STAGE_STOP_AT = {
    "parse_pdf": "pdf",
    "build_graph": "kg",
    "full_pipeline": "kg",
}


def run_document_pipeline(job_id: int) -> None:
    with SessionLocal() as db:
        job = db.get(ProcessingJob, job_id)
        if job is None:
            return
        document = db.get(Document, job.document_id)
        if document is None:
            _fail_job(db, job, "Document not found.")
            return

        run_id = f"web_doc_{document.id}_{job.id}"
        log_dir = job_log_dir(document, run_id)
        log_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = log_dir / "stdout.log"
        stderr_path = log_dir / "stderr.log"

        job.status = "running"
        job.log_path = str(log_dir)
        job.started_at = utc_now_naive()
        document.status = f"{job.stage}_running"
        document.processing_started_at = job.started_at
        db.commit()

        try:
            env = _build_pipeline_env(db, document)
            command = _build_pipeline_command(db, document, job, run_id)
            with stdout_path.open("w", encoding="utf-8") as stdout_file:
                with stderr_path.open("w", encoding="utf-8") as stderr_file:
                    result = subprocess.run(
                        command,
                        cwd=settings.project_dir,
                        env=env,
                        stdout=stdout_file,
                        stderr=stderr_file,
                        check=False,
                    )

            completed_at = utc_now_naive()
            job.completed_at = completed_at
            document.processing_completed_at = completed_at
            _archive_pipeline_outputs(run_id)
            job_status, document_status, message = _pipeline_status_from_result(
                stage=job.stage,
                run_id=run_id,
                returncode=result.returncode,
            )
            job.status = job_status
            document.status = document_status
            job.error_message = message
            db.commit()
        except Exception as exc:
            traceback_path = log_dir / "traceback.log"
            traceback_path.write_text(traceback.format_exc(), encoding="utf-8")
            _fail_job(db, job, str(exc))


def _build_pipeline_command(
    db: Session,
    document: Document,
    job: ProcessingJob,
    run_id: str,
) -> list[str]:
    pdf_path = _short_pipeline_pdf_path(document)
    stop_at = PIPELINE_STAGE_STOP_AT.get(job.stage, settings.pipeline_stop_at)
    dashscope_setting = _get_api_setting(db, "dashscope", document.owner_user_id)
    deepseek_setting = _get_api_setting(db, "deepseek", document.owner_user_id)
    payload = _job_payload(job)
    source_context_ids = _clean_source_context_ids(payload.get("source_context_ids", []))
    command = [
        settings.pipeline_python,
        "-m",
        "mas.pipelines.full_pipeline.main",
        "--pdf",
        str(pdf_path),
        "--run-id",
        run_id,
        "--subject",
        _pipeline_value(document.subject, "chemistry"),
        "--grade",
        _pipeline_value(document.grade, "high_school"),
        "--publisher",
        _pipeline_value(document.publisher, "sujiao"),
        "--stop-at",
        stop_at,
        "--no-publish-schema-standards",
        "--no-pdf-text-fallback",
        "--qwen-timeout-seconds",
        "180",
        "--qwen-retry-attempts",
        "5",
        "--qwen-timeout-retry-attempts",
        "3",
        "--qwen-timeout-retry-budget-seconds",
        "600",
    ]
    if dashscope_setting is not None and dashscope_setting.model_name.strip():
        qwen_model = dashscope_setting.model_name.strip()
        command.extend(
            [
                "--node-model",
                qwen_model,
                "--edge-model",
                qwen_model,
                "--standard-model",
                qwen_model,
                "--sa-model",
                qwen_model,
            ]
        )
    if deepseek_setting is not None:
        if deepseek_setting.model_name.strip():
            command.extend(["--validation-model", deepseek_setting.model_name.strip()])
        if deepseek_setting.base_url.strip():
            command.extend(["--validation-base-url", deepseek_setting.base_url.strip()])
    for source_context_id in source_context_ids:
        command.extend(["--source-context-id", source_context_id])
    cached_schema_path = _schema_path_for_pipeline(db, document, job) if stop_at == "kg" else None
    if cached_schema_path is not None:
        command.extend(
            [
                "--schema-path",
                str(cached_schema_path),
                "--no-schema-agent",
                "--reuse-schema-path-when-schema-agent-disabled",
                "--allow-schema-mismatch",
            ]
        )
    if settings.pipeline_mock:
        command.append("--mock")
    return command


def _pipeline_value(value: str | None, fallback: str) -> str:
    return (value or "").strip() or fallback


def _job_payload(job: ProcessingJob) -> dict[str, object]:
    try:
        value = json.loads(job.payload_json or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _clean_source_context_ids(source_context_ids: object) -> list[str]:
    if not isinstance(source_context_ids, list):
        return []
    cleaned: list[str] = []
    for item in source_context_ids:
        value = str(item or "").strip()
        if not value or value in cleaned:
            continue
        cleaned.append(value)
    return cleaned


def _document_success_status(stage: str) -> str:
    if stage == "parse_pdf":
        return "parsed"
    if stage == "build_graph":
        return "graph_ready"
    return "success"


def _short_pipeline_pdf_path(document: Document) -> Path:
    source_path = Path(document.original_path)
    target_path = pipeline_pdf_path(document)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if source_path.resolve() != target_path.resolve():
        shutil.copy2(source_path, target_path)
    return target_path


def _archive_pipeline_outputs(run_id: str) -> None:
    report_source_dir = settings.project_dir / "code_implement" / "data" / "output" / "full_pipeline_reports"
    ipa_source_root = settings.project_dir / "code_implement" / "data" / "intermediate" / "ipa_outputs" / "full_pipeline"
    artifact_source_dir = settings.project_dir / "code_implement" / "data" / "output" / "kg_extraction_outputs"

    report_target_dir = knowledge_graph_run_report_dir(run_id)
    artifact_target_dir = knowledge_graph_run_artifacts_dir(run_id)
    image_target_dir = knowledge_graph_run_images_dir(run_id)
    report_target_dir.mkdir(parents=True, exist_ok=True)
    artifact_target_dir.mkdir(parents=True, exist_ok=True)
    image_target_dir.mkdir(parents=True, exist_ok=True)

    _copy_if_exists(
        report_source_dir / f"{run_id}_full_pipeline_report.md",
        report_target_dir / f"{run_id}_full_pipeline_report.md",
    )
    _copy_if_exists(
        report_source_dir / f"{run_id}_full_pipeline_manifest.json",
        report_target_dir / f"{run_id}_full_pipeline_manifest.json",
    )

    _copy_if_exists(
        artifact_source_dir / run_id / "standard_outputs" / "merged_nodes.json",
        artifact_target_dir / "merged_nodes.json",
    )
    _copy_if_exists(
        artifact_source_dir / run_id / "standard_outputs" / "merged_edges.json",
        artifact_target_dir / "merged_edges.json",
    )
    _copy_if_exists(
        artifact_source_dir / run_id / "standard_outputs" / "triples.json",
        artifact_target_dir / "triples.json",
    )
    _copy_if_exists(
        artifact_source_dir / f"kg_{run_id}" / "standard_outputs" / "merged_nodes.json",
        artifact_target_dir / "merged_nodes.json",
    )
    _copy_if_exists(
        artifact_source_dir / f"kg_{run_id}" / "standard_outputs" / "merged_edges.json",
        artifact_target_dir / "merged_edges.json",
    )
    _copy_if_exists(
        artifact_source_dir / f"kg_{run_id}" / "standard_outputs" / "triples.json",
        artifact_target_dir / "triples.json",
    )

    for ipa_run_dir in _source_ipa_run_dirs(ipa_source_root, run_id):
        for image_dir in [
            ipa_run_dir / "inputs" / "sections" / "images",
            ipa_run_dir / "enhanced_markdown" / "sections" / "images",
        ]:
            if not image_dir.exists():
                continue
            for image_file in image_dir.rglob("*"):
                if not image_file.is_file():
                    continue
                relative = image_file.relative_to(image_dir)
                target_file = image_target_dir / relative
                target_file.parent.mkdir(parents=True, exist_ok=True)
                if not target_file.exists():
                    shutil.copy2(image_file, target_file)


def _source_ipa_run_dirs(ipa_source_root: Path, run_id: str) -> list[Path]:
    if not ipa_source_root.exists():
        return []
    dirs = [path for path in ipa_source_root.iterdir() if path.is_dir() and run_id in path.name]
    return sorted(dirs, key=lambda path: path.stat().st_mtime, reverse=True)


def _copy_if_exists(source: Path, target: Path) -> None:
    if source.exists() and source.is_file():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _build_pipeline_env(db: Session, document: Document) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["MINERU_MODEL_SOURCE"] = settings.mineru_model_source
    if settings.mineru_device_mode != "auto":
        env["MINERU_DEVICE_MODE"] = settings.mineru_device_mode
    else:
        env.pop("MINERU_DEVICE_MODE", None)
    src_path = str(settings.project_dir / "code_implement" / "src")
    env["PYTHONPATH"] = (
        f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
        if env.get("PYTHONPATH")
        else src_path
    )

    dashscope_key = _get_api_key(db, "dashscope", document.owner_user_id)
    deepseek_key = _get_api_key(db, "deepseek", document.owner_user_id)
    if dashscope_key:
        env["DASHSCOPE_API_KEY"] = dashscope_key
    if deepseek_key:
        env["DEEPSEEK_API_KEY"] = deepseek_key
    return env


def _get_api_key(db: Session, provider: str, owner_user_id: int | None) -> str:
    setting = _get_api_setting(db, provider, owner_user_id)
    if setting is None or not setting.encrypted_api_key:
        return ""
    try:
        api_key, used_legacy_format = decrypt_secret_with_metadata(
            setting.encrypted_api_key,
            secret_key=settings.secret_encryption_key,
            fallback_secret_keys=settings.legacy_secret_encryption_keys,
        )
        if used_legacy_format and api_key:
            setting.encrypted_api_key = encrypt_secret(
                api_key,
                secret_key=settings.secret_encryption_key,
            )
            db.add(setting)
            db.commit()
        return api_key
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError(
            f"Cannot decrypt {provider} API key. Keep FAMAS_SECRET_KEY / "
            "FAMAS_SECRET_ENCRYPTION_KEY unchanged "
            "or save the API key again in the API page."
        ) from exc


def _get_api_setting(
    db: Session,
    provider: str,
    owner_user_id: int | None,
) -> ApiSetting | UserApiSetting | None:
    setting = None
    if owner_user_id is not None:
        setting = db.scalar(
            select(UserApiSetting).where(
                UserApiSetting.user_id == owner_user_id,
                UserApiSetting.provider == provider,
            )
        )
        if setting is not None and not setting.encrypted_api_key:
            setting = None

    if setting is None:
        setting = db.scalar(select(ApiSetting).where(ApiSetting.provider == provider))
    return setting


def repair_usable_pipeline_job(job: ProcessingJob, document: Document) -> bool:
    if job.stage not in PIPELINE_STAGE_STOP_AT or job.status != "failed":
        return False
    run_id = f"web_doc_{document.id}_{job.id}"
    job_status, document_status, message = _pipeline_status_from_result(
        stage=job.stage,
        run_id=run_id,
        returncode=1,
    )
    if job_status == "failed":
        return False
    job.status = job_status
    document.status = document_status
    job.error_message = message
    return True


def recover_interrupted_pipeline_jobs(db: Session) -> int:
    jobs = list(
        db.scalars(
            select(ProcessingJob)
            .where(
                ProcessingJob.stage.in_(PIPELINE_STAGE_STOP_AT),
                ProcessingJob.status == "running",
            )
            .order_by(ProcessingJob.created_at.asc())
        )
    )
    if not jobs:
        return 0

    completed_at = utc_now_naive()
    recovered_count = 0
    for job in jobs:
        document = db.get(Document, job.document_id)
        run_id = f"web_doc_{job.document_id}_{job.id}"
        _archive_pipeline_outputs(run_id)
        job_status, document_status, message = _pipeline_status_from_result(
            stage=job.stage,
            run_id=run_id,
            returncode=1,
        )
        if job_status == "failed":
            message = (
                "Processing was interrupted by a server restart before completion. "
                "Please run this job again."
            )

        job.status = job_status
        job.error_message = message
        job.completed_at = completed_at
        if document is not None:
            document.status = document_status
            document.processing_completed_at = completed_at
        recovered_count += 1

    db.commit()
    return recovered_count


def _pipeline_status_from_result(
    *,
    stage: str,
    run_id: str,
    returncode: int,
) -> tuple[str, str, str]:
    if returncode == 0:
        return "success", _document_success_status(stage), ""

    manifest = _read_pipeline_manifest(run_id)
    manifest_status = str(manifest.get("status", "")).lower() if manifest else ""
    if manifest_status in {"passed", "degraded"} and _stage_outputs_are_usable(stage, run_id, manifest):
        if manifest_status == "degraded":
            return (
                "degraded",
                _document_success_status(stage),
                "Pipeline completed with degraded status; usable artifacts were generated.",
            )
        return "success", _document_success_status(stage), ""

    return "failed", "failed", f"Pipeline exited with code {returncode}."


def _read_pipeline_manifest(run_id: str) -> dict:
    candidate_paths = [
        knowledge_graph_run_report_dir(run_id) / f"{run_id}_full_pipeline_manifest.json",
        settings.project_dir
        / "code_implement"
        / "data"
        / "output"
        / "full_pipeline_reports"
        / f"{run_id}_full_pipeline_manifest.json",
    ]
    for manifest_path in candidate_paths:
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def _cached_schema_path_for_document(db: Session, document: Document, current_job_id: int) -> Path | None:
    if not settings.pipeline_schema_cache_enabled:
        return None

    jobs = list(
        db.scalars(
            select(ProcessingJob)
            .where(
                ProcessingJob.document_id == document.id,
                ProcessingJob.id != current_job_id,
                ProcessingJob.stage.in_(["build_graph", "full_pipeline"]),
                ProcessingJob.status.in_(["success", "degraded"]),
            )
            .order_by(ProcessingJob.completed_at.desc().nullslast(), ProcessingJob.created_at.desc())
        )
    )
    for job in jobs:
        run_id = f"web_doc_{document.id}_{job.id}"
        schema_path = _schema_path_from_manifest(_read_pipeline_manifest(run_id))
        if schema_path is not None:
            return schema_path
    return None


def _schema_path_for_pipeline(db: Session, document: Document, job: ProcessingJob) -> Path | None:
    web_schema_path = _web_schema_path_for_document(db, document, job.schema_version_id)
    if web_schema_path is not None:
        return web_schema_path
    return _cached_schema_path_for_document(db, document, job.id)


def _web_schema_path_for_document(
    db: Session,
    document: Document,
    schema_version_id: int | None,
) -> Path | None:
    if schema_version_id is not None:
        version = db.get(DocumentSchemaVersion, schema_version_id)
        if version is None or version.document_id != document.id:
            return None
    else:
        version = db.scalar(
            select(DocumentSchemaVersion)
            .where(
                DocumentSchemaVersion.document_id == document.id,
                DocumentSchemaVersion.is_active.is_(True),
            )
            .order_by(DocumentSchemaVersion.version_number.desc())
        )
    if version is None:
        return None

    schema_dir = document_pipeline_dir(document) / "schemas"
    schema_dir.mkdir(parents=True, exist_ok=True)
    schema_path = schema_dir / f"web_schema_v{version.version_number}.json"
    schema_path.write_text(version.schema_json, encoding="utf-8")
    return schema_path


def _schema_path_from_manifest(manifest: dict) -> Path | None:
    schema_manifest = manifest.get("schema_agent")
    if not isinstance(schema_manifest, dict):
        return None
    schema_path = schema_manifest.get("schema_path")
    if not schema_path:
        output_dir = schema_manifest.get("output_dir")
        if output_dir:
            schema_path = str(Path(str(output_dir)) / "final_schema.json")
    if not schema_path:
        return None
    candidate = Path(str(schema_path))
    if candidate.exists() and candidate.is_file():
        return candidate
    return None


def _stage_outputs_are_usable(stage: str, run_id: str, manifest: dict) -> bool:
    if stage == "parse_pdf":
        pdf_to_md = manifest.get("pdf_to_md", {})
        prepared_markdown = Path(str(pdf_to_md.get("prepared_markdown", "")))
        return pdf_to_md.get("status") == "ok" or prepared_markdown.exists()
    if stage in {"build_graph", "full_pipeline"}:
        artifacts = manifest.get("kg_artifacts", {})
        if all(artifacts.get(name) is True for name in [
            "merged_nodes_exists",
            "merged_edges_exists",
            "triples_exists",
        ]):
            return True
        return all(_processed_artifact_path(run_id, filename).exists() for filename in [
            "merged_nodes.json",
            "merged_edges.json",
            "triples.json",
        ])
    return False


def _processed_artifact_path(run_id: str, artifact_name: str) -> Path:
    storage_path = knowledge_graph_run_artifacts_dir(run_id) / artifact_name
    if storage_path.exists():
        return storage_path

    direct_path = _processed_artifact_dir(run_id) / "standard_outputs" / artifact_name
    if direct_path.exists():
        return direct_path

    kg_prefixed_path = _processed_artifact_dir(f"kg_{run_id}") / "standard_outputs" / artifact_name
    if kg_prefixed_path.exists():
        return kg_prefixed_path

    return direct_path


def _processed_artifact_dir(run_id: str) -> Path:
    return (
        settings.project_dir
        / "code_implement"
        / "data"
        / "output"
        / "kg_extraction_outputs"
        / run_id
    )


def _fail_job(db: Session, job: ProcessingJob, message: str) -> None:
    document = db.get(Document, job.document_id)
    completed_at = utc_now_naive()
    job.status = "failed"
    job.error_message = message
    job.completed_at = completed_at
    if document is not None:
        document.status = "failed"
        document.processing_completed_at = completed_at
    db.commit()
