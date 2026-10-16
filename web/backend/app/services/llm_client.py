from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import decrypt_secret_with_metadata, encrypt_secret
from app.core.time import utc_now_naive
from app.models.api_setting import ApiSetting
from app.models.user import User
from app.models.user_api_setting import UserApiSetting

SUPPORTED_CHAT_PROVIDERS = {"dashscope", "deepseek"}


class LlmClientError(Exception):
    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def chat_completion_from_settings(
    *,
    db: Session,
    user: User,
    provider: str,
    messages: list[dict[str, str]],
    timeout_seconds: int = 60,
    temperature: float | None = None,
    max_tokens: int | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    provider, setting, key_source, api_key = _resolve_chat_config(db, user, provider)
    effective_model_name = _model_name_or_default(model_name, setting.model_name)
    payload = {
        "model": effective_model_name,
        "messages": messages,
        "temperature": _float_or_default(temperature, _float_or_default(setting.temperature, 0.2)),
        "max_tokens": _int_or_default(max_tokens, _int_or_default(setting.max_tokens, 1200)),
    }
    request = Request(
        _chat_completions_url(setting.base_url),
        data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept-Encoding": "identity",
            },
        method="POST",
    )

    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response_text = response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        body = error.read(4096).decode("utf-8", errors="replace")
        raise LlmClientError(
            _extract_error_message(body) or error.reason or "Model API request failed.",
            status_code=502,
        ) from error
    except TimeoutError as error:
        raise LlmClientError("Model API request timed out.", status_code=504) from error
    except URLError as error:
        raise LlmClientError(f"Model API connection failed: {error.reason}") from error

    content = _extract_message_content(response_text)
    if not content:
        raise LlmClientError("Model API returned an empty answer.")

    return {
        "content": content,
        "provider": provider,
        "model_name": effective_model_name,
        "key_source": key_source,
    }


def stream_chat_completion_from_settings(
    *,
    db: Session,
    user: User,
    provider: str,
    messages: list[dict[str, str]],
    timeout_seconds: int = 120,
    temperature: float | None = None,
    max_tokens: int | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    provider, setting, key_source, api_key = _resolve_chat_config(db, user, provider)
    effective_model_name = _model_name_or_default(model_name, setting.model_name)
    payload = {
        "model": effective_model_name,
        "messages": messages,
        "temperature": _float_or_default(temperature, _float_or_default(setting.temperature, 0.2)),
        "max_tokens": _int_or_default(max_tokens, _int_or_default(setting.max_tokens, 1200)),
        "stream": True,
    }

    def chunks() -> Iterable[str]:
        fallback_lines: list[str] = []
        request = Request(
            _chat_completions_url(setting.base_url),
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
                "Accept-Encoding": "identity",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        fallback_lines.append(line)
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    delta = _extract_stream_delta(data)
                    if delta:
                        yield delta
                fallback_text = "\n".join(fallback_lines).strip()
                if fallback_text:
                    fallback_content = _extract_message_content(fallback_text)
                    if fallback_content:
                        yield fallback_content
        except HTTPError as error:
            body = error.read(4096).decode("utf-8", errors="replace")
            raise LlmClientError(
                _extract_error_message(body) or error.reason or "Model API request failed.",
                status_code=502,
            ) from error
        except TimeoutError as error:
            raise LlmClientError("Model API request timed out.", status_code=504) from error
        except URLError as error:
            raise LlmClientError(f"Model API connection failed: {error.reason}") from error

    return {
        "provider": provider,
        "model_name": effective_model_name,
        "key_source": key_source,
        "chunks": chunks(),
    }


def _resolve_chat_config(
    db: Session,
    user: User,
    provider: str,
) -> tuple[str, ApiSetting | UserApiSetting, str, str]:
    provider = provider.lower().strip()
    if provider not in SUPPORTED_CHAT_PROVIDERS:
        raise LlmClientError("Unsupported model provider.", status_code=400)

    setting, key_source = _effective_setting(db, user, provider)
    if setting is None:
        raise LlmClientError(
            f"No saved API settings found for {provider}. Save an API key first.",
            status_code=400,
        )

    api_key = _decrypt_api_key(setting, db=db)
    if not api_key:
        raise LlmClientError(
            f"No valid API key is saved for {provider}.",
            status_code=400,
        )
    if not setting.model_name.strip():
        raise LlmClientError("Model name is required.", status_code=400)
    if not setting.base_url.strip():
        raise LlmClientError("Base URL is required.", status_code=400)
    return provider, setting, key_source, api_key


def _effective_setting(
    db: Session,
    user: User,
    provider: str,
) -> tuple[ApiSetting | UserApiSetting | None, str]:
    if user.role != "admin":
        user_setting = db.scalar(
            select(UserApiSetting).where(
                UserApiSetting.user_id == user.id,
                UserApiSetting.provider == provider,
            )
        )
        if user_setting is not None and _decrypt_api_key(user_setting, db=db):
            return user_setting, "user"

    system_setting = db.scalar(select(ApiSetting).where(ApiSetting.provider == provider))
    if system_setting is not None:
        return system_setting, "system"
    return None, ""


def _decrypt_api_key(setting: ApiSetting | UserApiSetting, *, db: Session | None = None) -> str:
    api_key = ""
    if setting.encrypted_api_key:
        try:
            api_key, used_legacy_format = decrypt_secret_with_metadata(
                setting.encrypted_api_key,
                secret_key=settings.secret_encryption_key,
                fallback_secret_keys=settings.legacy_secret_encryption_keys,
            )
            if used_legacy_format and db is not None and api_key:
                setting.encrypted_api_key = encrypt_secret(
                    api_key,
                    secret_key=settings.secret_encryption_key,
                )
                setting.updated_at = utc_now_naive()
                db.add(setting)
                db.commit()
                db.refresh(setting)
        except (ValueError, UnicodeDecodeError):
            api_key = ""
    return api_key


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _model_name_or_default(model_name: str | None, default: str) -> str:
    normalized = (model_name or "").strip()
    return normalized or default


def _extract_message_content(response_text: str) -> str:
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        return response_text.strip()

    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    return str(content).strip()


def _extract_stream_delta(response_text: str) -> str:
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        return ""

    choice = data.get("choices", [{}])[0]
    delta = choice.get("delta")
    if isinstance(delta, dict):
        content = delta.get("content", "")
        if content is None:
            return ""
        return str(content)
    message = choice.get("message")
    if isinstance(message, dict):
        return str(message.get("content") or "")
    text = choice.get("text")
    return str(text or "")


def _extract_error_message(response_text: str) -> str:
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        return response_text[:300]

    error = data.get("error")
    if isinstance(error, dict):
        return str(error.get("message") or error.get("code") or "")
    if isinstance(error, str):
        return error
    return ""


def _float_or_default(value: str, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int_or_default(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
