from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.document_schema_version import DocumentSchemaVersion
from app.models.processing_job import ProcessingJob
from app.api.routes import document_schemas

from conftest import auth_headers, create_knowledge_base, create_user


def test_document_schema_versions_can_be_created_edited_and_activated(client, db_session: Session) -> None:
    user = create_user(db_session, "schema_user")
    knowledge_base = create_knowledge_base(db_session, owner_user_id=user.id)
    document = _create_document(db_session, knowledge_base.id, user.id, "chemistry.pdf")

    empty_response = client.get(
        f"/api/documents/{document.id}/schemas",
        headers=auth_headers(user),
    )
    assert empty_response.status_code == 200
    assert empty_response.json() == []

    template_response = client.post(
        f"/api/documents/{document.id}/schemas/system-template",
        headers=auth_headers(user),
        json={"prompt_text": "重点关注实验和图片", "activate": True},
    )
    assert template_response.status_code == 200
    template = template_response.json()
    assert template["version_number"] == 1
    assert template["source"] == "system"
    assert template["is_active"] is True
    assert template["schema"]["schema_version"] == "shumai.document_schema.v1"
    assert any(item["display_name"] == "实验" for item in template["schema"]["node_types"])

    custom_schema = {
        "schema_version": "custom.v1",
        "node_types": [{"type": "concept", "display_name": "概念"}],
        "relation_types": [{"type": "explains", "display_name": "解释"}],
    }
    custom_response = client.post(
        f"/api/documents/{document.id}/schemas",
        headers=auth_headers(user),
        json={"title": "我的 schema", "schema": custom_schema, "activate": False},
    )
    assert custom_response.status_code == 200
    custom = custom_response.json()
    assert custom["version_number"] == 2
    assert custom["is_active"] is False

    activate_response = client.post(
        f"/api/documents/{document.id}/schemas/{custom['id']}/activate",
        headers=auth_headers(user),
    )
    assert activate_response.status_code == 200
    assert activate_response.json()["is_active"] is True

    versions_response = client.get(
        f"/api/documents/{document.id}/schemas",
        headers=auth_headers(user),
    )
    assert versions_response.status_code == 200
    versions = versions_response.json()
    assert [version["id"] for version in versions][0] == custom["id"]
    assert sum(1 for version in versions if version["is_active"]) == 1

    updated_schema = {
        "schema_version": "custom.v2",
        "node_types": [{"type": "image", "display_name": "图片"}],
        "relation_types": [{"type": "supports", "display_name": "支持"}],
    }
    update_response = client.put(
        f"/api/documents/{document.id}/schemas/{custom['id']}",
        headers=auth_headers(user),
        json={"title": "修改后的 schema", "schema": updated_schema},
    )
    assert update_response.status_code == 200
    assert update_response.json()["title"] == "修改后的 schema"
    assert update_response.json()["source"] == "user"
    assert update_response.json()["schema"]["schema_version"] == "custom.v2"


def test_document_schema_versions_are_scoped_to_document_owner(client, db_session: Session) -> None:
    alice = create_user(db_session, "schema_alice")
    bob = create_user(db_session, "schema_bob")
    knowledge_base = create_knowledge_base(db_session, owner_user_id=alice.id)
    document = _create_document(db_session, knowledge_base.id, alice.id, "alice.pdf")

    denied_response = client.get(
        f"/api/documents/{document.id}/schemas",
        headers=auth_headers(bob),
    )
    assert denied_response.status_code == 404

    create_response = client.post(
        f"/api/documents/{document.id}/schemas/system-template",
        headers=auth_headers(alice),
        json={},
    )
    assert create_response.status_code == 200
    schema_id = create_response.json()["id"]

    denied_activate = client.post(
        f"/api/documents/{document.id}/schemas/{schema_id}/activate",
        headers=auth_headers(bob),
    )
    assert denied_activate.status_code == 404

    stored_versions = list(
        db_session.scalars(select(DocumentSchemaVersion).where(DocumentSchemaVersion.document_id == document.id))
    )
    assert len(stored_versions) == 1
    assert stored_versions[0].owner_user_id == alice.id


def test_document_schema_rejects_invalid_payload(client, db_session: Session) -> None:
    user = create_user(db_session, "schema_invalid")
    knowledge_base = create_knowledge_base(db_session, owner_user_id=user.id)
    document = _create_document(db_session, knowledge_base.id, user.id, "invalid.pdf")

    response = client.post(
        f"/api/documents/{document.id}/schemas",
        headers=auth_headers(user),
        json={"title": "空 schema", "schema": {}},
    )

    assert response.status_code == 400
    assert "Schema 必须是非空 JSON 对象" in response.json()["detail"]


