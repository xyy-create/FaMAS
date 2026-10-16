"""Token usage collection helpers for real API runs."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import json
import threading
from typing import Any


USAGE_ESTIMATE_NOTE = "estimated from response/request text because provider usage was unavailable"


@dataclass(frozen=True)
class ModelUsage:
    """Prompt/completion token counts attached to a provider response."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    estimated: bool = False
    source: str = "provider"

    def to_json(self) -> dict[str, Any]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
            "estimated": self.estimated,
            "source": self.source,
        }


class LLMResponse(str):
    """String response that also carries model usage metadata."""

    usage: ModelUsage

    def __new__(cls, value: str, usage: ModelUsage | None = None) -> "LLMResponse":
        obj = str.__new__(cls, value)
        obj.usage = usage or ModelUsage()
        return obj


class UsageTracker:
    """Thread-safe in-process accumulator for API token usage."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: list[dict[str, Any]] = []

    def reset(self) -> None:
        with self._lock:
            self._records = []

    def record(
        self,
        *,
        provider: str,
        model: str,
        stage: str,
        usage: ModelUsage,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not model and not stage:
            return
        with self._lock:
            self._records.append(
                {
                    "provider": provider,
                    "model": model,
                    "stage": stage,
                    "prompt_tokens": int(usage.prompt_tokens),
                    "completion_tokens": int(usage.completion_tokens),
                    "total_tokens": int(usage.total_tokens),
                    "estimated": bool(usage.estimated),
                    "source": usage.source,
                    "metadata": metadata or {},
                }
            )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            records = [dict(record) for record in self._records]
        by_model_stage: dict[tuple[str, str, str], dict[str, Any]] = {}
        for record in records:
            key = (str(record.get("provider", "")), str(record.get("model", "")), str(record.get("stage", "")))
            bucket = by_model_stage.setdefault(
                key,
                {
                    "provider": key[0],
                    "model": key[1],
                    "stage": key[2],
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "calls": 0,
                    "estimated_calls": 0,
                    "has_estimates": False,
                },
            )
            bucket["prompt_tokens"] += int(record.get("prompt_tokens", 0))
            bucket["completion_tokens"] += int(record.get("completion_tokens", 0))
            bucket["total_tokens"] += int(record.get("total_tokens", 0))
            bucket["calls"] += 1
            if record.get("estimated"):
                bucket["estimated_calls"] += 1
                bucket["has_estimates"] = True
        return {
            "schema_version": "mas.token_usage.v1",
            "records": records,
            "by_model_stage": list(by_model_stage.values()),
            "total_prompt_tokens": sum(int(record.get("prompt_tokens", 0)) for record in records),
            "total_completion_tokens": sum(int(record.get("completion_tokens", 0)) for record in records),
            "total_tokens": sum(int(record.get("total_tokens", 0)) for record in records),
            "estimated_calls": sum(1 for record in records if record.get("estimated")),
            "note": USAGE_ESTIMATE_NOTE if any(record.get("estimated") for record in records) else "",
        }


GLOBAL_USAGE_TRACKER = UsageTracker()


def reset_usage() -> None:
    GLOBAL_USAGE_TRACKER.reset()


def record_usage(
    *,
    provider: str,
    model: str,
    stage: str,
    usage: ModelUsage,
    metadata: dict[str, Any] | None = None,
) -> None:
    GLOBAL_USAGE_TRACKER.record(provider=provider, model=model, stage=stage, usage=usage, metadata=metadata)


def usage_snapshot() -> dict[str, Any]:
    return GLOBAL_USAGE_TRACKER.snapshot()


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def usage_from_payload(payload: dict[str, Any]) -> ModelUsage | None:
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt = _as_int(
        usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or usage.get("inputTokenCount")
        or usage.get("input_tokens_details", {}).get("tokens")
    )
    completion = _as_int(
        usage.get("completion_tokens")
        or usage.get("output_tokens")
        or usage.get("outputTokenCount")
        or usage.get("completion_tokens_details", {}).get("tokens")
    )
    total = _as_int(usage.get("total_tokens") or usage.get("totalTokenCount") or (prompt + completion))
    return ModelUsage(prompt_tokens=prompt, completion_tokens=completion, total_tokens=total, estimated=False, source="provider")


def estimate_tokens_from_text(text: Any) -> int:
    compact = str(text or "")
    if not compact:
        return 0
    cjk = sum(1 for char in compact if "\u4e00" <= char <= "\u9fff")
    other = max(0, len(compact) - cjk)
    return max(1, int((cjk / 2.0) + (other / 4.0) + 0.9999))


def estimate_usage(*, prompt_text: Any, completion_text: Any) -> ModelUsage:
    prompt = estimate_tokens_from_text(prompt_text)
    completion = estimate_tokens_from_text(completion_text)
    return ModelUsage(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion,
        estimated=True,
        source="estimate",
    )


def prompt_text_for_messages(messages: Any) -> str:
    try:
        return json.dumps(messages, ensure_ascii=False)
    except TypeError:
        return str(messages)
