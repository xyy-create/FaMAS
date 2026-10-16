from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.document import Document

from conftest import auth_headers, create_knowledge_base, create_user


def test_users_only_list_system_and_own_knowledge_bases(client, db_session: Session) -> None:
    admin = create_user(db_session, "admin", role="admin")
    alice = create_user(db_session, "alice")
    bob = create_user(db_session, "bob")
    create_knowledge_base(db_session, "System KB")
    create_knowledge_base(db_session, "Alice KB", owner_user_id=alice.id)
    create_knowledge_base(db_session, "Bob KB", owner_user_id=bob.id)

    alice_response = client.get("/api/knowledge-bases", headers=auth_headers(alice))
    admin_response = client.get("/api/knowledge-bases", headers=auth_headers(admin))

    assert alice_response.status_code == 200
    assert {item["name"] for item in alice_response.json()} == {"System KB", "Alice KB"}
    assert admin_response.status_code == 200
    assert {item["name"] for item in admin_response.json()} == {"System KB", "Alice KB", "Bob KB"}


def test_user_can_create_and_rename_own_knowledge_base(client, db_session: Session) -> None:
    alice = create_user(db_session, "alice")

    create_response = client.post(
        "/api/knowledge-bases",
        json={"name": "History Notes"},
        headers=auth_headers(alice),
    )
    assert create_response.status_code == 200
    assert create_response.json()["owner_user_id"] == alice.id
    assert create_response.json()["document_count"] == 0

    duplicate_response = client.post(
        "/api/knowledge-bases",
        json={"name": "History Notes"},
        headers=auth_headers(alice),
    )
    assert duplicate_response.status_code == 409

    update_response = client.put(
        f"/api/knowledge-bases/{create_response.json()['id']}",
        json={"name": "Ancient History"},
        headers=auth_headers(alice),
    )
    assert update_response.status_code == 200
    assert update_response.json()["name"] == "Ancient History"


def test_user_cannot_manage_another_users_knowledge_base(client, db_session: Session) -> None:
    alice = create_user(db_session, "alice")
    bob = create_user(db_session, "bob")
    bob_kb = create_knowledge_base(db_session, "Bob Private KB", owner_user_id=bob.id)

    update_response = client.put(
        f"/api/knowledge-bases/{bob_kb.id}",
        json={"name": "Taken"},
        headers=auth_headers(alice),
    )
    delete_response = client.delete(
        f"/api/knowledge-bases/{bob_kb.id}",
        headers=auth_headers(alice),
    )

    assert update_response.status_code == 404
    assert delete_response.status_code == 404


def test_deleting_own_knowledge_base_soft_deletes_its_documents(client, db_session: Session) -> None:
    alice = create_user(db_session, "alice")
    knowledge_base = create_knowledge_base(db_session, "Alice KB", owner_user_id=alice.id)
    document = Document(
        knowledge_base_id=knowledge_base.id,
        owner_user_id=alice.id,
        filename="alice.pdf",
        original_path="alice.pdf",
        file_size_bytes=100,
        status="uploaded",
        is_deleted=False,
    )
    db_session.add(document)
    db_session.commit()

    response = client.delete(
        f"/api/knowledge-bases/{knowledge_base.id}",
        headers=auth_headers(alice),
    )

    assert response.status_code == 200
    db_session.refresh(document)
    db_session.refresh(knowledge_base)
    assert knowledge_base.is_deleted is True
    assert document.is_deleted is True
    assert document.status == "deleted"
