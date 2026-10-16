from __future__ import annotations

import time
from typing import Any

from sqlalchemy.orm import Session

from app.api.routes.retrieval import _stream_llm_chunks_with_heartbeat
from app.models.document import Document
from conftest import auth_headers, create_knowledge_base, create_user


def test_search_mode_uses_local_graph_without_model_call(client, db_session: Session, monkeypatch) -> None:
    user = create_user(db_session, "alice")
    knowledge_base = create_knowledge_base(db_session)
    _patch_graph(monkeypatch)

    def fail_model_call(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("Search mode should not call the model API.")

    monkeypatch.setattr("app.api.routes.retrieval.chat_completion_from_settings", fail_model_call)

    response = client.post(
        "/api/retrieval/query",
        json={
            "mode": "search",
            "query": "photosynthesis",
            "knowledge_base_id": knowledge_base.id,
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == ""
    assert payload["match_summary"]["node_matches"] == 1
    assert payload["match_summary"]["triple_matches"] == 1


def test_search_mode_can_limit_rag_scope_to_selected_documents(client, db_session: Session, monkeypatch) -> None:
    user = create_user(db_session, "alice")
    knowledge_base = create_knowledge_base(db_session)
    first = _create_document(db_session, knowledge_base.id, user.id, "first.pdf")
    second = _create_document(db_session, knowledge_base.id, user.id, "second.pdf")
    seen_artifact_document_ids: list[int | None] = []

    def fake_summary(*, document_id: int | None, **_kwargs: Any) -> dict[str, Any]:
        return {
            "source": "processed",
            "counts": {"nodes": 1, "edges": 0, "triples": 0},
            "documents": [{"id": document_id, "filename": f"{document_id}.pdf", "status": "graph_ready"}],
            "processed_run_ids": [f"run_{document_id}"],
        }

    def fake_artifact(*, artifact_name: str, document_id: int | None, **_kwargs: Any) -> dict[str, Any]:
        seen_artifact_document_ids.append(document_id)
        if artifact_name == "merged_nodes.json":
            return {
                "schema_version": "kg.merged_nodes.v1",
                "nodes": [
                    {
                        "node_id": f"n{document_id}",
                        "label": "Concept",
                        "properties": {"title": "Photosynthesis"},
                    }
                ],
            }
        if artifact_name == "merged_edges.json":
            return {"schema_version": "kg.merged_edges.v1", "edges": []}
        if artifact_name == "triples.json":
            return {"schema_version": "kg.triples.v1", "triples": []}
        return {}

    monkeypatch.setattr("app.api.routes.retrieval.graph_summary", fake_summary)
    monkeypatch.setattr("app.api.routes.retrieval.graph_artifact", fake_artifact)

    response = client.post(
        "/api/retrieval/query",
        json={
            "mode": "search",
            "query": "photosynthesis",
            "knowledge_base_id": knowledge_base.id,
            "document_ids": [first.id, second.id],
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    assert set(seen_artifact_document_ids) == {first.id, second.id}
    assert response.json()["match_summary"]["source_documents"] == 2


def test_qa_mode_requires_saved_provider_key(client, db_session: Session, monkeypatch) -> None:
    user = create_user(db_session, "alice")
    knowledge_base = create_knowledge_base(db_session)
    _patch_graph(monkeypatch)

    response = client.post(
        "/api/retrieval/query",
        json={
            "mode": "qa",
            "provider": "dashscope",
            "query": "What is photosynthesis?",
            "knowledge_base_id": knowledge_base.id,
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 400
    assert "API settings" in response.json()["detail"]


def test_qa_mode_returns_model_answer_with_graph_context(client, db_session: Session, monkeypatch) -> None:
    user = create_user(db_session, "alice")
    knowledge_base = create_knowledge_base(db_session)
    _patch_graph(monkeypatch)
    captured: dict[str, Any] = {}

    def fake_model_call(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "content": "Photosynthesis converts light energy into chemical energy.",
            "provider": kwargs["provider"],
            "model_name": "qwen-plus",
            "key_source": "user",
        }

    monkeypatch.setattr("app.api.routes.retrieval.chat_completion_from_settings", fake_model_call)

    response = client.post(
        "/api/retrieval/query",
        json={
            "mode": "qa",
            "provider": "dashscope",
            "query": "What is photosynthesis?",
            "knowledge_base_id": knowledge_base.id,
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer_source"] == "llm"
    assert payload["answer"] == "Photosynthesis converts light energy into chemical energy."
    assert payload["model"]["provider"] == "dashscope"
    assert "photosynthesis" in captured["messages"][1]["content"].lower()


def test_strict_stream_returns_local_message_when_evidence_is_missing(client, db_session: Session, monkeypatch) -> None:
    user = create_user(db_session, "alice")
    knowledge_base = create_knowledge_base(db_session)
    _patch_graph(monkeypatch)

    def fail_stream_call(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("Strict QA with no evidence should not call the model API.")

    monkeypatch.setattr("app.api.routes.retrieval.stream_chat_completion_from_settings", fail_stream_call)

    response = client.post(
        "/api/retrieval/qa/stream",
        json={
            "query": "unrelated topic",
            "knowledge_base_id": knowledge_base.id,
            "answer_mode": "strict",
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert events[0] == ("status", {"phase": "retrieving", "message": "正在检索知识图谱依据..."})
    assert events[1][0] == "citations"
    assert events[2][0] == "metadata"
    assert events[3][0] == "status"
    assert events[4][0] == "delta"
    assert "当前知识图谱中没有足够信息" in "".join(
        data["content"] for event, data in events if event == "delta"
    )
    assert events[-1][0] == "done"
    assert events[-1][1]["answer_source"] == "local"


def test_free_stream_calls_model_with_controls_and_image_citations(client, db_session: Session, monkeypatch) -> None:
    user = create_user(db_session, "alice")
    knowledge_base = create_knowledge_base(db_session)
    _patch_graph(monkeypatch)
    captured: dict[str, Any] = {}

    def fake_stream_call(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "provider": kwargs["provider"],
            "model_name": "qwen-plus",
            "key_source": "user",
            "chunks": iter(["这是", "流式回答。"]),
        }

    monkeypatch.setattr("app.api.routes.retrieval.stream_chat_completion_from_settings", fake_stream_call)

    response = client.post(
        "/api/retrieval/qa/stream",
        json={
            "query": "What is photosynthesis?",
            "knowledge_base_id": knowledge_base.id,
            "answer_mode": "free",
            "answer_style": "exam",
            "model_name": "qwen-turbo",
            "temperature": 0.6,
            "max_tokens": 900,
            "history_turns": 1,
            "history": [
                {"role": "user", "content": "上一问"},
                {"role": "assistant", "content": "上一答"},
            ],
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    assert events[0][0] == "status"
    citations = events[1][1]
    assert citations["images"][0]["image_path"] == "images/page001_img001.jpg"
    assert events[3][0] == "metadata"
    assert events[3][1]["model"]["model_name"] == "qwen-plus"
    delta_contents = [data["content"] for event, data in events if event == "delta"]
    assert delta_contents[0].startswith("以下回答包含模型基于通用知识的补充")
    assert len(delta_contents) == 3
    assert events[-1][0] == "done"
    assert captured["temperature"] == 0.6
    assert captured["max_tokens"] == 900
    assert captured["model_name"] == "qwen-turbo"
    assert captured["messages"][0]["content"].startswith("你是“书脉”")
    assert "[依据1]" in captured["messages"][0]["content"]
    assert "不要直接展示节点 ID" in captured["messages"][0]["content"]
    assert "不要把补充内容伪装成知识图谱原文" in captured["messages"][0]["content"]
    assert "可引用的证据索引 JSON" in captured["messages"][-1]["content"]
    assert "知识图谱依据 JSON" not in captured["messages"][-1]["content"]
    assert "依据1" in captured["messages"][-1]["content"]
    assert citations["evidence_items"][0]["ref"] == "依据1"
    assert citations["evidence_items"][0]["kind"] == "关系"
    assert "产生" in citations["evidence_items"][0]["title"]
    assert "produces" not in citations["evidence_items"][0]["title"]
    assert "node_id" not in captured["messages"][-1]["content"]
    assert "triple_id" not in captured["messages"][-1]["content"]
    assert captured["messages"][1]["content"] == "上一问"
    assert captured["messages"][2]["content"] == "上一答"


def test_free_stream_handles_greeting_as_general_chat_without_graph_context(
    client,
    db_session: Session,
    monkeypatch,
) -> None:
    user = create_user(db_session, "alice")
    knowledge_base = create_knowledge_base(db_session)
    _patch_graph(monkeypatch)
    captured: dict[str, Any] = {}

    def fake_stream_call(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {
            "provider": kwargs["provider"],
            "model_name": "qwen-plus",
            "key_source": "user",
            "chunks": iter(["你好！", "我是书脉，可以帮你解答学习问题。"]),
        }

    monkeypatch.setattr("app.api.routes.retrieval.stream_chat_completion_from_settings", fake_stream_call)

    response = client.post(
        "/api/retrieval/qa/stream",
        json={
            "query": "你好",
            "knowledge_base_id": knowledge_base.id,
            "answer_mode": "free",
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    citations = next(data for event, data in events if event == "citations")
    assert citations["uses_kg_context"] is False
    assert citations["related_nodes"] == []
    assert citations["triples"] == []
    assert "通用问答" in citations["message"]
    assert events[-1][1]["uses_kg_context"] is False

    answer = "".join(data["content"] for event, data in events if event == "delta")
    assert "以下回答包含模型基于通用知识的补充" not in answer
    system_prompt = captured["messages"][0]["content"]
    user_prompt = captured["messages"][-1]["content"]
    assert "像普通大模型一样回答" in system_prompt
    assert "知识图谱依据 JSON" not in user_prompt
    assert "node_id" not in user_prompt
    assert user_prompt == "你好"


def test_streaming_capability_question_returns_local_truthful_answer(
    client,
    db_session: Session,
    monkeypatch,
) -> None:
    user = create_user(db_session, "alice")
    knowledge_base = create_knowledge_base(db_session)
    _patch_graph(monkeypatch)

    def fail_stream_call(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("System capability questions should not be answered by the model.")

    monkeypatch.setattr("app.api.routes.retrieval.stream_chat_completion_from_settings", fail_stream_call)

    response = client.post(
        "/api/retrieval/qa/stream",
        json={
            "query": "你支持流式输出吗？",
            "knowledge_base_id": knowledge_base.id,
            "answer_mode": "free",
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    delta_contents = [data["content"] for event, data in events if event == "delta"]
    assert len(delta_contents) > 3
    answer = "".join(delta_contents)
    assert "支持流式展示" in answer
    assert "浏览器 Network" in answer
    assert events[-1][1]["answer_source"] == "local"


def test_knowledge_scope_question_returns_local_summary_without_model_call(
    client,
    db_session: Session,
    monkeypatch,
) -> None:
    user = create_user(db_session, "alice")
    knowledge_base = create_knowledge_base(db_session)
    _patch_graph(monkeypatch)

    def fail_stream_call(**_kwargs: Any) -> dict[str, Any]:
        raise AssertionError("Knowledge scope questions should be answered locally.")

    monkeypatch.setattr("app.api.routes.retrieval.stream_chat_completion_from_settings", fail_stream_call)

    response = client.post(
        "/api/retrieval/qa/stream",
        json={
            "query": "当前库中的知识范围",
            "knowledge_base_id": knowledge_base.id,
            "answer_mode": "free",
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    delta_text = "".join(data["content"] for event, data in events if event == "delta")
    assert "当前库中的知识范围" in delta_text
    assert "2 个节点" in delta_text
    assert "1 个三元组" in delta_text
    assert events[-1][1]["answer_source"] == "local"


def test_stream_persists_conversation_history_and_keeps_users_isolated(
    client,
    db_session: Session,
    monkeypatch,
) -> None:
    user = create_user(db_session, "alice")
    other_user = create_user(db_session, "bob")
    knowledge_base = create_knowledge_base(db_session)
    _patch_graph(monkeypatch)

    def fake_stream_call(**kwargs: Any) -> dict[str, Any]:
        return {
            "provider": kwargs["provider"],
            "model_name": "qwen-plus",
            "key_source": "user",
            "chunks": iter(["第一段", "第二段"]),
        }

    monkeypatch.setattr("app.api.routes.retrieval.stream_chat_completion_from_settings", fake_stream_call)

    response = client.post(
        "/api/retrieval/qa/stream",
        json={
            "query": "What is photosynthesis?",
            "knowledge_base_id": knowledge_base.id,
            "answer_mode": "free",
        },
        headers=auth_headers(user),
    )

    assert response.status_code == 200
    events = _parse_sse(response.text)
    done = events[-1][1]
    conversation_id = done["conversation_id"]
    assert done["assistant_message_id"]

    list_response = client.get(
        f"/api/retrieval/conversations?knowledge_base_id={knowledge_base.id}",
        headers=auth_headers(user),
    )
    assert list_response.status_code == 200
    conversations = list_response.json()
    assert conversations[0]["id"] == conversation_id
    assert conversations[0]["message_count"] == 2
    assert conversations[0]["last_message_preview"].endswith("第一段第二段")

    detail_response = client.get(
        f"/api/retrieval/conversations/{conversation_id}",
        headers=auth_headers(user),
    )
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
    assert detail["messages"][0]["content"] == "What is photosynthesis?"
    assert detail["messages"][1]["content"].endswith("第一段第二段")
    assert detail["messages"][1]["citations"]["images"][0]["image_path"] == "images/page001_img001.jpg"

    forbidden_response = client.get(
        f"/api/retrieval/conversations/{conversation_id}",
        headers=auth_headers(other_user),
    )
    assert forbidden_response.status_code == 404

    captured_follow_up: dict[str, Any] = {}

    def fake_follow_up_call(**kwargs: Any) -> dict[str, Any]:
        captured_follow_up.update(kwargs)
        return {
            "provider": kwargs["provider"],
            "model_name": "qwen-plus",
            "key_source": "user",
            "chunks": iter(["追问回答"]),
        }

    monkeypatch.setattr("app.api.routes.retrieval.stream_chat_completion_from_settings", fake_follow_up_call)
    follow_up_response = client.post(
        "/api/retrieval/qa/stream",
        json={
            "query": "那上一问是什么？",
            "knowledge_base_id": knowledge_base.id,
            "conversation_id": conversation_id,
            "answer_mode": "free",
            "history_turns": 1,
        },
        headers=auth_headers(user),
    )

    assert follow_up_response.status_code == 200
    llm_messages = captured_follow_up["messages"]
    assert {"role": "user", "content": "What is photosynthesis?"} in llm_messages
    assert {"role": "assistant", "content": "第一段第二段"} in llm_messages
    assert llm_messages[-1] == {"role": "user", "content": "那上一问是什么？"}


def test_llm_stream_heartbeat_arrives_before_slow_delta() -> None:
    def slow_chunks() -> Any:
        time.sleep(0.03)
        yield "晚到的回答"

    events = list(_stream_llm_chunks_with_heartbeat(slow_chunks(), heartbeat_seconds=0.005))

    assert events[0][0] == "status"
    assert events[0][1]["phase"] == "waiting_model"
    assert events[-1] == ("delta", {"content": "晚到的回答"})


def test_llm_stream_splits_large_upstream_chunk() -> None:
    events = list(
        _stream_llm_chunks_with_heartbeat(
            iter(["这是一段上游一次性返回的较长回答，后端需要切成多个小片段推给浏览器。"]),
            heartbeat_seconds=0.1,
        )
    )

    deltas = [data["content"] for event, data in events if event == "delta"]
    assert len(deltas) > 1
    assert "".join(deltas).startswith("这是一段上游一次性返回")


def _patch_graph(monkeypatch) -> None:
    def fake_summary(**_kwargs: Any) -> dict[str, Any]:
        return {
            "source": "processed",
            "counts": {"nodes": 2, "edges": 1, "triples": 1},
        }

    def fake_artifact(*, artifact_name: str, **_kwargs: Any) -> dict[str, Any]:
        if artifact_name == "merged_nodes.json":
            return {
                "nodes": [
                    {
                        "node_id": "n1",
                        "label": "Concept",
                        "properties": {
                            "title": "Photosynthesis",
                            "definition": "Plants convert light energy into chemical energy.",
                            "evidence": [{"quote_or_summary": "Photosynthesis uses light."}],
                            "figures": [
                                {
                                    "figure_id": "fig1",
                                    "image_path": "images/page001_img001.jpg",
                                    "description": "A leaf diagram showing photosynthesis.",
                                }
                            ],
                        },
                    },
                    {
                        "node_id": "n2",
                        "label": "Concept",
                        "properties": {"title": "Glucose"},
                    },
                ]
            }
        if artifact_name == "merged_edges.json":
            return {
                "edges": [
                    {
                        "edge_id": "e1",
                        "properties": {
                            "relation_label": "produces",
                            "rationale": "Photosynthesis produces glucose.",
                        },
                    }
                ]
            }
        if artifact_name == "triples.json":
            return {
                "triples": [
                    {
                        "triple_id": "t1",
                        "subject_node_id": "n1",
                        "predicate": "produces",
                        "object_node_id": "n2",
                        "edge_id": "e1",
                        "evidence": [{"quote_or_summary": "Photosynthesis produces glucose."}],
                    }
                ]
            }
        return {}

    monkeypatch.setattr("app.api.routes.retrieval.graph_summary", fake_summary)
    monkeypatch.setattr("app.api.routes.retrieval.graph_artifact", fake_artifact)


def _create_document(db: Session, knowledge_base_id: int, owner_user_id: int, filename: str) -> Document:
    document = Document(
        knowledge_base_id=knowledge_base_id,
        owner_user_id=owner_user_id,
        filename=filename,
        original_path=f"/tmp/{filename}",
        file_size_bytes=128,
        status="graph_ready",
        is_deleted=False,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


def _parse_sse(text: str) -> list[tuple[str, dict[str, Any]]]:
    events: list[tuple[str, dict[str, Any]]] = []
    event_name = ""
    event_data = ""
    for line in text.splitlines():
        if line.startswith("event:"):
            event_name = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            event_data = line.removeprefix("data:").strip()
        elif not line and event_name:
            events.append((event_name, json_loads(event_data)))
            event_name = ""
            event_data = ""
    if event_name:
        events.append((event_name, json_loads(event_data)))
    return events


def json_loads(value: str) -> dict[str, Any]:
    import json

    data = json.loads(value)
    assert isinstance(data, dict)
    return data
