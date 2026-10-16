from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.processing_job import ProcessingJob
from app.services.storage_paths import knowledge_graph_run_artifacts_dir

from conftest import auth_headers, create_knowledge_base, create_user


def test_graph_annotations_are_user_scoped_and_merged_into_artifacts(client, db_session: Session) -> None:
    user = create_user(db_session, "kg_annotation_user")
    other_user = create_user(db_session, "kg_annotation_other")
    knowledge_base = create_knowledge_base(db_session, owner_user_id=user.id)
    document = _create_graph_document(db_session, knowledge_base.id, user.id)
    _write_graph_artifacts(document.id, _create_success_job(db_session, document.id).id)

    response = client.put(
        "/api/knowledge-graph/annotations/node/node_a",
        headers=auth_headers(user),
        json={
            "knowledge_base_id": knowledge_base.id,
            "document_id": document.id,
            "tags": ["重点", "适合问答引用", "unknown"],
            "note": "课堂讲解时优先使用",
        },
    )
    assert response.status_code == 200
    assert response.json()["tags"] == ["重点", "适合问答引用"]

    other_response = client.get(
        f"/api/knowledge-graph/annotations?knowledge_base_id={knowledge_base.id}&document_id={document.id}",
        headers=auth_headers(other_user),
    )
    assert other_response.status_code == 404

    nodes = client.get(
        f"/api/knowledge-graph/zh/merged_nodes.json?knowledge_base_id={knowledge_base.id}&document_id={document.id}",
        headers=auth_headers(user),
    ).json()["nodes"]

    annotation = nodes[0]["properties"]["web_annotations"]
    assert annotation["tags"] == ["重点", "适合问答引用"]
    assert annotation["note"] == "课堂讲解时优先使用"
    assert nodes[0]["properties"]["web_source_document_name"] == document.filename


def test_graph_image_annotations_are_merged_into_figures(client, db_session: Session) -> None:
    user = create_user(db_session, "kg_image_annotation_user")
    knowledge_base = create_knowledge_base(db_session, owner_user_id=user.id)
    document = _create_graph_document(db_session, knowledge_base.id, user.id)
    _write_graph_artifacts(document.id, _create_success_job(db_session, document.id).id)

    response = client.put(
        "/api/knowledge-graph/annotations/image/images/page001_img001.jpg",
        headers=auth_headers(user),
        json={
            "knowledge_base_id": knowledge_base.id,
            "document_id": document.id,
            "tags": ["图片证据", "已确认"],
            "note": "图像内容已复核",
        },
    )
    assert response.status_code == 200

    nodes = client.get(
        f"/api/knowledge-graph/zh/merged_nodes.json?knowledge_base_id={knowledge_base.id}&document_id={document.id}",
        headers=auth_headers(user),
    ).json()["nodes"]

    figure_annotation = nodes[0]["properties"]["figures"][0]["web_annotations"]
    assert figure_annotation["tags"] == ["图片证据", "已确认"]
    assert figure_annotation["note"] == "图像内容已复核"


def test_error_extraction_annotation_excludes_item_from_retrieval(client, db_session: Session) -> None:
    user = create_user(db_session, "kg_annotation_retrieval_user")
    knowledge_base = create_knowledge_base(db_session, owner_user_id=user.id)
    document = _create_graph_document(db_session, knowledge_base.id, user.id)
    _write_graph_artifacts(document.id, _create_success_job(db_session, document.id).id)

    response = client.put(
        "/api/knowledge-graph/annotations/node/node_a",
        headers=auth_headers(user),
        json={
            "knowledge_base_id": knowledge_base.id,
            "document_id": document.id,
            "tags": ["错误抽取"],
            "note": "不应进入问答证据",
        },
    )
    assert response.status_code == 200

    query_response = client.post(
        "/api/retrieval/query",
        headers=auth_headers(user),
        json={
            "mode": "search",
            "query": "Alpha",
            "knowledge_base_id": knowledge_base.id,
            "document_id": document.id,
        },
    )

    assert query_response.status_code == 200
    payload = query_response.json()
    assert payload["related_nodes"] == []
    assert payload["triples"] == []


