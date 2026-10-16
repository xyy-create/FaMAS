from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.document import Document
from app.models.processing_job import ProcessingJob
from app.services.storage_paths import knowledge_graph_run_artifacts_dir

from conftest import auth_headers, create_knowledge_base, create_user


def test_graph_overrides_hide_nodes_and_dependent_edges(client, db_session: Session) -> None:
    user = create_user(db_session, "kg_override_user")
    knowledge_base = create_knowledge_base(db_session, owner_user_id=user.id)
    document = _create_graph_document(db_session, knowledge_base.id, user.id)
    _write_graph_artifacts(document.id, _create_success_job(db_session, document.id).id)

    response = client.put(
        "/api/knowledge-graph/overrides/node/node_b",
        headers=auth_headers(user),
        json={
            "knowledge_base_id": knowledge_base.id,
            "document_id": document.id,
            "is_hidden": True,
            "patch": {"title": "隐藏节点"},
        },
    )
    assert response.status_code == 200
    assert response.json()["is_hidden"] is True

    nodes = client.get(
        f"/api/knowledge-graph/zh/merged_nodes.json?knowledge_base_id={knowledge_base.id}&document_id={document.id}",
        headers=auth_headers(user),
    ).json()["nodes"]
    edges = client.get(
        f"/api/knowledge-graph/zh/merged_edges.json?knowledge_base_id={knowledge_base.id}&document_id={document.id}",
        headers=auth_headers(user),
    ).json()["edges"]
    triples = client.get(
        f"/api/knowledge-graph/zh/triples.json?knowledge_base_id={knowledge_base.id}&document_id={document.id}",
        headers=auth_headers(user),
    ).json()["triples"]
    summary = client.get(
        f"/api/knowledge-graph/summary?knowledge_base_id={knowledge_base.id}&document_id={document.id}",
        headers=auth_headers(user),
    ).json()

    assert [node["node_id"] for node in nodes] == ["node_a"]
    assert edges == []
    assert triples == []
    assert summary["counts"] == {"nodes": 1, "edges": 0, "triples": 0}


def test_graph_edge_override_updates_edges_and_triples(client, db_session: Session) -> None:
    user = create_user(db_session, "kg_edge_override_user")
    knowledge_base = create_knowledge_base(db_session, owner_user_id=user.id)
    document = _create_graph_document(db_session, knowledge_base.id, user.id)
    _write_graph_artifacts(document.id, _create_success_job(db_session, document.id).id)

    response = client.put(
        "/api/knowledge-graph/overrides/edge/edge_a_b",
        headers=auth_headers(user),
        json={
            "knowledge_base_id": knowledge_base.id,
            "document_id": document.id,
            "patch": {
                "predicate": "explains",
                "relation_description": "用户确认后的关系说明",
                "importance": "重点",
                "image_paths": ["images/page001_img001.jpg"],
            },
        },
    )
    assert response.status_code == 200

    edge = client.get(
        f"/api/knowledge-graph/zh/merged_edges.json?knowledge_base_id={knowledge_base.id}&document_id={document.id}",
        headers=auth_headers(user),
    ).json()["edges"][0]
    triple = client.get(
        f"/api/knowledge-graph/zh/triples.json?knowledge_base_id={knowledge_base.id}&document_id={document.id}",
        headers=auth_headers(user),
    ).json()["triples"][0]

    assert edge["predicate"] == "explains"
    assert edge["properties"]["rationale"] == "用户确认后的关系说明"
    assert edge["properties"]["重要程度"] == "重点"
    assert edge["properties"]["figures"][0]["image_path"] == "images/page001_img001.jpg"
    assert triple["predicate"] == "explains"


