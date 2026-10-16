from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.config import settings

from conftest import create_user


def test_login_rate_limit_blocks_repeated_failed_attempts(
    client,
    db_session: Session,
    monkeypatch,
) -> None:
    create_user(db_session, "limited_user", password="password123")
    monkeypatch.setattr(settings, "login_rate_limit_max_attempts", 3)
    monkeypatch.setattr(settings, "login_rate_limit_window_seconds", 600)

    for _index in range(3):
        response = client.post(
            "/api/auth/login",
            json={"username": "limited_user", "password": "wrong-password"},
        )
        assert response.status_code == 401

    blocked_response = client.post(
        "/api/auth/login",
        json={"username": "limited_user", "password": "wrong-password"},
    )

    assert blocked_response.status_code == 429
    assert "Too many failed login attempts" in blocked_response.json()["detail"]


def test_successful_login_resets_failed_attempt_count(
    client,
    db_session: Session,
    monkeypatch,
) -> None:
    create_user(db_session, "reset_limited_user", password="password123")
    monkeypatch.setattr(settings, "login_rate_limit_max_attempts", 3)
    monkeypatch.setattr(settings, "login_rate_limit_window_seconds", 600)

    for _index in range(2):
        response = client.post(
            "/api/auth/login",
            json={"username": "reset_limited_user", "password": "wrong-password"},
        )
        assert response.status_code == 401

    success_response = client.post(
        "/api/auth/login",
        json={"username": "reset_limited_user", "password": "password123"},
    )
    assert success_response.status_code == 200

    for _index in range(3):
        response = client.post(
            "/api/auth/login",
            json={"username": "reset_limited_user", "password": "wrong-password"},
        )
        assert response.status_code == 401
