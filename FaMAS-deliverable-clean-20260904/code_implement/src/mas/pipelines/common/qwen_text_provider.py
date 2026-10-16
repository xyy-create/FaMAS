"""OpenAI-compatible Qwen text provider using only the Python standard library."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import socket
import time
import http.client
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
DEFAULT_MODEL = "qwen3.5-flash"
DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
DEFAULT_API_KEY_ENV = "DASHSCOPE_API_KEY"
DEFAULT_TIMEOUT_SECONDS = 120
DEFAULT_MAX_TOKENS = 8192
DEFAULT_MAX_INPUT_TOKENS = 64000
DEFAULT_TEMPERATURE = 0.0
DEFAULT_RETRY_ATTEMPTS = 5
DEFAULT_RETRY_BACKOFF_SECONDS = 3.0
DEFAULT_TIMEOUT_RETRY_ATTEMPTS = 3
DEFAULT_TIMEOUT_RETRY_BUDGET_SECONDS = 600
TRANSIENT_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504}
TRANSIENT_CONNECTION_ERRORS = (
    ConnectionResetError,
    ConnectionAbortedError,
    http.client.RemoteDisconnected,
)


class QwenTextProviderError(RuntimeError):
    """Raised when the Qwen text provider cannot complete a request."""


class QwenTextTimeoutError(QwenTextProviderError):
    """Raised when a Qwen text request exhausts its read/connect timeout."""

    def __init__(self, message: str, *, attempt_records: list[dict[str, Any]] | None = None) -> None:
        super().__init__(message)
        self.attempt_records = attempt_records or []


@dataclass
class QwenTextConfig:
    provider: str = DEFAULT_PROVIDER
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    api_key_env: str = DEFAULT_API_KEY_ENV
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_tokens: int = DEFAULT_MAX_TOKENS
    max_input_tokens: int = DEFAULT_MAX_INPUT_TOKENS
    temperature: float = DEFAULT_TEMPERATURE
    retry_attempts: int = DEFAULT_RETRY_ATTEMPTS
    retry_backoff_seconds: float = DEFAULT_RETRY_BACKOFF_SECONDS
    timeout_retry_attempts: int = DEFAULT_TIMEOUT_RETRY_ATTEMPTS
    timeout_retry_budget_seconds: int = DEFAULT_TIMEOUT_RETRY_BUDGET_SECONDS
    seed: int | None = None


def _config_from_dict(config: dict[str, Any] | None) -> QwenTextConfig:
    data = config or {}
    retry_attempts = data.get("retry_attempts")
    retry_backoff_seconds = data.get("retry_backoff_seconds")
    timeout_retry_attempts = data.get("timeout_retry_attempts")
    timeout_retry_budget_seconds = data.get("timeout_retry_budget_seconds")
    seed_value = data.get("seed")
    return QwenTextConfig(
        provider=str(data.get("provider") or DEFAULT_PROVIDER),
        model=str(data.get("name") or data.get("model") or DEFAULT_MODEL),
        base_url=str(data.get("base_url") or DEFAULT_BASE_URL).rstrip("/"),
        api_key_env=str(data.get("api_key_env") or DEFAULT_API_KEY_ENV),
        timeout_seconds=int(data.get("timeout_seconds") or DEFAULT_TIMEOUT_SECONDS),
        max_tokens=int(data.get("max_tokens") or DEFAULT_MAX_TOKENS),
        max_input_tokens=int(data.get("max_input_tokens") or DEFAULT_MAX_INPUT_TOKENS),
        temperature=float(data.get("temperature") if data.get("temperature") is not None else DEFAULT_TEMPERATURE),
        retry_attempts=max(1, int(retry_attempts if retry_attempts is not None else DEFAULT_RETRY_ATTEMPTS)),
        retry_backoff_seconds=max(
            0.0,
            float(retry_backoff_seconds if retry_backoff_seconds is not None else DEFAULT_RETRY_BACKOFF_SECONDS),
        ),
        timeout_retry_attempts=max(
            1,
            int(timeout_retry_attempts if timeout_retry_attempts is not None else DEFAULT_TIMEOUT_RETRY_ATTEMPTS),
        ),
        timeout_retry_budget_seconds=max(
            1,
            int(
                timeout_retry_budget_seconds
                if timeout_retry_budget_seconds is not None
                else DEFAULT_TIMEOUT_RETRY_BUDGET_SECONDS
            ),
        ),
        seed=int(seed_value) if seed_value is not None else None,
    )


def _extract_content(response_payload: dict[str, Any]) -> str:
    choices = response_payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise QwenTextProviderError("Qwen text response missing choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise QwenTextProviderError("Qwen text response choice is not an object")
    message = first.get("message")
    if not isinstance(message, dict):
        raise QwenTextProviderError("Qwen text response missing message")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise QwenTextProviderError("Qwen text response content is empty")
    return content


def _summarize_provider_error(body: str, api_key: str) -> str:
    """Return a short provider error summary without secret-bearing text."""

    code = ""
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        parsed = {}
    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, dict):
            code = str(error.get("code") or error.get("type") or "").strip()
            message = str(error.get("message") or "").strip()
            param = str(error.get("param") or "").strip()
            details = []
            if code:
                details.append(code)
            if message:
                details.append(message[:180])
            if param:
                details.append(f"param={param}")
            if details:
                code = " | ".join(details)
    if not code:
        scrubbed = str(body)
        if api_key:
            scrubbed = scrubbed.replace(api_key, "[REDACTED_SECRET]")
        scrubbed = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer [REDACTED_SECRET]", scrubbed, flags=re.I)
        scrubbed = re.sub(r"Authorization\s*[:=]\s*[^,\s}\]]+", "Authorization=[REDACTED_SECRET]", scrubbed, flags=re.I)
        code = scrubbed[:120].replace("\n", " ").strip()
    return code or "provider_error"


def _sleep_before_retry(attempt_index: int, qwen_config: QwenTextConfig) -> None:
    if qwen_config.retry_backoff_seconds <= 0:
        return
    time.sleep(qwen_config.retry_backoff_seconds * attempt_index)


def _sleep_before_timeout_retry(attempt_index: int, qwen_config: QwenTextConfig) -> None:
    if qwen_config.retry_backoff_seconds <= 0:
        return
    time.sleep(min(qwen_config.retry_backoff_seconds * attempt_index, 2.0))


def _is_timeout_error(error: BaseException) -> bool:
    if isinstance(error, (TimeoutError, socket.timeout)):
        return True
    reason = getattr(error, "reason", None)
    return isinstance(reason, (TimeoutError, socket.timeout))


def _is_transient_connection_error(error: BaseException) -> bool:
    if isinstance(error, TRANSIENT_CONNECTION_ERRORS):
        return True
    reason = getattr(error, "reason", None)
    return isinstance(reason, TRANSIENT_CONNECTION_ERRORS)


def call_qwen_text(
    system_prompt: str,
    user_prompt: str,
    config: dict[str, Any] | None = None,
) -> str:
    qwen_config = _config_from_dict(config)
    if qwen_config.provider != DEFAULT_PROVIDER:
        raise QwenTextProviderError(f"unsupported provider: {qwen_config.provider}")
    api_key = os.environ.get(qwen_config.api_key_env)
    if not api_key:
        raise QwenTextProviderError(f"environment variable {qwen_config.api_key_env} is missing")

    payload = {
        "model": qwen_config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": qwen_config.temperature,
        "max_tokens": qwen_config.max_tokens,
    }
    if qwen_config.seed is not None:
        payload["seed"] = qwen_config.seed
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
    transient_attempt = 1
    timeout_attempts = 0
    timeout_attempt_records: list[dict[str, Any]] = []
    started = time.monotonic()
    while True:
        attempt_started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=qwen_config.timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            error_body = exc.read().decode("utf-8", errors="replace")
            if exc.code in TRANSIENT_HTTP_STATUS_CODES and transient_attempt < qwen_config.retry_attempts:
                _sleep_before_retry(transient_attempt, qwen_config)
                transient_attempt += 1
                continue
            reason = _summarize_provider_error(error_body, api_key)
            raise QwenTextProviderError(f"Qwen text HTTP {exc.code}: {reason}") from exc
        except urllib.error.URLError as exc:
            if _is_timeout_error(exc):
                timeout_attempts += 1
                timeout_attempt_records.append(
                    {
                        "attempt_index": timeout_attempts,
                        "timeout_seconds": qwen_config.timeout_seconds,
                        "elapsed_seconds": round(time.monotonic() - attempt_started, 3),
                        "exception_type": type(exc.reason).__name__ if hasattr(exc, "reason") else type(exc).__name__,
                        "exception_message": str(getattr(exc, "reason", exc)),
                    }
                )
                elapsed = time.monotonic() - started
                if (
                    timeout_attempts < qwen_config.timeout_retry_attempts
                    and elapsed < qwen_config.timeout_retry_budget_seconds
                ):
                    _sleep_before_timeout_retry(timeout_attempts, qwen_config)
                    continue
                raise QwenTextTimeoutError(
                    f"Qwen text request timed out: {exc.reason}",
                    attempt_records=timeout_attempt_records,
                ) from exc
            if transient_attempt < qwen_config.retry_attempts:
                _sleep_before_retry(transient_attempt, qwen_config)
                transient_attempt += 1
                continue
            raise QwenTextProviderError(f"Qwen text request failed: {exc.reason}") from exc
        except TRANSIENT_CONNECTION_ERRORS as exc:
            if _is_transient_connection_error(exc) and transient_attempt < qwen_config.retry_attempts:
                _sleep_before_retry(transient_attempt, qwen_config)
                transient_attempt += 1
                continue
            if transient_attempt < qwen_config.retry_attempts:
                _sleep_before_retry(transient_attempt, qwen_config)
                transient_attempt += 1
                continue
            raise QwenTextProviderError(f"Qwen text request failed: {exc}") from exc
        except (TimeoutError, socket.timeout) as exc:
            timeout_attempts += 1
            timeout_attempt_records.append(
                {
                    "attempt_index": timeout_attempts,
                    "timeout_seconds": qwen_config.timeout_seconds,
                    "elapsed_seconds": round(time.monotonic() - attempt_started, 3),
                    "exception_type": type(exc).__name__,
                    "exception_message": str(exc),
                }
            )
            elapsed = time.monotonic() - started
            if (
                timeout_attempts < qwen_config.timeout_retry_attempts
                and elapsed < qwen_config.timeout_retry_budget_seconds
            ):
                _sleep_before_timeout_retry(timeout_attempts, qwen_config)
                continue
            raise QwenTextTimeoutError(
                f"Qwen text request timed out: {exc}",
                attempt_records=timeout_attempt_records,
            ) from exc

    try:
        response_payload = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise QwenTextProviderError("Qwen text response is not valid JSON") from exc
    if not isinstance(response_payload, dict):
        raise QwenTextProviderError("Qwen text response must be a JSON object")
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
        metadata={"api_key_env": qwen_config.api_key_env},
    )
    return LLMResponse(content, usage)
