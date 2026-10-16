"""OpenAI-compatible Qwen VL provider using only the Python standard library."""

from __future__ import annotations

from dataclasses import dataclass
import base64
import json
import mimetypes
import os
from pathlib import Path
import socket
import time
from typing import Any
import urllib.error
import urllib.request

from mas.pipelines.common.usage_tracker import (
    LLMResponse,
    estimate_usage,
    prompt_text_for_messages,
    record_usage,
    usage_from_payload,
)


DEFAULT_PROVIDER = "qwen_openai_compatible"
DEFAULT_MODEL = "qwen3-vl-flash"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_API_KEY_ENV = "DASHSCOPE_API_KEY"
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_MAX_TOKENS = 2048
DEFAULT_RETRY_ATTEMPTS = 3
DEFAULT_RETRY_BACKOFF_SECONDS = 2.0
TRANSIENT_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504}


class QwenVLProviderError(RuntimeError):
    """Raised when the Qwen VL provider cannot complete a request."""


@dataclass
class QwenVLConfig:
    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    api_key_env: str = DEFAULT_API_KEY_ENV
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_tokens: int = DEFAULT_MAX_TOKENS
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS


@dataclass
class QwenVLImage:
    image_id: str
    path: Path


def _config_from_dict(config: dict[str, Any] | None) -> QwenVLConfig:
    data = config or {}
    retry_attempts = data.get("retry_attempts")
    retry_backoff_seconds = data.get("retry_backoff_seconds")
    return QwenVLConfig(
        provider=str(data.get("provider") or DEFAULT_PROVIDER),
        model=str(data.get("name") or data.get("model") or DEFAULT_MODEL),
        base_url=str(data.get("base_url") or DEFAULT_BASE_URL).rstrip("/"),
        api_key_env=str(data.get("api_key_env") or DEFAULT_API_KEY_ENV),
        timeout_seconds=int(data.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS),
        max_tokens=int(data.get("max_tokens") or DEFAULT_MAX_TOKENS),
        retry_attempts=max(1, int(retry_attempts if retry_attempts is not None else DEFAULT_RETRY_ATTEMPTS)),
        retry_backoff_seconds=max(
            0.0,
            float(retry_backoff_seconds if retry_backoff_seconds is not None else DEFAULT_RETRY_BACKOFF_SECONDS),
        ),
    )


def _data_url_for_image(image: QwenVLImage) -> str:
    path = Path(image.path)
    if not path.exists():
        raise QwenVLProviderError(f"image file does not exist for {image.image_id}: {path}")
    if not path.is_file():
        raise QwenVLProviderError(f"image path is not a file for {image.image_id}: {path}")
    mime_type, _encoding = mimetypes.guess_type(str(path))
    if not mime_type or not mime_type.startswith("image/"):
        suffix = path.suffix.lower()
        if suffix in {".jpg", ".jpeg"}:
            mime_type = "image/jpeg"
        elif suffix == ".webp":
            mime_type = "image/webp"
        else:
            mime_type = "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _extract_content(response_payload: dict[str, Any]) -> str:
    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise QwenVLProviderError("Qwen VL response missing choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise QwenVLProviderError("Qwen VL response choice is not an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise QwenVLProviderError("Qwen VL response missing message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise QwenVLProviderError("Qwen VL response content is empty")
    return content


def _sleep_before_retry(attempt_index: int, qwen_config: QwenVLConfig) -> None:
    if qwen_config.retry_backoff_seconds <= 0:
        return
    time.sleep(qwen_config.retry_backoff_seconds * attempt_index)


def call_qwen_vl(
    *,
    system_prompt: str,
    user_prompt: str,
    images: list[QwenVLImage],
    config: dict[str, Any] | None,
    image_anchors: dict[str, str] | None = None,
) -> str:
    qwen_config = _config_from_dict(config)
    if qwen_config.provider != DEFAULT_PROVIDER:
        raise QwenVLProviderError(f"unsupported provider: {qwen_config.provider}")
    api_key = os.environ.get(qwen_config.api_key_env)
    if not api_key:
        raise QwenVLProviderError(f"environment variable {qwen_config.api_key_env} is missing")

    user_content: list[dict[str, Any]] = [{"type": "text", "text": user_prompt}]
    for image in images:
        anchor = (image_anchors or {}).get(image.image_id)
        if anchor:
            user_content.append({"type": "text", "text": anchor})
        user_content.append({"type": "image_url", "image_url": {"url": _data_url_for_image(image)}})

    payload = {
        "model": qwen_config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        "max_tokens": qwen_config.max_tokens,
    }
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{qwen_config.base_url}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    response_body = ""
    for attempt in range(1, qwen_config.retry_attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=qwen_config.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            if exc.code in TRANSIENT_HTTP_STATUS_CODES and attempt < qwen_config.retry_attempts:
                _sleep_before_retry(attempt, qwen_config)
                continue
            raise QwenVLProviderError(f"Qwen VL HTTP {exc.code}: {error_body}") from exc
        except urllib.error.URLError as exc:
            if attempt < qwen_config.retry_attempts:
                _sleep_before_retry(attempt, qwen_config)
                continue
            raise QwenVLProviderError(f"Qwen VL request failed: {exc.reason}") from exc
        except (TimeoutError, socket.timeout, ConnectionResetError, ConnectionAbortedError) as exc:
            if attempt < qwen_config.retry_attempts:
                _sleep_before_retry(attempt, qwen_config)
                continue
            raise QwenVLProviderError(f"Qwen VL request timed out: {exc}") from exc

    try:
        response_payload = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise QwenVLProviderError("Qwen VL response is not valid JSON") from exc
    if not isinstance(response_payload, dict):
        raise QwenVLProviderError("Qwen VL response must be a JSON object")
    content = _extract_content(response_payload)
    usage = usage_from_payload(response_payload) or estimate_usage(
        prompt_text=prompt_text_for_messages(payload["messages"]),
        completion_text=content,
    )
    stage = str((config or {}).get("usage_stage") or "")
    record_usage(
        provider=DEFAULT_PROVIDER,
        model=qwen_config.model,
        stage=stage,
        usage=usage,
        metadata={"api_key_env": qwen_config.api_key_env, "image_count": len(images)},
    )
    return LLMResponse(content, usage)
