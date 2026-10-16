"""Mock and real agent entry points for KG Extraction MAS."""

from __future__ import annotations

import json
import os
import re
import socket
import time
import http.client
from typing import Any
import urllib.error
import urllib.request

from mas.config.models import get_model
from mas.pipelines.common.json_recovery import extract_json_object
from mas.pipelines.common.qwen_text_provider import QwenTextProviderError, QwenTextTimeoutError, call_qwen_text
from mas.pipelines.common.usage_tracker import (
    LLMResponse,
    estimate_usage,
    prompt_text_for_messages,
    record_usage,
    usage_from_payload,
)

from .models import make_stable_id


_KG_TEXT_MODEL = get_model("kg_text")
_KG_VALIDATION_MODEL = get_model("kg_validation")
DEFAULT_TEXT_MODEL = str(_KG_TEXT_MODEL.get("name", "qwen3.5-flash"))
DEFAULT_VALIDATION_PROVIDER = str(_KG_VALIDATION_MODEL.get("provider", "deepseek_openai_compatible"))
DEFAULT_VALIDATION_MODEL = str(_KG_VALIDATION_MODEL.get("name", "deepseek-v4-flash"))
DEFAULT_VALIDATION_BASE_URL = str(_KG_VALIDATION_MODEL.get("base_url", "https://api.deepseek.com"))
DEFAULT_VALIDATION_API_KEY_ENV = str(_KG_VALIDATION_MODEL.get("api_key_env", "DEEPSEEK_API_KEY"))
TRANSIENT_HTTP_STATUS_CODES = {408, 429, 500, 502, 503, 504}
TRANSIENT_CONNECTION_ERRORS = (
    ConnectionResetError,
    ConnectionAbortedError,
    http.client.RemoteDisconnected,
)
TRANSIENT_REQUEST_ERRORS = (
    urllib.error.URLError,
    TimeoutError,
    socket.timeout,
) + TRANSIENT_CONNECTION_ERRORS


class ExtractionModelNotConfiguredError(RuntimeError):
    """Raised when a required extraction model configuration is missing."""


class ValidationModelNotConfiguredError(RuntimeError):
    """Raised when real VA is requested without provider/model/API key config."""


class ExtractionModelCallError(RuntimeError):
    """Raised when a real model call fails or returns invalid output."""

    def __init__(self, message: str, *, raw_response: str = "") -> None:
        super().__init__(message)
        self.raw_response = raw_response


class ExtractionModelTimeoutError(ExtractionModelCallError):
    """Raised when a real extraction model call times out."""


def _is_qwen_configuration_error(error: QwenTextProviderError) -> bool:
    text = str(error).lower()
    return text.startswith("unsupported provider:") or ("environment variable" in text and "missing" in text)


def _raise_extraction_provider_error(error: QwenTextProviderError) -> None:
    if isinstance(error, QwenTextTimeoutError):
        raised = ExtractionModelTimeoutError(str(error), raw_response="")
        raised.attempt_records = list(getattr(error, "attempt_records", []))
        raise raised from error
    if "content is empty" in str(error).lower():
        raise ExtractionModelCallError(str(error), raw_response="") from error
    if _is_qwen_configuration_error(error):
        raise ExtractionModelNotConfiguredError(str(error)) from error
    raise ExtractionModelCallError(str(error), raw_response="") from error


def _parse_strict_json(raw: str, stage: str) -> dict[str, Any]:
    try:
        return extract_json_object(raw)
    except ValueError as exc:
        raise ExtractionModelCallError(f"{stage} response is not valid JSON", raw_response=raw) from exc


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
    if not code:
        scrubbed = str(body)
        for secret in [api_key]:
            if secret:
                scrubbed = scrubbed.replace(secret, "[REDACTED_SECRET]")
        scrubbed = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer [REDACTED_SECRET]", scrubbed, flags=re.I)
        scrubbed = re.sub(r"Authorization\s*[:=]\s*[^,\s}\]]+", "Authorization=[REDACTED_SECRET]", scrubbed, flags=re.I)
        code = scrubbed[:120].replace("\n", " ").strip()
    return code or "provider_error"


