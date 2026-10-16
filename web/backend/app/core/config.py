import os
import sys
from pathlib import Path


def _default_pipeline_python(project_dir: Path) -> str:
    configured_python = os.getenv("FAMAS_PIPELINE_PYTHON")
    if configured_python:
        return configured_python

    pipeline_python = project_dir / "code_implement" / ".venv" / "Scripts" / "python.exe"
    if pipeline_python.exists():
        return str(pipeline_python)

    return sys.executable


def _positive_int_env(name: str, default: int) -> int:
    try:
        value = int(_non_empty_env(name, str(default)))
    except ValueError:
        return default
    return max(1, value)


def _positive_float_env(name: str, default: float) -> float:
    try:
        value = float(_non_empty_env(name, str(default)))
    except ValueError:
        return default
    return max(0.1, value)


def _non_empty_env(name: str, default: str) -> str:
    value = os.getenv(name)
    if value:
        return value
    return default


def _build_legacy_secret_encryption_keys(
    raw_value: str,
    *,
    secret_key: str,
    secret_encryption_key: str,
) -> tuple[str, ...]:
    keys = []
    for key in [*(item.strip() for item in raw_value.split(",")), secret_key]:
        if key and key != secret_encryption_key and key not in keys:
            keys.append(key)
    return tuple(keys)


class Settings:
    backend_dir = Path(__file__).resolve().parents[2]
    web_dir = backend_dir.parent
    project_dir = web_dir.parent
    pipeline_python = _default_pipeline_python(project_dir)
    pipeline_stop_at = _non_empty_env("FAMAS_PIPELINE_STOP_AT", "kg")
    pipeline_mock = os.getenv("FAMAS_PIPELINE_MOCK", "0") == "1"
    pipeline_schema_cache_enabled = os.getenv("FAMAS_PIPELINE_SCHEMA_CACHE_ENABLED", "1") == "1"
    pipeline_worker_enabled = os.getenv("FAMAS_PIPELINE_WORKER_ENABLED", "1") == "1"
    pipeline_worker_interval_seconds = _positive_float_env("FAMAS_PIPELINE_WORKER_INTERVAL_SECONDS", 2)
    pipeline_worker_concurrency = _positive_int_env("FAMAS_PIPELINE_WORKER_CONCURRENCY", 1)
    runtime_mode = _non_empty_env("FAMAS_RUNTIME_MODE", "development").lower()
    enable_diagnostics = os.getenv(
        "FAMAS_ENABLE_DIAGNOSTICS",
        "1" if runtime_mode == "development" else "0",
    ) == "1"
    example_kg_fallback = os.getenv("FAMAS_EXAMPLE_KG_FALLBACK", "1") == "1"
    seed_default_knowledge_base = os.getenv("FAMAS_SEED_DEFAULT_KB", "1") == "1"
    registration_mode = _non_empty_env("FAMAS_REGISTRATION_MODE", "immediate").lower()
    public_url = os.getenv("FAMAS_PUBLIC_URL", "").strip()
    mineru_model_source = _non_empty_env("MINERU_MODEL_SOURCE", "local")
    mineru_device_mode = _non_empty_env("MINERU_DEVICE_MODE", "auto").lower()
    storage_dir = web_dir / "storage"
    user_storage_dir = storage_dir / "users"
    upload_dir = storage_dir / "uploads"
    job_log_dir = storage_dir / "jobs"
    chunk_upload_dir = storage_dir / "chunk_uploads"
    upload_chunk_size_bytes = _positive_int_env("FAMAS_UPLOAD_CHUNK_SIZE_BYTES", 2 * 1024 * 1024)
    max_upload_bytes = _positive_int_env("FAMAS_MAX_UPLOAD_BYTES", 250 * 1024 * 1024)
    database_url = _non_empty_env(
        "FAMAS_DATABASE_URL",
        f"sqlite:///{storage_dir / 'famas_web.db'}",
    )
    auto_migrate_database = os.getenv("FAMAS_AUTO_MIGRATE_DATABASE", "1") == "1"
    auto_create_tables = os.getenv("FAMAS_AUTO_CREATE_TABLES", "1") == "1"
    secret_key = os.getenv("FAMAS_SECRET_KEY", "dev-only-change-me")
    secret_encryption_key = os.getenv("FAMAS_SECRET_ENCRYPTION_KEY", secret_key)
    legacy_secret_encryption_keys = _build_legacy_secret_encryption_keys(
        os.getenv("FAMAS_LEGACY_SECRET_ENCRYPTION_KEYS", ""),
        secret_key=secret_key,
        secret_encryption_key=secret_encryption_key,
    )
    auth_cookie_name = os.getenv("FAMAS_AUTH_COOKIE_NAME", "famas_access_token")
    access_token_expire_minutes = _positive_int_env("FAMAS_ACCESS_TOKEN_EXPIRE_MINUTES", 120)
    login_rate_limit_max_attempts = _positive_int_env("FAMAS_LOGIN_RATE_LIMIT_MAX_ATTEMPTS", 5)
    login_rate_limit_window_seconds = _positive_int_env("FAMAS_LOGIN_RATE_LIMIT_WINDOW_SECONDS", 600)
    cors_origins = [
        origin.strip()
        for origin in os.getenv(
            "FAMAS_CORS_ORIGINS",
            "http://127.0.0.1:5173,http://localhost:5173",
        ).split(",")
        if origin.strip()
    ]


settings = Settings()