def test_public_annotation_templates_are_admin_managed_and_user_readable(client, db_session: Session) -> None:
    admin = create_user(db_session, "kg_template_admin", role="admin")
    user = create_user(db_session, "kg_template_user")

    forbidden = client.post(
        "/api/knowledge-graph/annotation-templates",
        headers=auth_headers(user),
        json={
            "target_kind": "node",
            "name": "课堂重点",
            "tags": ["重点"],
            "note": "普通用户不能创建公共模板",
        },
    )
    assert forbidden.status_code == 403

    created = client.post(
        "/api/knowledge-graph/annotation-templates",
        headers=auth_headers(admin),
        json={
            "target_kind": "node",
            "name": "课堂重点",
            "tags": ["重点", "适合问答引用", "unknown"],
            "note": "优先用于课堂讲解和问答引用",
        },
    )
    assert created.status_code == 200
    template_id = created.json()["id"]
    assert created.json()["tags"] == ["重点", "适合问答引用"]

    listed = client.get(
        "/api/knowledge-graph/annotation-templates?target_kind=node",
        headers=auth_headers(user),
    )
    assert listed.status_code == 200
    assert listed.json()[0]["id"] == template_id
    assert listed.json()[0]["name"] == "课堂重点"


def test_admin_user_overview_includes_owned_graph_overrides_and_annotations(client, db_session: Session) -> None:
    admin = create_user(db_session, "kg_overview_admin", role="admin")
    user = create_user(db_session, "kg_overview_user")
    knowledge_base = create_knowledge_base(db_session, owner_user_id=user.id)
    document = _create_graph_document(db_session, knowledge_base.id, user.id)
    _write_graph_artifacts(document.id, _create_success_job(db_session, document.id).id)

    override_response = client.put(
        "/api/knowledge-graph/overrides/node/node_a",
        headers=auth_headers(user),
        json={
            "knowledge_base_id": knowledge_base.id,
            "document_id": document.id,
            "is_hidden": False,
            "patch": {"title": "人工修正节点"},
        },
    )
    assert override_response.status_code == 200

    annotation_response = client.put(
        "/api/knowledge-graph/annotations/node/node_a",
        headers=auth_headers(user),
        json={
            "knowledge_base_id": knowledge_base.id,
            "document_id": document.id,
            "tags": ["重点"],
            "note": "管理员应能看到这条标注",
        },
    )
    assert annotation_response.status_code == 200

    overview_response = client.get(
        f"/api/users/{user.id}/overview",
        headers=auth_headers(admin),
    )

    assert overview_response.status_code == 200
    payload = overview_response.json()
    assert payload["graph_overrides"][0]["owner_username"] == user.username
    assert payload["graph_overrides"][0]["document_filename"] == document.filename
    assert payload["graph_overrides"][0]["summary"] == "人工修正节点"
    assert payload["graph_annotations"][0]["owner_username"] == user.username
    assert payload["graph_annotations"][0]["tags"] == ["重点"]
    assert payload["graph_annotations"][0]["note"] == "管理员应能看到这条标注"


def _create_graph_document(db: Session, knowledge_base_id: int, owner_user_id: int) -> Document:
    document = Document(
        knowledge_base_id=knowledge_base_id,
        owner_user_id=owner_user_id,
        filename="graph.pdf",
        original_path="/tmp/graph.pdf",
        file_size_bytes=128,
        status="graph_ready",
        is_deleted=False,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def _create_success_job(db: Session, document_id: int) -> ProcessingJob:
    job = ProcessingJob(
        document_id=document_id,
        stage="build_graph",
        status="success",
        log_path="",
        error_message="",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _write_graph_artifacts(document_id: int, job_id: int) -> None:
    run_id = f"web_doc_{document_id}_{job_id}"
    output_dir = knowledge_graph_run_artifacts_dir(run_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "merged_nodes.json").write_text(
        json.dumps(
            {
                "schema_version": "kg.merged_nodes.v1",
                "nodes": [
                    {
                        "node_id": "node_a",
                        "label": "Concept",
                        "properties": {
                            "title": "Alpha",
                            "description": "Alpha concept",
                            "figures": [
                                {
                                    "figure_id": "fig_a",
                                    "image_path": "images/page001_img001.jpg",
                                    "description": "Figure Alpha",
                                }
                            ],
                        },
                    },
                    {
                        "node_id": "node_b",
                        "label": "Concept",
                        "properties": {"title": "Beta", "description": "Beta concept"},
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (output_dir / "merged_edges.json").write_text(
        json.dumps(
            {
                "schema_version": "kg.merged_edges.v1",
                "edges": [
                    {
                        "edge_id": "edge_a_b",
                        "predicate": "related_to",
                        "source_node_id": "node_a",
                        "target_node_id": "node_b",
                        "properties": {"rationale": "Alpha relation"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (output_dir / "triples.json").write_text(
        json.dumps(
            {
                "schema_version": "kg.triples.v1",
                "triples": [
                    {
                        "triple_id": "triple_a_b",
                        "subject_node_id": "node_a",
                        "predicate": "related_to",
                        "object_node_id": "node_b",
                        "edge_id": "edge_a_b",
                        "evidence": [],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
