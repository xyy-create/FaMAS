from __future__ import annotations

from sqlalchemy.orm import Session

from app.core.security import verify_password
from conftest import auth_headers, create_user


def test_register_rejects_invalid_username_and_weak_password(client) -> None:
    invalid_username = client.post(
        "/api/auth/register",
        json={"username": "bad name", "password": "password123"},
    )
    weak_password = client.post(
        "/api/auth/register",
        json={"username": "valid_user", "password": "password"},
    )

    assert invalid_username.status_code == 400
    assert "Username must be" in invalid_username.json()["detail"]
    assert weak_password.status_code == 400
    assert "Password must be" in weak_password.json()["detail"]


def test_account_password_change_uses_shared_password_policy(
    client,
    db_session: Session,
) -> None:
    user = create_user(db_session, "password_owner", password="password123")

    response = client.post(
        "/api/settings/system/account/password",
        json={"current_password": "password123", "new_password": "short1"},
        headers=auth_headers(user),
    )

    db_session.refresh(user)
    assert response.status_code == 400
    assert "Password must be" in response.json()["detail"]
    assert verify_password("password123", user.password_hash)


def test_account_password_change_invalidates_existing_token(
    client,
    db_session: Session,
) -> None:
    user = create_user(db_session, "token_owner", password="password123")
    old_headers = auth_headers(user)

    response = client.post(
        "/api/settings/system/account/password",
        json={"current_password": "password123", "new_password": "newpass123"},
        headers=old_headers,
    )
    old_me_response = client.get("/api/auth/me", headers=old_headers)
    login_response = client.post(
        "/api/auth/login",
        json={"username": "token_owner", "password": "newpass123"},
    )

    assert response.status_code == 200
    assert old_me_response.status_code == 401
    assert login_response.status_code == 200
    assert login_response.json()["access_token"]


def test_admin_password_reset_uses_shared_password_policy(
    client,
    db_session: Session,
) -> None:
    admin = create_user(db_session, "admin", role="admin")
    user = create_user(db_session, "managed_user", password="password123")

    response = client.put(
        f"/api/users/{user.id}/password",
        json={"new_password": "12345678"},
        headers=auth_headers(admin),
    )

    db_session.refresh(user)
    assert response.status_code == 400
    assert "Password must be" in response.json()["detail"]
    assert verify_password("password123", user.password_hash)


def test_admin_password_reset_invalidates_users_existing_token(
    client,
    db_session: Session,
) -> None:
    admin = create_user(db_session, "token_admin", role="admin")
    user = create_user(db_session, "token_reset_user", password="password123")
    old_headers = auth_headers(user)

    response = client.put(
        f"/api/users/{user.id}/password",
        json={"new_password": "resetpass123"},
        headers=auth_headers(admin),
    )
    old_me_response = client.get("/api/auth/me", headers=old_headers)
    login_response = client.post(
        "/api/auth/login",
        json={"username": "token_reset_user", "password": "resetpass123"},
    )

    assert response.status_code == 200
    assert old_me_response.status_code == 401
    assert login_response.status_code == 200


def test_admin_password_reset_accepts_strong_password(
    client,
    db_session: Session,
) -> None:
    admin = create_user(db_session, "root_admin", role="admin")
    user = create_user(db_session, "reset_user", password="password123")

    response = client.put(
        f"/api/users/{user.id}/password",
        json={"new_password": "newpass123"},
        headers=auth_headers(admin),
    )

    db_session.refresh(user)
    assert response.status_code == 200
    assert verify_password("newpass123", user.password_hash)