def test_graph_override_queues_refresh_job_and_returns_job_id(client, db_session: Session, monkeypatch) -> None:
    monkeypatch.setattr(settings, "pipeline_worker_enabled", True)
    user = create_user(db_session, "kg_refresh_user")
    knowledge_base = create_knowledge_base(db_session, owner_user_id=user.id)
    document = _create_graph_document(db_session, knowledge_base.id, user.id)

    response = client.put(
        "/api/knowledge-graph/overrides/node/node_a",
        headers=auth_headers(user),
        json={
            "knowledge_base_id": knowledge_base.id,
            "document_id": document.id,
            "is_hidden": False,
            "source_context_ids": ["ctx_a", "ctx_b"],
            "patch": {"title": "节点 A 修正"},
        },
    )

    assert response.status_code == 200
    assert response.headers["X-Graph-Refresh-Job-Id"]
    db_session.expire_all()
    job = db_session.scalar(
        select(ProcessingJob).where(
            ProcessingJob.document_id == document.id,
            ProcessingJob.stage == "build_graph",
            ProcessingJob.status == "pending",
        )
    )
    assert job is not None
    assert json.loads(job.payload_json)["source_context_ids"] == ["ctx_a", "ctx_b"]


def test_graph_override_can_add_user_nodes_and_edges(client, db_session: Session) -> None:
    user = create_user(db_session, "kg_add_override_user")
    knowledge_base = create_knowledge_base(db_session, owner_user_id=user.id)
    document = _create_graph_document(db_session, knowledge_base.id, user.id)
    _write_graph_artifacts(document.id, _create_success_job(db_session, document.id).id)

    node_response = client.post(
        "/api/knowledge-graph/overrides/nodes",
        headers=auth_headers(user),
        json={
            "knowledge_base_id": knowledge_base.id,
            "document_id": document.id,
            "title": "用户新增知识点",
            "label": "KnowledgePoint",
            "description": "由用户补充的说明",
            "user_evidence": "课堂补充材料",
            "evidence_confidence": "已确认",
        },
    )
    assert node_response.status_code == 200
    node_id = node_response.json()["item_id"]
    assert node_response.json()["is_new"] is True

    edge_response = client.post(
        "/api/knowledge-graph/overrides/edges",
        headers=auth_headers(user),
        json={
            "knowledge_base_id": knowledge_base.id,
            "document_id": document.id,
            "source_node_id": "node_a",
            "target_node_id": node_id,
            "predicate": "explains",
            "relation_description": "用户新增关系",
            "user_evidence": "课堂补充材料",
        },
    )
    assert edge_response.status_code == 200
    edge_id = edge_response.json()["item_id"]

    nodes = client.get(
        f"/api/knowledge-graph/zh/merged_nodes.json?knowledge_base_id={knowledge_base.id}&document_id={document.id}",
        headers=auth_headers(user),
    ).json()["nodes"]
    edges = client.get(
        f"/api/knowledge-graph/zh/merged_edges.json?knowledge_base_id={knowledge_base.id}&document_id={document.id}",
        headers=auth_headers(user),
    ).json()["edges"]
    triples = client.get(
        f"/api/knowledge-graph/zh/triples.json?knowledge_base_id={knowledge_base.id}&document_id={document.id}",
        headers=auth_headers(user),
    ).json()["triples"]

    added_node = next(node for node in nodes if node["node_id"] == node_id)
    added_edge = next(edge for edge in edges if edge["edge_id"] == edge_id)
    added_triple = next(triple for triple in triples if triple["edge_id"] == edge_id)

    assert added_node["properties"]["title"] == "用户新增知识点"
    assert added_node["properties"]["web_created"] is True
    assert added_edge["target_node_id"] == node_id
    assert added_edge["properties"]["web_created"] is True
    assert added_triple["subject_node_id"] == "node_a"
    assert added_triple["object_node_id"] == node_id


def test_graph_override_rejects_inaccessible_document(client, db_session: Session) -> None:
    owner = create_user(db_session, "kg_owner")
    other_user = create_user(db_session, "kg_other")
    knowledge_base = create_knowledge_base(db_session, owner_user_id=owner.id)
    document = _create_graph_document(db_session, knowledge_base.id, owner.id)

    response = client.put(
        "/api/knowledge-graph/overrides/node/node_a",
        headers=auth_headers(other_user),
        json={
            "knowledge_base_id": knowledge_base.id,
            "document_id": document.id,
            "patch": {"title": "不应成功"},
        },
    )

    assert response.status_code == 404


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
                    {"node_id": "node_a", "label": "Concept", "properties": {"title": "节点 A"}},
                    {"node_id": "node_b", "label": "Concept", "properties": {"title": "节点 B"}},
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
                        "properties": {},
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