def _prompt_contexts(prompt: dict[str, Any]) -> list[dict[str, Any]]:
    user = prompt.get("user", "")
    if "INPUT_JSON" in user:
        payload_text = user.split("INPUT_JSON", 1)[1].strip()
    else:
        payload_text = user
    try:
        payload = json.loads(payload_text)
    except json.JSONDecodeError:
        return []
    return payload.get("section_contexts", []) if isinstance(payload, dict) else []


def _prompt_schema(prompt: dict[str, Any]) -> dict[str, Any]:
    user = prompt.get("user", "")
    if "INPUT_JSON" in user:
        try:
            payload = json.loads(user.split("INPUT_JSON", 1)[1].strip())
            return payload.get("schema", {})
        except json.JSONDecodeError:
            return {}
    try:
        payload = json.loads(user)
        return payload.get("schema", {})
    except json.JSONDecodeError:
        return {}


def _context_like(context_json: dict[str, Any]):
    class _Context:
        source_context_id = context_json["source_context_id"]
        section_id = context_json["section_id"]
        markdown_path = context_json["markdown_path"]
        markdown_file = context_json["markdown_file"]
        markdown_text = context_json["markdown_text"]
        textbook_profile = context_json["textbook_profile"]
        section_metadata = context_json["section_metadata"]

    return _Context()


def _text_evidence_ref(*, context: Any, source_path: str, quote_or_summary: str) -> dict[str, Any]:
    return {
        "source_path": str(source_path),
        "section": {
            "source_context_id": context.source_context_id,
            "section_id": context.section_id,
            "metadata": context.section_metadata,
        },
        "quote_or_summary": quote_or_summary,
    }


def _figure_refs(context_json: dict[str, Any]) -> list[dict[str, Any]]:
    figures: list[dict[str, Any]] = []
    for ipa in context_json.get("ipa_image_evidence", []):
        if not isinstance(ipa, dict):
            continue
        image_path = str(ipa.get("image_path", "") or "").strip()
        if not image_path:
            continue
        figure: dict[str, Any] = {"image_path": image_path}
        name = str(ipa.get("name", "") or "").strip()
        description = str(ipa.get("description_text", "") or "").strip()
        if name:
            figure["name"] = name
        if description:
            figure["description"] = description
        figures.append(figure)
    return figures


def _mock_nea(prompt: dict[str, Any]) -> dict[str, Any]:
    contexts = _prompt_contexts(prompt)
    nodes: list[dict[str, Any]] = []
    for context_json in contexts:
        ctx = _context_like(context_json)
        title = str(ctx.section_metadata.get("chapter_title") or ctx.markdown_file)
        chapter_id = make_stable_id("node_chaptersection", ["ChapterSection", ctx.source_context_id, ctx.markdown_file, title])
        section_evidence = _text_evidence_ref(context=ctx, source_path=str(ctx.markdown_path), quote_or_summary=title)
        nodes.append(
            {
                "node_id": chapter_id,
                "label": "ChapterSection",
                "properties": {
                    "title": title,
                    "chapter_num": str(ctx.section_metadata.get("chapter_num", "")),
                    "section_num": str(ctx.section_metadata.get("section_num", "")),
                    "source_path": str(ctx.markdown_path),
                    "line_range": {
                        "start_line": ctx.section_metadata.get("start_line"),
                        "end_line": ctx.section_metadata.get("end_line"),
                    },
                    "evidence": [section_evidence],
                    "confidence": 0.95,
                },
                "source_context_id": ctx.source_context_id,
                "revision_round": 0,
                "status": "candidate",
                "audit_refs": [],
            }
        )
        kp_name = "数级" if "数位" in ctx.markdown_text or "数级" in ctx.markdown_text else title.replace(" ", "")
        quote = "从右边起，每四个数位是一级。" if "从右边起，每四个数位是一级" in ctx.markdown_text else title
        evidence = _text_evidence_ref(context=ctx, source_path=str(ctx.markdown_path), quote_or_summary=quote)
        properties: dict[str, Any] = {
            "name": kp_name,
            "definition": quote,
            "aliases": [kp_name.replace(" ", "")],
            "evidence": [evidence],
            "confidence": 0.88,
        }
        figures = _figure_refs(context_json)
        if figures:
            properties["figures"] = figures
        kp_id = make_stable_id("node_knowledgepoint", ["KnowledgePoint", ctx.source_context_id, ctx.markdown_file, kp_name])
        nodes.append(
            {
                "node_id": kp_id,
                "label": "KnowledgePoint",
                "properties": properties,
                "source_context_id": ctx.source_context_id,
                "revision_round": 0,
                "status": "candidate",
                "audit_refs": [],
            }
        )
    return {
        "schema_version": "kg.node_extraction.v1",
        "run_id": "node_mock",
        "mock": True,
        "batch_id": "batch_001",
        "nodes": nodes,
        "rejected_evidence": [],
    }


