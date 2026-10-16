from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.core.security import _create_legacy_access_token
from app.core.security import create_access_token
from app.core.config import settings
from app.models.document import Document
from app.models.processing_job import ProcessingJob
from app.models.user import User

from conftest import auth_headers, create_knowledge_base, create_user


def test_registration_approval_blocks_login_until_user_is_approved(client, db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "registration_mode", "approval")

    response = client.post(
        "/api/auth/register",
        json={"username": "pending_user", "password": "password123"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "pending"

    login_response = client.post(
        "/api/auth/login",
        json={"username": "pending_user", "password": "password123"},
    )
    assert login_response.status_code == 403

    user = db_session.query(User).filter_by(username="pending_user").one()
    user.is_active = True
    user.approval_status = "approved"
    db_session.commit()

    approved_login = client.post(
        "/api/auth/login",
        json={"username": "pending_user", "password": "password123"},
    )
    assert approved_login.status_code == 200
    assert approved_login.json()["access_token"]


def test_login_issues_jwt_and_me_accepts_it(client, db_session: Session) -> None:
    user = create_user(db_session, "jwt_user", password="password123")

    login_response = client.post(
        "/api/auth/login",
        json={"username": user.username, "password": "password123"},
    )

    assert login_response.status_code == 200
    token = login_response.json()["access_token"]
    assert token.count(".") == 2

    me_response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_response.status_code == 200
    assert me_response.json()["username"] == user.username


def test_login_sets_cookie_and_me_accepts_cookie_auth(client, db_session: Session) -> None:
    create_user(db_session, "cookie_user", password="password123")

    login_response = client.post(
        "/api/auth/login",
        json={"username": "cookie_user", "password": "password123"},
    )

    assert login_response.status_code == 200
    assert login_response.cookies.get("famas_access_token")

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 200
    assert me_response.json()["username"] == "cookie_user"


def test_logout_clears_cookie(client, db_session: Session) -> None:
    create_user(db_session, "logout_user", password="password123")

    login_response = client.post(
        "/api/auth/login",
        json={"username": "logout_user", "password": "password123"},
    )
    assert login_response.status_code == 200

    logout_response = client.post("/api/auth/logout")
    assert logout_response.status_code == 200

    me_response = client.get("/api/auth/me")
    assert me_response.status_code == 401


def test_legacy_access_token_is_still_accepted(client, db_session: Session) -> None:
    user = create_user(db_session, "legacy_token_user")
    token = _create_legacy_access_token(
        str(user.id),
        secret_key=settings.secret_key,
        expires_in_seconds=3600,
    )

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["username"] == user.username


def test_document_list_is_scoped_to_current_user_for_non_admin(client, db_session: Session) -> None:
    admin = create_user(db_session, "admin", role="admin")
    alice = create_user(db_session, "alice")
    bob = create_user(db_session, "bob")
    knowledge_base = create_knowledge_base(db_session, owner_user_id=alice.id)
    _create_document(db_session, knowledge_base.id, alice.id, "alice.pdf")
    _create_document(db_session, knowledge_base.id, bob.id, "bob.pdf")

    alice_response = client.get(
        f"/api/documents?knowledge_base_id={knowledge_base.id}",
        headers=auth_headers(alice),
    )
    admin_response = client.get(
        f"/api/documents?knowledge_base_id={knowledge_base.id}",
        headers=auth_headers(admin),
    )

    assert alice_response.status_code == 200
    assert [item["filename"] for item in alice_response.json()] == ["alice.pdf"]
    assert admin_response.status_code == 200
    assert {item["filename"] for item in admin_response.json()} == {"alice.pdf", "bob.pdf"}


def test_user_cannot_access_or_delete_another_users_document(client, db_session: Session) -> None:
    alice = create_user(db_session, "alice")
    bob = create_user(db_session, "bob")
    knowledge_base = create_knowledge_base(db_session, owner_user_id=bob.id)
    bob_document = _create_document(db_session, knowledge_base.id, bob.id, "bob.pdf")
    db_session.add(
        ProcessingJob(
            document_id=bob_document.id,
            stage="upload",
            status="success",
            log_path="",
            error_message="",
        )
    )
    db_session.commit()

    jobs_response = client.get(
        f"/api/documents/{bob_document.id}/jobs",
        headers=auth_headers(alice),
    )
    delete_response = client.delete(
        f"/api/documents/{bob_document.id}",
        headers=auth_headers(alice),
    )

    db_session.refresh(bob_document)
    assert jobs_response.status_code == 404
    assert delete_response.status_code == 404
    assert bob_document.is_deleted is False


def test_public_knowledge_base_documents_are_visible_but_not_modifiable_by_other_users(
    client,
    db_session: Session,
) -> None:
    alice = create_user(db_session, "alice")
    bob = create_user(db_session, "bob")
    knowledge_base = create_knowledge_base(db_session)
    document = _create_document(db_session, knowledge_base.id, alice.id, "shared.pdf")

    list_response = client.get(
        f"/api/documents?knowledge_base_id={knowledge_base.id}",
        headers=auth_headers(bob),
    )
    delete_response = client.delete(
        f"/api/documents/{document.id}",
        headers=auth_headers(bob),
    )

    assert list_response.status_code == 200
    assert [item["filename"] for item in list_response.json()] == ["shared.pdf"]
    assert delete_response.status_code == 404
    db_session.refresh(document)
    assert document.is_deleted is False


def test_user_can_batch_delete_own_documents(client, db_session: Session) -> None:
    alice = create_user(db_session, "alice")
    knowledge_base = create_knowledge_base(db_session)
    first = _create_document(db_session, knowledge_base.id, alice.id, "first.pdf")
    second = _create_document(db_session, knowledge_base.id, alice.id, "second.pdf")

    response = client.post(
        "/api/documents/batch-delete",
        json={"document_ids": [first.id, second.id]},
        headers=auth_headers(alice),
    )

    db_session.refresh(first)
    db_session.refresh(second)
    assert response.status_code == 200
    assert response.json()["deleted_count"] == 2
    assert set(response.json()["deleted_ids"]) == {first.id, second.id}
    assert first.is_deleted is True
    assert second.is_deleted is True
    assert first.status == "deleted"
    assert second.status == "deleted"

    list_response = client.get(
        f"/api/documents?knowledge_base_id={knowledge_base.id}",
        headers=auth_headers(alice),
    )
    assert list_response.status_code == 200
    assert list_response.json() == []


def test_batch_delete_rejects_documents_outside_user_scope(client, db_session: Session) -> None:
    alice = create_user(db_session, "alice")
    bob = create_user(db_session, "bob")
    knowledge_base = create_knowledge_base(db_session)
    alice_document = _create_document(db_session, knowledge_base.id, alice.id, "alice.pdf")
    bob_document = _create_document(db_session, knowledge_base.id, bob.id, "bob.pdf")

    response = client.post(
        "/api/documents/batch-delete",
        json={"document_ids": [alice_document.id, bob_document.id]},
        headers=auth_headers(alice),
    )

    db_session.refresh(alice_document)
    db_session.refresh(bob_document)
    assert response.status_code == 404
    assert alice_document.is_deleted is False
    assert bob_document.is_deleted is False


def test_knowledge_graph_image_serves_processed_image_with_query_token(
    client,
    db_session: Session,
    runtime_dir: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "project_dir", runtime_dir)
    monkeypatch.setattr(settings, "storage_dir", runtime_dir / "web" / "storage")
    alice = create_user(db_session, "alice")
    knowledge_base = create_knowledge_base(db_session)
    document = _create_document(db_session, knowledge_base.id, alice.id, "alice.pdf")
    job = ProcessingJob(
        document_id=document.id,
        stage="build_graph",
        status="success",
        log_path="",
        error_message="",
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)

    run_id = f"web_doc_{document.id}_{job.id}"
    _write_graph_artifacts(runtime_dir, run_id)
    image_dir = (
        runtime_dir
        / "web"
        / "storage"
        / "knowledge_graph"
        / "runs"
        / run_id
        / "images"
    )
    image_dir.mkdir(parents=True)
    image_bytes = b"\xff\xd8\xff\xe0test-image\xff\xd9"
    (image_dir / "page001_img001.jpg").write_bytes(image_bytes)
    token = create_access_token(
        str(alice.id),
        secret_key=settings.secret_key,
        expires_in_seconds=3600,
        token_version=alice.token_version,
    )

    response = client.get(
        "/api/knowledge-graph/image",
        params={
            "knowledge_base_id": knowledge_base.id,
            "image_path": "images/page001_img001.jpg",
            "access_token": token,
        },
    )

    assert response.status_code == 200
    assert response.content == image_bytes


def _create_document(db: Session, knowledge_base_id: int, owner_user_id: int, filename: str) -> Document:
    document = Document(
        knowledge_base_id=knowledge_base_id,
        owner_user_id=owner_user_id,
        filename=filename,
        original_path=f"/tmp/{filename}",
        file_size_bytes=128,
        status="uploaded",
        is_deleted=False,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def _write_graph_artifacts(project_dir: Path, run_id: str) -> None:
    output_dir = (
        project_dir
        / "web"
        / "storage"
        / "knowledge_graph"
        / "runs"
        / run_id
        / "standard_outputs"
    )
    output_dir.mkdir(parents=True)
    (output_dir / "merged_nodes.json").write_text(
        '{"schema_version":"kg.merged_nodes.v1","nodes":[]}',
        encoding="utf-8",
    )
    (output_dir / "merged_edges.json").write_text(
        '{"schema_version":"kg.merged_edges.v1","edges":[]}',
        encoding="utf-8",
    )
    (output_dir / "triples.json").write_text(
        '{"schema_version":"kg.triples.v1","triples":[]}',
        encoding="utf-8",
    )
