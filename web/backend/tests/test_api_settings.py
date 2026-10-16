from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from conftest import auth_headers, create_user
from app.core.config import settings
from app.core.security import (
    SECRET_ENCRYPTION_PREFIX,
    _encrypt_legacy_secret,
    decrypt_secret,
    encrypt_secret,
)
from app.models.api_setting import ApiSetting


def test_api_keys_are_masked_and_user_settings_do_not_leak_between_users(client, db_session: Session) -> None:
    admin = create_user(db_session, "admin", role="admin")
    alice = create_user(db_session, "alice")
    bob = create_user(db_session, "bob")

    admin_payload = {
        "provider": "dashscope",
        "model_name": "qwen-plus",
        "base_url": "https://dashscope.example.test",
        "api_key": "sk-system-secret-1234",
        "temperature": "0.2",
        "max_tokens": "4096",
    }
    admin_save = client.put(
        "/api/settings/models/dashscope",
        json=admin_payload,
        headers=auth_headers(admin),
    )
    assert admin_save.status_code == 200
    assert "sk-system-secret-1234" not in admin_save.text
    admin_setting = db_session.scalar(select(ApiSetting).where(ApiSetting.provider == "dashscope"))
    assert admin_setting is not None
    assert admin_setting.encrypted_api_key.startswith(SECRET_ENCRYPTION_PREFIX)
    assert "sk-system-secret-1234" not in admin_setting.encrypted_api_key

    alice_system_settings = client.get(
        "/api/settings/models",
        headers=auth_headers(alice),
    )
    assert alice_system_settings.status_code == 200
    assert alice_system_settings.json()[0]["masked_api_key"] == "System default"
    assert "sk-system-secret-1234" not in alice_system_settings.text

    alice_payload = {
        "provider": "dashscope",
        "model_name": "qwen-plus",
        "base_url": "https://dashscope.example.test",
        "api_key": "sk-alice-secret-5678",
        "temperature": "0.2",
        "max_tokens": "4096",
    }
    alice_save = client.put(
        "/api/settings/models/dashscope",
        json=alice_payload,
        headers=auth_headers(alice),
    )
    assert alice_save.status_code == 200
    assert alice_save.json()["key_source"] == "user"
    assert "sk-alice-secret-5678" not in alice_save.text

    bob_settings = client.get(
        "/api/settings/models",
        headers=auth_headers(bob),
    )
    assert bob_settings.status_code == 200
    assert bob_settings.json()[0]["masked_api_key"] == "System default"
    assert "sk-alice-secret-5678" not in bob_settings.text


def test_legacy_api_key_is_read_and_rotated_to_fernet(client, db_session: Session) -> None:
    admin = create_user(db_session, "admin", role="admin")
    legacy_setting = ApiSetting(
        provider="dashscope",
        model_name="qwen-plus",
        base_url="https://dashscope.example.test",
        encrypted_api_key=_encrypt_legacy_secret(
            "sk-legacy-secret-1234",
            secret_key="test-secret-key",
        ),
    )
    db_session.add(legacy_setting)
    db_session.commit()

    response = client.get(
        "/api/settings/models",
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    assert response.json()[0]["masked_api_key"] == "sk-l********1234"
    db_session.refresh(legacy_setting)
    assert legacy_setting.encrypted_api_key.startswith(SECRET_ENCRYPTION_PREFIX)
    assert "sk-legacy-secret-1234" not in legacy_setting.encrypted_api_key


def test_api_key_can_rotate_to_a_separate_encryption_secret(
    client,
    db_session: Session,
    monkeypatch,
) -> None:
    admin = create_user(db_session, "admin", role="admin")
    monkeypatch.setattr(settings, "secret_encryption_key", "test-encryption-key-1234567890")
    monkeypatch.setattr(settings, "legacy_secret_encryption_keys", ("test-secret-key",))
    rotated_setting = ApiSetting(
        provider="deepseek",
        model_name="deepseek-chat",
        base_url="https://api.deepseek.example.test",
        encrypted_api_key=encrypt_secret(
            "sk-rotate-secret-9876",
            secret_key="test-secret-key",
        ),
    )
    db_session.add(rotated_setting)
    db_session.commit()

    response = client.get(
        "/api/settings/models",
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    assert response.json()[0]["masked_api_key"] == "sk-r********9876"
    db_session.refresh(rotated_setting)
    assert decrypt_secret(
        rotated_setting.encrypted_api_key,
        secret_key="test-encryption-key-1234567890",
    ) == "sk-rotate-secret-9876"


def test_available_models_are_loaded_from_openai_compatible_endpoint(
    client,
    db_session: Session,
    monkeypatch,
) -> None:
    admin = create_user(db_session, "admin", role="admin")
    setting = ApiSetting(
        provider="dashscope",
        model_name="qwen-plus",
        base_url="https://dashscope.example.test/compatible-mode/v1",
        encrypted_api_key=encrypt_secret(
            "sk-model-list-secret",
            secret_key=settings.secret_encryption_key,
        ),
    )
    db_session.add(setting)
    db_session.commit()
    requested_urls: list[str] = []

    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, *_args):
            return b'{"data":[{"id":"qwen-plus"},{"id":"qwen-turbo"}]}'

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        assert timeout == 12
        assert request.headers["Authorization"] == "Bearer sk-model-list-secret"
        return FakeResponse()

    monkeypatch.setattr("app.api.routes.api_settings.urlopen", fake_urlopen)

    response = client.get(
        "/api/settings/models/dashscope/available-models",
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    assert requested_urls == ["https://dashscope.example.test/compatible-mode/v1/models"]
    assert response.json()["ok"] is True
    assert [model["id"] for model in response.json()["models"]] == ["qwen-plus", "qwen-turbo"]


def test_available_models_falls_back_to_saved_model_when_remote_lookup_fails(
    client,
    db_session: Session,
    monkeypatch,
) -> None:
    admin = create_user(db_session, "admin", role="admin")
    setting = ApiSetting(
        provider="deepseek",
        model_name="deepseek-chat",
        base_url="https://api.deepseek.example.test",
        encrypted_api_key=encrypt_secret(
            "sk-model-list-secret",
            secret_key=settings.secret_encryption_key,
        ),
    )
    db_session.add(setting)
    db_session.commit()

    def fake_urlopen(_request, timeout):
        assert timeout == 12
        raise TimeoutError()

    monkeypatch.setattr("app.api.routes.api_settings.urlopen", fake_urlopen)

    response = client.get(
        "/api/settings/models/deepseek/available-models",
        headers=auth_headers(admin),
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["models"] == [{"id": "deepseek-chat", "name": "deepseek-chat"}]
