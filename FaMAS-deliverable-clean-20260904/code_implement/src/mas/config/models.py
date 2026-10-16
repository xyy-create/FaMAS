"""Central model-name configuration for MAS stages."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from .pipeline import project_root


FALLBACK_MODELS: dict[str, dict[str, Any]] = {
    "kg_text": {"name": "qwen3.5-flash", "api_key_env": "DASHSCOPE_API_KEY"},
    "kg_validation": {
        "name": "deepseek-v4-flash",
        "base_url": "https://api.deepseek.com",
        "api_key_env": "DEEPSEEK_API_KEY",
        "provider": "deepseek_openai_compatible",
    },
    "ita_vision": {"name": "qwen3-vl-flash", "api_key_env": "DASHSCOPE_API_KEY"},
    "ipa_generator": {"name": "qwen3-vl-flash", "api_key_env": "DASHSCOPE_API_KEY"},
    "ipa_verifier": {"name": "qwen-vl-plus", "api_key_env": "DASHSCOPE_API_KEY"},
    "schema_agent": {"name": "qwen3.5-flash", "api_key_env": "DASHSCOPE_API_KEY"},
}


def default_models_path() -> Path:
    return project_root() / "config" / "models.yaml"


def _sanitize_model_config(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    sanitized = deepcopy(FALLBACK_MODELS)
    for stage, values in raw.items():
        if not isinstance(values, dict):
            continue
        stage_config = dict(sanitized.get(stage, {}))
        for key in ("name", "base_url", "provider", "api_key_env"):
            if key in values and values[key] is not None:
                stage_config[key] = str(values[key])
        sanitized[stage] = stage_config
    return sanitized


def load_model_config(config_path: str | Path | None = None) -> dict[str, dict[str, Any]]:
    """Load configured model identifiers, falling back when the YAML is absent."""

    path = Path(config_path) if config_path is not None else default_models_path()
    if not path.exists():
        return deepcopy(FALLBACK_MODELS)
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    models = raw.get("models", raw)
    if not isinstance(models, dict):
        return deepcopy(FALLBACK_MODELS)
    return _sanitize_model_config(models)


def get_model(stage: str, config_path: str | Path | None = None) -> dict[str, Any]:
    """Return one stage's model config without exposing any secret values."""

    return dict(load_model_config(config_path).get(stage, FALLBACK_MODELS.get(stage, {})))
