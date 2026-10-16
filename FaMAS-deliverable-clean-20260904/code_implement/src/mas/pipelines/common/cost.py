"""RMB cost estimation from token usage records."""

from __future__ import annotations

from collections import OrderedDict
from typing import Any


COST_NOTE = "缓存命中价未区分，统一按未命中价计；Qwen 按单次调用上下文长度分档"

QWEN_35_FLASH_TIERS = [
    (128_000, 0.2, 2.0),
    (256_000, 0.8, 8.0),
    (1_000_000, 1.2, 12.0),
]
QWEN_VL_FLASH_TIERS = [
    (32_000, 0.15, 1.5),
    (128_000, 0.3, 3.0),
    (256_000, 0.6, 6.0),
]
SINGLE_PRICE_MODELS = {
    "deepseek-v4-flash": (1.0, 2.0),
}


def _as_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _qwen_tier_price(prompt_tokens: int, tiers: list[tuple[int, float, float]]) -> tuple[float, float]:
    for upper_bound, input_price, output_price in tiers:
        if prompt_tokens <= upper_bound:
            return input_price, output_price
    return tiers[-1][1], tiers[-1][2]


def _prices_for_record(model: str, prompt_tokens: int) -> tuple[float, float] | None:
    normalized = str(model or "").strip().lower()
    if "qwen3.5-flash" in normalized:
        return _qwen_tier_price(prompt_tokens, QWEN_35_FLASH_TIERS)
    if "qwen3-vl-flash" in normalized:
        return _qwen_tier_price(prompt_tokens, QWEN_VL_FLASH_TIERS)
    if "qwen-vl-plus" in normalized:
        # TODO: verify qwen-vl-plus pricing when official tiers are published
        return _qwen_tier_price(prompt_tokens, QWEN_VL_FLASH_TIERS)
    for model_key, prices in SINGLE_PRICE_MODELS.items():
        if model_key in normalized:
            return prices
    return None


def estimate_cost_rmb(usage: dict[str, Any] | None) -> dict[str, Any]:
    """Estimate RMB costs from ``usage_snapshot()["records"]``.

    Qwen pricing is selected per individual call using that call's prompt
    token count, then aggregated by model.
    """

    records = (usage or {}).get("records", [])
    buckets: OrderedDict[str, dict[str, Any]] = OrderedDict()
    unknown_models: set[str] = set()
    for record in records if isinstance(records, list) else []:
        if not isinstance(record, dict):
            continue
        model = str(record.get("model", "") or "")
        prompt_tokens = _as_int(record.get("prompt_tokens", 0))
        completion_tokens = _as_int(record.get("completion_tokens", 0))
        bucket = buckets.setdefault(
            model,
            {
                "model": model,
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "cost_rmb": 0.0,
            },
        )
        bucket["prompt_tokens"] += prompt_tokens
        bucket["completion_tokens"] += completion_tokens
        prices = _prices_for_record(model, prompt_tokens)
        if prices is None:
            bucket["cost_rmb"] = None
            unknown_models.add(model or "<empty>")
            continue
        if bucket["cost_rmb"] is not None:
            input_price, output_price = prices
            bucket["cost_rmb"] += (prompt_tokens * input_price / 1_000_000) + (
                completion_tokens * output_price / 1_000_000
            )

    by_model = list(buckets.values())
    has_unknown = bool(unknown_models)
    total = None if has_unknown else sum(float(item.get("cost_rmb") or 0.0) for item in by_model)
    note = COST_NOTE
    if unknown_models:
        note += "；未知模型未计价: " + ", ".join(sorted(unknown_models))
    return {
        "by_model": by_model,
        "total_rmb": total,
        "note": note,
    }
