from __future__ import annotations

import time

_failed_login_attempts: dict[str, list[float]] = {}


class LoginRateLimitExceeded(Exception):
    pass


def login_rate_limit_key(username: str, client_host: str) -> str:
    return f"{client_host.strip() or 'unknown'}:{username.strip().lower()}"


def assert_login_allowed(
    key: str,
    *,
    max_attempts: int,
    window_seconds: int,
    now: float | None = None,
) -> None:
    attempts = _pruned_attempts(key, window_seconds=window_seconds, now=now)
    if len(attempts) >= max_attempts:
        raise LoginRateLimitExceeded


def record_failed_login(
    key: str,
    *,
    window_seconds: int,
    now: float | None = None,
) -> None:
    timestamp = time.time() if now is None else now
    attempts = _pruned_attempts(key, window_seconds=window_seconds, now=timestamp)
    attempts.append(timestamp)
    _failed_login_attempts[key] = attempts


def reset_login_attempts(key: str) -> None:
    _failed_login_attempts.pop(key, None)


def clear_login_rate_limits() -> None:
    _failed_login_attempts.clear()


def _pruned_attempts(
    key: str,
    *,
    window_seconds: int,
    now: float | None = None,
) -> list[float]:
    timestamp = time.time() if now is None else now
    cutoff = timestamp - window_seconds
    attempts = [
        attempt
        for attempt in _failed_login_attempts.get(key, [])
        if attempt >= cutoff
    ]
    _failed_login_attempts[key] = attempts
    return attempts
