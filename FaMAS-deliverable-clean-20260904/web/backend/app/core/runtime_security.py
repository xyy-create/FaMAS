from __future__ import annotations

from app.core.config import Settings

DEVELOPMENT_SECRET_KEYS = {"", "dev-secret", "dev-only-change-me"}
STRICT_RUNTIME_MODES = {"public", "production"}
MIN_STRONG_SECRET_LENGTH = 32


def secret_key_is_development_value(secret_key: str) -> bool:
    return secret_key.strip() in DEVELOPMENT_SECRET_KEYS


def strict_runtime_mode_enabled(runtime_mode: str) -> bool:
    return runtime_mode.strip().lower() in STRICT_RUNTIME_MODES


def validate_runtime_security_config(settings: Settings) -> None:
    runtime_mode = settings.runtime_mode.strip().lower()
    if not strict_runtime_mode_enabled(runtime_mode):
        return

    secret_key = settings.secret_key.strip()
    if secret_key_is_development_value(secret_key) or len(secret_key) < MIN_STRONG_SECRET_LENGTH:
        raise RuntimeError(
            "FAMAS_SECRET_KEY must be a non-default secret with at least "
            f"{MIN_STRONG_SECRET_LENGTH} characters when FAMAS_RUNTIME_MODE "
            f"is {runtime_mode}."
        )

    secret_encryption_key = getattr(settings, "secret_encryption_key", "") or secret_key
    secret_encryption_key = secret_encryption_key.strip()
    if secret_encryption_key != secret_key and (
        secret_key_is_development_value(secret_encryption_key)
        or len(secret_encryption_key) < MIN_STRONG_SECRET_LENGTH
    ):
        raise RuntimeError(
            "FAMAS_SECRET_ENCRYPTION_KEY must be a non-default secret with at least "
            f"{MIN_STRONG_SECRET_LENGTH} characters when FAMAS_RUNTIME_MODE "
            f"is {runtime_mode}."
        )