def _mock_eea(prompt: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.loads(prompt["user"].split("INPUT_JSON", 1)[1].strip())
    except Exception:
        payload = {}
    node_pack = payload.get("node_pack", {})
    nodes = node_pack.get("nodes", [])
    by_label: dict[str, list[dict[str, Any]]] = {}
    for node in nodes:
        by_label.setdefault(node.get("label", ""), []).append(node)
    edges = []
    for chapter in by_label.get("ChapterSection", []):
        for kp in by_label.get("KnowledgePoint", []):
            if chapter.get("source_context_id") != kp.get("source_context_id"):
                continue
            edge_id = make_stable_id(
                "edge_contains",
                ["contains", chapter["node_id"], kp["node_id"], chapter["source_context_id"]],
            )
            evidence = kp.get("properties", {}).get("evidence", chapter.get("properties", {}).get("evidence", []))
            properties: dict[str, Any] = {
                "relation_label": "章节包含知识点",
                "rationale": "知识点出现在该章节内容中；相关图像作为 FigureRef 挂载。",
                "evidence": evidence,
                "confidence": 0.86,
            }
            figures = kp.get("properties", {}).get("figures", [])
            if isinstance(figures, list) and figures:
                properties["figures"] = [dict(figure) for figure in figures if isinstance(figure, dict)]
            edges.append(
                {
                    "edge_id": edge_id,
                    "predicate": "contains",
                    "source_node_id": chapter["node_id"],
                    "target_node_id": kp["node_id"],
                    "properties": properties,
                    "source_context_id": chapter["source_context_id"],
                    "revision_round": 0,
                    "status": "candidate",
                    "audit_refs": [],
                }
            )
    return {
        "schema_version": "kg.edge_extraction.v1",
        "run_id": "edge_mock",
        "mock": True,
        "batch_id": "batch_001",
        "edges": edges,
    }


def run_nea(
    prompt: dict[str, Any],
    *,
    mock: bool,
    model_config: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Run Node Extraction Agent.

    Args:
        prompt: Prompt package from `build_nea_prompt`.
        mock: Whether to use deterministic mock output.
        model_config: Text model config.

    Returns:
        Tuple of parsed node candidate package and raw response text.

    Raises:
        ExtractionModelNotConfiguredError: If real config is missing.
        ExtractionModelCallError: If real output is not strict JSON.
    """

    if mock:
        data = _mock_nea(prompt)
        raw = json.dumps(data, ensure_ascii=False)
        return data, raw
    config = dict(model_config or {})
    config.setdefault("model", config.get("name") or DEFAULT_TEXT_MODEL)
    try:
        raw = call_qwen_text(prompt["system"], prompt["user"], config=config)
    except QwenTextProviderError as exc:
        _raise_extraction_provider_error(exc)
    return _parse_strict_json(raw, "NEA"), raw


def run_eea(
    prompt: dict[str, Any],
    *,
    mock: bool,
    model_config: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Run Edge Extraction Agent.

    Args:
        prompt: Prompt package from `build_eea_prompt`.
        mock: Whether to use deterministic mock output.
        model_config: Text model config.

    Returns:
        Tuple of parsed edge candidate package and raw response text.
    """

    if mock:
        data = _mock_eea(prompt)
        raw = json.dumps(data, ensure_ascii=False)
        return data, raw
    config = dict(model_config or {})
    config.setdefault("model", config.get("name") or DEFAULT_TEXT_MODEL)
    try:
        raw = call_qwen_text(prompt["system"], prompt["user"], config=config)
    except QwenTextProviderError as exc:
        _raise_extraction_provider_error(exc)
    return _parse_strict_json(raw, "EEA"), raw


def run_va(
    prompt: dict[str, Any],
    *,
    mock: bool,
    validation_config: dict[str, Any],
) -> str:
    """Run Validation Agent and return raw VA text.

    Args:
        prompt: Prompt package from `build_va_prompt`.
        mock: Whether to use deterministic mock VA.
        validation_config: Explicit provider/model/base_url/api_key_env config.

    Returns:
        Raw VA text containing `<VA_PASS>` or `<VA_REVISE>`.

    Raises:
        ValidationModelNotConfiguredError: If real VA config is incomplete.
        ExtractionModelCallError: If provider call fails.
    """

    if mock:
        return "<VA_PASS>\nAll checked items pass validation.\n</VA_PASS>"
    provider = validation_config.get("provider")
    model = validation_config.get("model")
    base_url = validation_config.get("base_url")
    api_key_env = validation_config.get("api_key_env")
    if not provider or not model or not base_url or not api_key_env:
        raise ValidationModelNotConfiguredError("real VA requires provider, model, base_url, and api_key_env")
    return _call_openai_compatible_text(
        system_prompt=prompt["system"],
        user_prompt=prompt["user"],
        provider=provider,
        model=model,
        base_url=base_url,
        api_key_env=api_key_env,
        timeout_seconds=int(validation_config.get("timeout_seconds", 120)),
        retry_attempts=int(validation_config.get("retry_attempts", 3)),
        seed=int(validation_config["seed"]) if validation_config.get("seed") is not None else None,
        usage_stage=str(validation_config.get("usage_stage") or ""),
    )


def run_sda(
    prompt: dict[str, Any],
    *,
    mock: bool,
    model_config: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    """Run Standard Agent.

    Args:
        prompt: Prompt package from `build_sda_prompt`.
        mock: Whether to use deterministic standardization.
        model_config: Text model config.

    Returns:
        Tuple of parsed SdA output or hints and raw response text.
    """

    if mock:
        raw = json.dumps({"schema_version": "kg.standard_agent.v1", "mock": True}, ensure_ascii=False)
        return json.loads(raw), raw
    config = dict(model_config or {})
    config.setdefault("model", config.get("name") or DEFAULT_TEXT_MODEL)
    try:
        raw = call_qwen_text(prompt["system"], prompt["user"], config=config)
    except QwenTextProviderError as exc:
        _raise_extraction_provider_error(exc)
    return _parse_strict_json(raw, "SdA"), raw


def _call_openai_compatible_text(
    *,
    system_prompt: str,
    user_prompt: str,
    provider: str,
    model: str,
    base_url: str,
    api_key_env: str,
    timeout_seconds: int,
    retry_attempts: int,
    seed: int | None = None,
    usage_stage: str = "",
) -> str:
    """Call an OpenAI-compatible chat completion endpoint."""

    if provider != DEFAULT_VALIDATION_PROVIDER:
        raise ValidationModelNotConfiguredError(f"unsupported validation provider: {provider}")
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise ValidationModelNotConfiguredError(f"environment variable {api_key_env} is missing")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.0,
    }
    if seed is not None:
        payload["seed"] = seed
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    response_body = ""
    for attempt in range(1, max(1, retry_attempts) + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
            break
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            if exc.code in TRANSIENT_HTTP_STATUS_CODES and attempt < retry_attempts:
                time.sleep(2.0 * attempt)
                continue
            reason = _summarize_provider_error(body, api_key)
            raise ExtractionModelCallError(f"Validation HTTP {exc.code}: {reason}") from exc
        except TRANSIENT_REQUEST_ERRORS as exc:
            if attempt < retry_attempts:
                time.sleep(2.0 * attempt)
                continue
            raise ExtractionModelCallError(f"Validation request failed: {exc}") from exc
    try:
        response_payload = json.loads(response_body)
        content = response_payload["choices"][0]["message"]["content"]
    except Exception as exc:
        raise ExtractionModelCallError("Validation response is malformed", raw_response=response_body) from exc
    if not isinstance(content, str) or not content.strip():
        raise ExtractionModelCallError("Validation response content is empty", raw_response=response_body)
    usage = usage_from_payload(response_payload) or estimate_usage(
        prompt_text=prompt_text_for_messages(payload["messages"]),
        completion_text=content,
    )
    record_usage(
        provider=provider,
        model=model,
        stage=usage_stage,
        usage=usage,
        metadata={"api_key_env": api_key_env},
    )
    return LLMResponse(content, usage)