def test_document_schema_llm_rewrite_creates_new_version(client, db_session: Session, monkeypatch) -> None:
    user = create_user(db_session, "schema_llm")
    knowledge_base = create_knowledge_base(db_session, owner_user_id=user.id)
    document = _create_document(db_session, knowledge_base.id, user.id, "llm.pdf")
    base_schema = DocumentSchemaVersion(
        document_id=document.id,
        owner_user_id=user.id,
        version_number=1,
        title="基础 schema",
        source="user",
        prompt_text="",
        schema_json='{"schema_version":"base","node_types":[],"relation_types":[]}',
        is_active=True,
    )
    db_session.add(base_schema)
    db_session.commit()
    db_session.refresh(base_schema)

    def fake_chat_completion_from_settings(**kwargs):
        assert kwargs["provider"] == "dashscope"
        assert "强化图片" in kwargs["messages"][1]["content"]
        return {
            "content": """
            {
              "schema_version": "rewritten",
              "node_types": [{"type": "image", "display_name": "图片"}],
              "relation_types": [{"type": "supports", "display_name": "支持"}]
            }
            """,
            "provider": "dashscope",
            "model_name": "qwen-plus",
        }

    monkeypatch.setattr(
        document_schemas.llm_client,
        "chat_completion_from_settings",
        fake_chat_completion_from_settings,
    )

    response = client.post(
        f"/api/documents/{document.id}/schemas/{base_schema.id}/llm-rewrite",
        headers=auth_headers(user),
        json={"preset": "image", "instruction": "更重视图文关系", "activate": True},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["version_number"] == 2
    assert payload["source"] == "llm"
    assert payload["is_active"] is True
    assert payload["schema"]["schema_version"] == "rewritten"

    db_session.refresh(base_schema)
    assert base_schema.is_active is False


def test_create_build_graph_job_can_reference_schema_version(client, db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "pipeline_worker_enabled", True)
    user = create_user(db_session, "schema_job")
    knowledge_base = create_knowledge_base(db_session, owner_user_id=user.id)
    document = _create_document(db_session, knowledge_base.id, user.id, "job.pdf")
    schema = DocumentSchemaVersion(
        document_id=document.id,
        owner_user_id=user.id,
        version_number=1,
        title="构图 schema",
        source="user",
        prompt_text="",
        schema_json='{"schema_version":"job","node_types":[],"relation_types":[]}',
        is_active=False,
    )
    db_session.add(schema)
    db_session.commit()
    db_session.refresh(schema)

    response = client.post(
        f"/api/documents/{document.id}/build-graph",
        headers=auth_headers(user),
        json={"schema_version_id": schema.id},
    )

    assert response.status_code == 200
    assert response.json()["schema_version_id"] == schema.id


def test_parse_job_rejects_schema_version(client, db_session: Session) -> None:
    user = create_user(db_session, "schema_parse")
    knowledge_base = create_knowledge_base(db_session, owner_user_id=user.id)
    document = _create_document(db_session, knowledge_base.id, user.id, "parse.pdf")

    response = client.post(
        f"/api/documents/{document.id}/parse",
        headers=auth_headers(user),
        json={"schema_version_id": 1},
    )

    assert response.status_code == 400
    assert "解析 PDF 阶段不能指定 schema" in response.json()["detail"]


def test_create_build_graph_job_persists_source_context_ids(client, db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "pipeline_worker_enabled", True)
    user = create_user(db_session, "context_job")
    knowledge_base = create_knowledge_base(db_session, owner_user_id=user.id)
    document = _create_document(db_session, knowledge_base.id, user.id, "context.pdf")

    response = client.post(
        f"/api/documents/{document.id}/build-graph",
        headers=auth_headers(user),
        json={"source_context_ids": ["s001_ch1_s1", "  ", "s002_ch1_s2", "s001_ch1_s1"]},
    )

    assert response.status_code == 200
    job = db_session.scalar(select(ProcessingJob).where(ProcessingJob.id == response.json()["id"]))
    assert job is not None
    assert job.payload_json == '{"schema_version_id": null, "source_context_ids": ["s001_ch1_s1", "s002_ch1_s2"]}'


def test_parse_job_rejects_source_context_ids(client, db_session: Session) -> None:
    user = create_user(db_session, "parse_context")
    knowledge_base = create_knowledge_base(db_session, owner_user_id=user.id)
    document = _create_document(db_session, knowledge_base.id, user.id, "parse_context.pdf")

    response = client.post(
        f"/api/documents/{document.id}/parse",
        headers=auth_headers(user),
        json={"source_context_ids": ["s001_ch1_s1"]},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "PDF parsing jobs cannot restrict source contexts."


def _create_document(db: Session, knowledge_base_id: int, owner_user_id: int, filename: str) -> Document:
    document = Document(
        knowledge_base_id=knowledge_base_id,
        owner_user_id=owner_user_id,
        filename=filename,
        original_path=f"/tmp/{filename}",
        file_size_bytes=128,
        subject="chemistry",
        grade="high_school",
        publisher="renjiao",
        textbook="化学必修第一册",
        textbook_version="compulsory",
        status="uploaded",
        is_deleted=False,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document
