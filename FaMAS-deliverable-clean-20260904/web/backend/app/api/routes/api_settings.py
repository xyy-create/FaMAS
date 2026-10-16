import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import settings
from app.core.security import decrypt_secret_with_metadata, encrypt_secret, mask_secret
from app.core.time import utc_now_naive
from app.db.session import get_db
from app.models.api_setting import ApiSetting
from app.models.user import User
from app.models.user_api_setting import UserApiSetting
from app.schemas.api_setting import (
    ApiSettingResponse,
    ApiSettingTestResponse,
    ApiSettingUpsert,
)

SUPPORTED_PROVIDERS = {"dashscope", "deepseek"}

router = APIRouter(prefix="/api/settings/models", tags=["api-settings"])


@router.get("", response_model=list[ApiSettingResponse])
def list_api_settings(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[ApiSettingResponse]:
    if user.role == "admin":
        statement = select(ApiSetting).order_by(ApiSetting.provider.asc())
        return [_to_response(setting, key_source="system", db=db) for setting in db.scalars(statement)]

    responses: list[ApiSettingResponse] = []
    for provider in sorted(SUPPORTED_PROVIDERS):
        setting, key_source = _effective_setting(db, user, provider)
        if setting is not None:
            responses.append(
                _to_response(
                    setting,
                    key_source=key_source,
                    hide_secret=key_source == "system",
                    db=db,
                )
            )
    return responses


@router.put("/{provider}", response_model=ApiSettingResponse)
def upsert_api_setting(
    provider: str,
    payload: ApiSettingUpsert,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiSettingResponse:
    provider = provider.lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported provider.",
        )
    if payload.provider.lower() != provider:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Provider in path and body must match.",
        )

    model = ApiSetting if user.role == "admin" else UserApiSetting
    statement = select(model).where(model.provider == provider)
    if user.role != "admin":
        statement = statement.where(UserApiSetting.user_id == user.id)
    setting = db.scalar(statement)
    if setting is None:
        if user.role == "admin":
            setting = ApiSetting(provider=provider, model_name=payload.model_name)
        else:
            setting = UserApiSetting(
                user_id=user.id,
                provider=provider,
                model_name=payload.model_name,
            )
        db.add(setting)

    setting.model_name = payload.model_name
    setting.base_url = payload.base_url
    setting.temperature = payload.temperature
    setting.max_tokens = payload.max_tokens
    setting.updated_at = utc_now_naive()
    if payload.api_key:
        setting.encrypted_api_key = encrypt_secret(
            payload.api_key,
            secret_key=settings.secret_encryption_key,
        )

    db.commit()
    db.refresh(setting)
    return _to_response(setting, key_source="system" if user.role == "admin" else "user", db=db)


@router.post("/{provider}/test", response_model=ApiSettingTestResponse)
def test_api_setting(
    provider: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> ApiSettingTestResponse:
    provider = provider.lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported provider.",
        )

    setting, key_source = _effective_setting(db, user, provider)
    if setting is None:
        return ApiSettingTestResponse(
            provider=provider,
            model_name="",
            ok=False,
            message="No saved settings found for this provider.",
        )

    api_key = _decrypt_api_key(setting, db=db)
    if not api_key:
        return ApiSettingTestResponse(
            provider=provider,
            model_name=setting.model_name,
            ok=False,
            message="No valid API key is saved for this provider.",
        )
    if not setting.model_name.strip():
        return ApiSettingTestResponse(
            provider=provider,
            model_name=setting.model_name,
            ok=False,
            message="Model name is required.",
        )
    if not setting.base_url.strip():
        return ApiSettingTestResponse(
            provider=provider,
            model_name=setting.model_name,
            ok=False,
            message="Base URL is required.",
        )

    result = _test_openai_compatible_chat(setting, api_key)
    if result.ok and key_source == "system" and user.role != "admin":
        result.message = "Connection test passed using the system default API key."
    return result


