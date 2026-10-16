"""Tolerant JSON extraction shared across MAS auditors and agents."""

from __future__ import annotations

import json
import re
from typing import Any


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S | re.I)
_JSON_SIMPLE_ESCAPES = {'"', "\\", "/", "b", "f", "n", "r", "t"}
_HEX_DIGITS = set("0123456789abcdefABCDEF")


def extract_json_object(raw: str) -> dict[str, Any]:
    """Parse a JSON object from possibly noisy LLM output."""

    text = (raw or "").strip()
    recovery_candidates: list[str] = [text]
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    for match in _FENCE_RE.finditer(text):
        candidate = match.group(1).strip()
        recovery_candidates.append(candidate)
        try:
            data = json.loads(candidate)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue

    span = _first_balanced_object(text)
    if span is not None:
        recovery_candidates.append(span)
        try:
            data = json.loads(span)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            pass

    for candidate in _unique_candidates(recovery_candidates):
        cleaned = _escape_invalid_json_string_backslashes(candidate)
        if cleaned == candidate:
            continue
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                return data
        except json.JSONDecodeError:
            continue
    raise ValueError("no parseable JSON object found in response")


def _unique_candidates(candidates: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)
        unique.append(candidate)
    return unique


def _escape_invalid_json_string_backslashes(text: str) -> str:
    output: list[str] = []
    in_str = False
    index = 0
    while index < len(text):
        ch = text[index]
        if not in_str:
            output.append(ch)
            if ch == '"':
                in_str = True
            index += 1
            continue

        if ch == '"':
            output.append(ch)
            in_str = False
            index += 1
            continue

        if ch != "\\":
            output.append(ch)
            index += 1
            continue

        next_ch = text[index + 1] if index + 1 < len(text) else ""
        if next_ch in _JSON_SIMPLE_ESCAPES:
            output.append(text[index : index + 2])
            index += 2
            continue
        if (
            next_ch == "u"
            and index + 5 < len(text)
            and all(part in _HEX_DIGITS for part in text[index + 2 : index + 6])
        ):
            output.append(text[index : index + 6])
            index += 6
            continue

        output.append("\\\\")
        index += 1

    return "".join(output)


def _first_balanced_object(text: str) -> str | None:
    start = text.find("{")
    while start != -1:
        depth = 0
        in_str = False
        esc = False
        for index in range(start, len(text)):
            ch = text[index]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start : index + 1]
        start = text.find("{", start + 1)
    return None
