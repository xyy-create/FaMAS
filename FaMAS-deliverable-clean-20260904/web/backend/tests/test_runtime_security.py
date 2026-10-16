from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.core.runtime_security import (
    secret_key_is_development_value,
    validate_runtime_security_config,
)


@dataclass
class RuntimeSettings:
    runtime_mode: str
    secret_key: str
    secret_encryption_key: str = ""


def test_development_runtime_allows_short_local_secret() -> None:
    validate_runtime_security_config(
        RuntimeSettings(runtime_mode="development", secret_key="dev-secret")
    )


@pytest.mark.parametrize("secret_key", ["", "dev-secret", "dev-only-change-me", "short"])
def test_public_runtime_rejects_default_or_short_secret(secret_key: str) -> None:
    with pytest.raises(RuntimeError, match="FAMAS_SECRET_KEY"):
        validate_runtime_security_config(
            RuntimeSettings(runtime_mode="public", secret_key=secret_key)
        )


def test_production_runtime_accepts_strong_secret() -> None:
    validate_runtime_security_config(
        RuntimeSettings(
            runtime_mode="production",
            secret_key="famas-test-secret-with-more-than-32-characters",
        )
    )


def test_public_runtime_rejects_weak_independent_encryption_secret() -> None:
    with pytest.raises(RuntimeError, match="FAMAS_SECRET_ENCRYPTION_KEY"):
        validate_runtime_security_config(
            RuntimeSettings(
                runtime_mode="public",
                secret_key="famas-test-secret-with-more-than-32-characters",
                secret_encryption_key="short",
            )
        )


def test_secret_key_development_value_detection() -> None:
    assert secret_key_is_development_value("dev-secret") is True
    assert secret_key_is_development_value(" dev-only-change-me ") is True
    assert secret_key_is_development_value("famas-test-secret-with-more-than-32-characters") is False