@router.get("/{provider}/available-models")
def list_available_models(
    provider: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    provider = provider.lower()
    if provider not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported provider.",
        )

    setting, key_source = _effective_setting(db, user, provider)
    if setting is None:
        return _model_list_fallback(provider, "", "", ok=False, message="尚未保存该平台的 API 设置。")

    api_key = _decrypt_api_key(setting, db=db)
    if not api_key:
        return _model_list_fallback(
            provider,
            setting.model_name,
            key_source,
            ok=False,
            message="尚未保存可用的 API key。",
        )

    models_url = _models_url(setting.base_url)
    request = Request(
        models_url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=12) as response:
            response_text = response.read(256 * 1024).decode("utf-8", errors="replace")
    except HTTPError as error:
        body = error.read(2048).decode("utf-8", errors="replace")
        return _model_list_fallback(
            provider,
            setting.model_name,
            key_source,
            ok=False,
            message=_extract_error_message(body) or error.reason or "模型列表获取失败，已使用当前保存模型。",
            status_code=error.code,
        )
    except (URLError, TimeoutError) as error:
        return _model_list_fallback(
            provider,
            setting.model_name,
            key_source,
            ok=False,
            message=f"模型列表获取失败，已使用当前保存模型：{error}",
        )

    model_ids = _extract_model_ids(response_text)
    if not model_ids and setting.model_name.strip():
        model_ids = [setting.model_name.strip()]
    return {
        "provider": provider,
        "key_source": key_source,
        "ok": bool(model_ids),
        "message": "模型列表已获取。" if model_ids else "模型列表为空。",
        "model_name": setting.model_name,
        "models": [{"id": model_id, "name": model_id} for model_id in model_ids],
    }


def _to_response(
    setting: ApiSetting | UserApiSetting,
    *,
    key_source: str,
    hide_secret: bool = False,
    db: Session | None = None,
) -> ApiSettingResponse:
    api_key = _decrypt_api_key(setting, db=db)
    return ApiSettingResponse(
        id=setting.id,
        provider=setting.provider,
        model_name=setting.model_name,
        base_url=setting.base_url,
        masked_api_key="System default" if hide_secret and api_key else mask_secret(api_key),
        has_api_key=bool(api_key),
        key_source=key_source,
        temperature=setting.temperature,
        max_tokens=setting.max_tokens,
        created_at=setting.created_at,
        updated_at=setting.updated_at,
    )


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


def _test_openai_compatible_chat(
    setting: ApiSetting | UserApiSetting,
    api_key: str,
) -> ApiSettingTestResponse:
    url = _chat_completions_url(setting.base_url)
    payload = {
        "model": setting.model_name,
        "messages": [
            {"role": "system", "content": "You are a connection test endpoint."},
            {"role": "user", "content": "Reply with OK only."},
        ],
        "temperature": 0,
        "max_tokens": 8,
    }
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=20) as response:
            response_text = response.read(4096).decode("utf-8", errors="replace")
            return ApiSettingTestResponse(
                provider=setting.provider,
                model_name=setting.model_name,
                ok=True,
                status_code=response.status,
                message="Connection test passed.",
                response_preview=_extract_response_preview(response_text),
            )
    except HTTPError as error:
        body = error.read(4096).decode("utf-8", errors="replace")
        return ApiSettingTestResponse(
            provider=setting.provider,
            model_name=setting.model_name,
            ok=False,
            status_code=error.code,
            message=_extract_error_message(body) or error.reason,
            response_preview=body[:500],
        )
    except URLError as error:
        return ApiSettingTestResponse(
            provider=setting.provider,
            model_name=setting.model_name,
            ok=False,
            message=f"Connection failed: {error.reason}",
        )
    except TimeoutError:
        return ApiSettingTestResponse(
            provider=setting.provider,
            model_name=setting.model_name,
            ok=False,
            message="Connection timed out.",
        )


def _chat_completions_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        return normalized
    return f"{normalized}/chat/completions"


def _models_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/chat/completions"):
        normalized = normalized[: -len("/chat/completions")]
    return f"{normalized}/models"


def _model_list_fallback(
    provider: str,
    model_name: str,
    key_source: str,
    *,
    ok: bool,
    message: str,
    status_code: int | None = None,
) -> dict[str, Any]:
    normalized_model_name = model_name.strip()
    result: dict[str, Any] = {
        "provider": provider,
        "key_source": key_source,
        "ok": ok,
        "message": message,
        "model_name": model_name,
        "models": [{"id": normalized_model_name, "name": normalized_model_name}] if normalized_model_name else [],
    }
    if status_code is not None:
        result["status_code"] = status_code
    return result


def _extract_model_ids(response_text: str) -> list[str]:
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        return []
    raw_models = data.get("data", data if isinstance(data, list) else [])
    if not isinstance(raw_models, list):
        return []
    model_ids: list[str] = []
    seen: set[str] = set()
    for item in raw_models:
        if isinstance(item, str):
            model_id = item
        elif isinstance(item, dict):
            model_id = str(item.get("id") or item.get("name") or "").strip()
        else:
            continue
        if model_id and model_id not in seen:
            model_ids.append(model_id)
            seen.add(model_id)
    return model_ids


def _extract_response_preview(response_text: str) -> str:
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        return response_text[:500]

    content = (
        data.get("choices", [{}])[0]
        .get("message", {})
        .get("content", "")
    )
    return content or response_text[:500]


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
