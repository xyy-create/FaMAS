from __future__ import annotations

import json
import queue
import re
import time
from collections.abc import Iterable
from threading import Thread
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.api.routes.knowledge_graph import graph_artifact, graph_summary
from app.db.session import get_db
from app.models.document import Document
from app.models.qa_conversation import QaConversation, QaMessage
from app.models.user import User
from app.models.knowledge_base import KnowledgeBase
from app.core.time import utc_now_naive
from app.services.knowledge_base_access import get_accessible_knowledge_base
from app.services.llm_client import (
    LlmClientError,
    chat_completion_from_settings,
    stream_chat_completion_from_settings,
)

router = APIRouter(prefix="/api/retrieval", tags=["retrieval"])

EvidenceLevel = Literal["sufficient", "limited", "none"]
AnswerMode = Literal["strict", "free"]
AnswerStyle = Literal["concise", "textbook", "exam", "student"]

STRICT_INSUFFICIENT_MESSAGE = (
    "当前知识图谱中没有足够信息直接回答该问题。下面是系统检索到的最接近依据，"
    "你可以尝试扩大知识库范围或补充相关 PDF。"
)
FREE_MODE_NOTICE = "以下回答包含模型基于通用知识的补充，不完全来自当前知识图谱。请结合引用依据判断。"
STREAMING_CAPABILITY_MESSAGE = (
    "书脉问答页面支持流式展示：后端使用 SSE 返回问答事件，前端会把收到的回答内容按小片段连续打印到对话框中。"
    "如果你看到答案最后一次性出现，通常不是知识图谱能力问题，而是浏览器缓存、代理缓冲、当前页面没有跟随到最新回答，"
    "或上游模型接口首个内容块返回较晚导致。请以网页实际显示和浏览器 Network 中的 `/api/retrieval/qa/stream` 事件为准。"
)


class RetrievalQuery(BaseModel):
    mode: Literal["search", "qa"] = "search"
    query: str
    knowledge_base_id: int
    document_id: int | None = None
    document_ids: list[int] = []
    limit: int = 8
    provider: Literal["dashscope", "deepseek"] = "dashscope"
    answer_mode: AnswerMode = "strict"
    answer_style: AnswerStyle = "textbook"
    temperature: float | None = None
    max_tokens: int | None = None


class QaHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class QaStreamRequest(BaseModel):
    query: str
    knowledge_base_id: int
    document_id: int | None = None
    document_ids: list[int] = []
    conversation_id: int | None = None
    provider: Literal["dashscope", "deepseek"] = "dashscope"
    model_name: str | None = None
    answer_mode: AnswerMode = "strict"
    answer_style: AnswerStyle = "textbook"
    temperature: float = 0.3
    max_tokens: int = 1200
    limit: int = 8
    history_turns: int = 3
    history: list[QaHistoryMessage] = []
    reuse_context: dict[str, Any] | None = None


class QaConversationCreate(BaseModel):
    knowledge_base_id: int
    document_id: int | None = None
    title: str = "新会话"
    provider: Literal["dashscope", "deepseek"] = "dashscope"
    answer_mode: AnswerMode = "strict"
    answer_style: AnswerStyle = "textbook"


@router.get("/conversations")
def list_qa_conversations(
    knowledge_base_id: int | None = None,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[dict[str, Any]]:
    statement = select(QaConversation).where(
        QaConversation.user_id == _user.id,
        QaConversation.is_deleted.is_(False),
    )
    if knowledge_base_id is not None:
        get_accessible_knowledge_base(db, knowledge_base_id, _user)
        statement = statement.where(QaConversation.knowledge_base_id == knowledge_base_id)
    conversations = db.scalars(statement.order_by(QaConversation.updated_at.desc())).all()
    return [_conversation_summary(conversation) for conversation in conversations]


@router.post("/conversations")
def create_qa_conversation(
    payload: QaConversationCreate,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    _ensure_scope_exists(db, payload.knowledge_base_id, payload.document_id, _user)
    conversation = _create_conversation(
        db,
        user=_user,
        knowledge_base_id=payload.knowledge_base_id,
        document_id=payload.document_id,
        title=payload.title,
        provider=payload.provider,
        answer_mode=payload.answer_mode,
        answer_style=payload.answer_style,
    )
    return _conversation_detail(conversation)


@router.get("/conversations/{conversation_id}")
def get_qa_conversation(
    conversation_id: int,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    conversation = _get_user_conversation(db, conversation_id, _user)
    return _conversation_detail(conversation)


@router.delete("/conversations/{conversation_id}")
def delete_qa_conversation(
    conversation_id: int,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, bool]:
    conversation = _get_user_conversation(db, conversation_id, _user)
    conversation.is_deleted = True
    conversation.updated_at = utc_now_naive()
    db.add(conversation)
    db.commit()
    return {"ok": True}


@router.post("/query")
def query_retrieval(
    payload: RetrievalQuery,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    context = _retrieve_graph_context(payload, _user, db)
    answer = ""
    answer_source = "search"
    model_info: dict[str, Any] | None = None

    if payload.mode == "qa":
        answer_mode = payload.answer_mode
        uses_kg_context = _should_use_kg_context(query=context["query"], context=context, answer_mode=answer_mode)
        context["uses_kg_context"] = uses_kg_context
        context["message"] = _status_message(
            context["status"],
            uses_kg_context=uses_kg_context,
            answer_mode=answer_mode,
        )
        if answer_mode == "strict" and not uses_kg_context:
            answer = STRICT_INSUFFICIENT_MESSAGE
            answer_source = "local"
        else:
            try:
                llm_result = chat_completion_from_settings(
                    db=db,
                    user=_user,
                    provider=payload.provider,
                    messages=_build_qa_messages(
                        query=context["query"],
                        context=context,
                        answer_mode=answer_mode,
                        answer_style=payload.answer_style,
                        history=[],
                        use_kg_context=uses_kg_context,
                    ),
                    temperature=_clamp_temperature(payload.temperature, default=0.3),
                    max_tokens=_clamp_int(payload.max_tokens, default=1200, minimum=100, maximum=8000),
                )
            except LlmClientError as error:
                raise HTTPException(
                    status_code=error.status_code,
                    detail=error.message,
                ) from error
            answer = llm_result["content"]
            if uses_kg_context and answer_mode == "free" and not answer.startswith(FREE_MODE_NOTICE):
                answer = f"{FREE_MODE_NOTICE}\n\n{answer}"
            answer_source = "llm"
            model_info = {
                "provider": llm_result["provider"],
                "model_name": llm_result["model_name"],
                "key_source": llm_result["key_source"],
            }

    return {
        "mode": payload.mode,
        "query": context["query"],
        "provider": payload.provider,
        "source": context["source"],
        "uses_kg_context": context.get("uses_kg_context", False),
        "counts": context["counts"],
        "status": context["status"],
        "evidence_level": context["evidence_level"],
        "message": context["message"],
        "match_summary": context["match_summary"],
        "answer": answer,
        "answer_source": answer_source,
        "model": model_info,
        "related_nodes": context["related_nodes"],
        "triples": context["triples"],
        "sources": context["sources"],
        "images": context["images"],
    }


@router.post("/qa/stream")
def stream_qa(
    payload: QaStreamRequest,
    _user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    started_at = time.perf_counter()
    query = payload.query.strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="问题不能为空。",
        )

    temperature = _clamp_temperature(payload.temperature, default=0.3)
    max_tokens = _clamp_int(payload.max_tokens, default=1200, minimum=100, maximum=8000)

    def event_stream() -> Iterable[str]:
        yield _sse_prelude()
        yield _sse("status", {"phase": "retrieving", "message": "正在检索知识图谱依据..."})
        context = _context_from_reuse(payload.reuse_context) if payload.reuse_context else None
        conversation: QaConversation | None = None
        history: list[dict[str, str]] = []
        if context is None:
            try:
                context = _retrieve_graph_context(payload, _user, db)
            except HTTPException as error:
                yield _sse(
                    "error",
                    {
                        "detail": error.detail,
                        "status_code": error.status_code,
                        "elapsed_ms": _elapsed_ms(started_at),
                    },
                )
                return
        else:
            try:
                _ensure_scope_exists(db, payload.knowledge_base_id, payload.document_id, _user)
                context["query"] = query
            except HTTPException as error:
                yield _sse(
                    "error",
                    {
                        "detail": error.detail,
                        "status_code": error.status_code,
                        "elapsed_ms": _elapsed_ms(started_at),
                    },
                )
                return

        try:
            if payload.conversation_id is not None:
                conversation = _get_user_conversation(db, payload.conversation_id, _user)
                if conversation.knowledge_base_id != payload.knowledge_base_id:
                    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
                if (conversation.document_id or None) != (payload.document_id or None):
                    conversation.document_id = payload.document_id
                conversation.provider = payload.provider
                conversation.answer_mode = payload.answer_mode
                conversation.answer_style = payload.answer_style
            else:
                conversation = _create_conversation(
                    db,
                    user=_user,
                    knowledge_base_id=payload.knowledge_base_id,
                    document_id=payload.document_id,
                    title=_conversation_title(query),
                    provider=payload.provider,
                    answer_mode=payload.answer_mode,
                    answer_style=payload.answer_style,
                )
            history = (
                _conversation_history(db, conversation, turns=payload.history_turns)
                if payload.conversation_id is not None
                else _history_messages(payload.history, turns=payload.history_turns)
            )
            _save_qa_message(db, conversation, role="user", content=query)
        except HTTPException as error:
            yield _sse(
                "error",
                {
                    "detail": error.detail,
                    "status_code": error.status_code,
                    "elapsed_ms": _elapsed_ms(started_at),
                },
            )
            return

        base_metadata = {
            "conversation_id": conversation.id,
            "provider": payload.provider,
            "requested_model_name": _optional_model_name(payload.model_name),
            "answer_mode": payload.answer_mode,
            "answer_style": payload.answer_style,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "knowledge_base_id": payload.knowledge_base_id,
            "document_id": payload.document_id,
            "evidence_level": context["evidence_level"],
            "status": context["status"],
            "message": context["message"],
            "uses_kg_context": _should_use_kg_context(
                query=context["query"],
                context=context,
                answer_mode=payload.answer_mode,
            ),
            "counts": context["counts"],
            "match_summary": context["match_summary"],
            "source": context["source"],
        }
        context["uses_kg_context"] = bool(base_metadata["uses_kg_context"])
        context["message"] = _status_message(
            context["status"],
            uses_kg_context=context["uses_kg_context"],
            answer_mode=payload.answer_mode,
        )
        yield _sse("citations", _citation_payload(context))

        if _is_knowledge_scope_question(query):
            yield _sse("metadata", {**base_metadata, "answer_source": "local", "model": None})
            yield _sse("status", {"phase": "answering", "message": "正在整理当前知识库范围..."})
            answer_content = _scope_summary_answer(context)
            for fragment in _answer_fragments(answer_content, max_chars=6):
                yield _sse("delta", {"content": fragment})
                time.sleep(0.025)
            assistant_message = _save_qa_message(
                db,
                conversation,
                role="assistant",
                content=answer_content,
                citations=_citation_payload(context),
                metadata={**base_metadata, "answer_source": "local", "model": None},
            )
            yield _sse(
                "done",
                {
                    **base_metadata,
                    "answer_source": "local",
                    "elapsed_ms": _elapsed_ms(started_at),
                    "model": None,
                    "assistant_message_id": assistant_message.id,
                },
            )
            return

        if _is_streaming_capability_question(query):
            yield _sse("metadata", {**base_metadata, "answer_source": "local", "model": None})
            yield _sse("status", {"phase": "answering", "message": "正在说明系统流式能力..."})
            answer_content = STREAMING_CAPABILITY_MESSAGE
            for fragment in _answer_fragments(answer_content, max_chars=6):
                yield _sse("delta", {"content": fragment})
                time.sleep(0.025)
            assistant_message = _save_qa_message(
                db,
                conversation,
                role="assistant",
                content=answer_content,
                citations=_citation_payload(context),
                metadata={**base_metadata, "answer_source": "local", "model": None},
            )
            yield _sse(
                "done",
                {
                    **base_metadata,
                    "answer_source": "local",
                    "elapsed_ms": _elapsed_ms(started_at),
                    "model": None,
                    "assistant_message_id": assistant_message.id,
                },
            )
            return

        uses_kg_context = bool(base_metadata["uses_kg_context"])

        if payload.answer_mode == "strict" and not uses_kg_context:
            answer_content = STRICT_INSUFFICIENT_MESSAGE
            yield _sse("metadata", {**base_metadata, "answer_source": "local"})
            yield _sse("status", {"phase": "answering", "message": "正在整理回答..."})
            for fragment in _answer_fragments(answer_content, max_chars=6):
                yield _sse("delta", {"content": fragment})
                time.sleep(0.025)
            assistant_message = _save_qa_message(
                db,
                conversation,
                role="assistant",
                content=answer_content,
                citations=_citation_payload(context),
                metadata={**base_metadata, "answer_source": "local", "model": None},
            )
            yield _sse(
                "done",
                {
                    **base_metadata,
                    "answer_source": "local",
                    "elapsed_ms": _elapsed_ms(started_at),
                    "model": None,
                    "assistant_message_id": assistant_message.id,
                },
            )
            return

        yield _sse("status", {"phase": "calling_model", "message": "正在调用模型生成回答..."})

        try:
            llm_result = stream_chat_completion_from_settings(
                db=db,
                user=_user,
                provider=payload.provider,
                messages=_build_qa_messages(
                    query=context["query"],
                    context=context,
                    answer_mode=payload.answer_mode,
                    answer_style=payload.answer_style,
                    history=history,
                    use_kg_context=uses_kg_context,
                ),
                temperature=temperature,
                max_tokens=max_tokens,
                model_name=payload.model_name,
                timeout_seconds=120,
            )
            model_info = {
                "provider": llm_result["provider"],
                "model_name": llm_result["model_name"],
                "key_source": llm_result["key_source"],
            }
            yield _sse("metadata", {**base_metadata, "answer_source": "llm", "model": model_info})
            yield _sse("status", {"phase": "answering", "message": "正在生成回答..."})
            answer_parts: list[str] = []
            if uses_kg_context and payload.answer_mode == "free":
                notice = f"{FREE_MODE_NOTICE}\n\n"
                answer_parts.append(notice)
                yield _sse("delta", {"content": notice})
            for event, data in _stream_llm_chunks_with_heartbeat(llm_result["chunks"]):
                if event == "delta":
                    answer_parts.append(str(data["content"]))
                yield _sse(event, data)
            answer_content = "".join(answer_parts)
            assistant_message = _save_qa_message(
                db,
                conversation,
                role="assistant",
                content=answer_content,
                citations=_citation_payload(context),
                metadata={**base_metadata, "answer_source": "llm", "model": model_info},
            )
            yield _sse(
                "done",
                {
                    **base_metadata,
                    "answer_source": "llm",
                    "elapsed_ms": _elapsed_ms(started_at),
                    "model": model_info,
                    "assistant_message_id": assistant_message.id,
                },
            )
        except LlmClientError as error:
            yield _sse(
                "error",
                {
                    "detail": error.message,
                    "status_code": error.status_code,
                    "elapsed_ms": _elapsed_ms(started_at),
                },
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _retrieve_graph_context(
    payload: RetrievalQuery | QaStreamRequest,
    user: User,
    db: Session,
) -> dict[str, Any]:
    query = payload.query.strip()
    if not query:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="问题不能为空。",
        )

    document_ids = _scope_document_ids(payload)
    if document_ids:
        for document_id in document_ids:
            _ensure_scope_exists(db, payload.knowledge_base_id, document_id, user)
        summary = _merged_scope_summary(payload.knowledge_base_id, document_ids, user, db)
        nodes_data = _merged_scope_artifact("merged_nodes.json", "nodes", payload.knowledge_base_id, document_ids, user, db)
        edges_data = _merged_scope_artifact("merged_edges.json", "edges", payload.knowledge_base_id, document_ids, user, db)
        triples_data = _merged_scope_artifact("triples.json", "triples", payload.knowledge_base_id, document_ids, user, db)
    else:
        _ensure_scope_exists(db, payload.knowledge_base_id, payload.document_id, user)
        summary = graph_summary(
            knowledge_base_id=payload.knowledge_base_id,
            document_id=payload.document_id,
            _user=user,
            db=db,
        )
        nodes_data = graph_artifact(
            language="en",
            artifact_name="merged_nodes.json",
            knowledge_base_id=payload.knowledge_base_id,
            document_id=payload.document_id,
            _user=user,
            db=db,
        )
        edges_data = graph_artifact(
            language="en",
            artifact_name="merged_edges.json",
            knowledge_base_id=payload.knowledge_base_id,
            document_id=payload.document_id,
            _user=user,
            db=db,
        )
        triples_data = graph_artifact(
            language="en",
            artifact_name="triples.json",
            knowledge_base_id=payload.knowledge_base_id,
            document_id=payload.document_id,
            _user=user,
            db=db,
        )

    nodes = [node for node in nodes_data.get("nodes", []) if isinstance(node, dict)]
    edges = [edge for edge in edges_data.get("edges", []) if isinstance(edge, dict)]
    triples = [triple for triple in triples_data.get("triples", []) if isinstance(triple, dict)]
    node_by_id = {_node_id(node): node for node in nodes if _node_id(node)}
    edge_by_id = {_edge_id(edge): edge for edge in edges if _edge_id(edge)}

    terms = _query_terms(query)
    node_scores = sorted(
        (
            (_score_text(_node_search_text(node), terms, query) + _annotation_score(_node_annotations(node)), node)
            for node in nodes
            if not _has_excluding_annotation(_node_annotations(node))
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    triple_scores = sorted(
        (
            (
                _score_text(
                    _triple_search_text(triple, node_by_id=node_by_id, edge_by_id=edge_by_id),
                    terms,
                    query,
                ) + _annotation_score(_triple_annotations(triple, node_by_id=node_by_id, edge_by_id=edge_by_id)),
                triple,
            )
            for triple in triples
            if not _has_excluding_annotation(
                _triple_annotations(triple, node_by_id=node_by_id, edge_by_id=edge_by_id)
            )
        ),
        key=lambda item: item[0],
        reverse=True,
    )

    limit = _clamp_int(payload.limit, default=8, minimum=1, maximum=20)
    minimum_score = _minimum_match_score(query)
    related_nodes = [
        _node_response(node, score)
        for score, node in node_scores
        if score >= minimum_score
    ][:limit]
    related_triples = [
        _triple_response(triple, score, node_by_id=node_by_id, edge_by_id=edge_by_id)
        for score, triple in triple_scores
        if score >= minimum_score
    ][:limit]

    node_match_count = len(related_nodes)
    triple_match_count = len(related_triples)
    used_fallback = False
    has_graph_data = bool(nodes or edges or triples)

    sources = _source_documents(
        db,
        payload.knowledge_base_id,
        payload.document_id,
        user,
        document_ids=document_ids,
    )
    result_status = _result_status(
        has_graph_data=has_graph_data,
        node_match_count=node_match_count,
        triple_match_count=triple_match_count,
        used_fallback=used_fallback,
    )
    evidence_level = _evidence_level(
        result_status=result_status,
        related_nodes=related_nodes,
        related_triples=related_triples,
    )
    uses_kg_context = _should_use_kg_context(
        query=query,
        context={
            "status": result_status,
            "evidence_level": evidence_level,
            "related_nodes": related_nodes,
            "triples": related_triples,
        },
        answer_mode=getattr(payload, "answer_mode", "free"),
    )
    images = _dedupe_figures(
        [
            figure
            for item in [*related_nodes, *related_triples]
            for figure in item.get("figures", [])
            if isinstance(figure, dict)
        ]
    )
    return {
        "query": query,
        "source": summary["source"],
        "counts": summary["counts"],
        "status": result_status,
        "message": _status_message(
            result_status,
            uses_kg_context=uses_kg_context,
            answer_mode=getattr(payload, "answer_mode", "free"),
        ),
        "evidence_level": evidence_level,
        "uses_kg_context": uses_kg_context,
        "match_summary": {
            "node_matches": node_match_count,
            "triple_matches": triple_match_count,
            "source_documents": len(sources),
            "used_fallback": used_fallback,
        },
        "related_nodes": related_nodes,
        "triples": related_triples,
        "sources": sources,
        "images": images,
    }


def _context_from_reuse(value: dict[str, Any]) -> dict[str, Any] | None:
    required_keys = {"related_nodes", "triples", "sources", "images", "evidence_level", "status"}
    if not required_keys.issubset(value):
        return None
    related_nodes = value.get("related_nodes")
    triples = value.get("triples")
    sources = value.get("sources")
    images = value.get("images")
    if not all(isinstance(item, list) for item in [related_nodes, triples, sources, images]):
        return None
    return {
        "query": "",
        "source": str(value.get("source") or "processed"),
        "counts": value.get("counts") if isinstance(value.get("counts"), dict) else {},
        "status": str(value.get("status") or "matched"),
        "message": str(value.get("message") or ""),
        "evidence_level": str(value.get("evidence_level") or "limited"),
        "uses_kg_context": bool(value.get("uses_kg_context", True)),
        "match_summary": value.get("match_summary") if isinstance(value.get("match_summary"), dict) else {},
        "related_nodes": related_nodes,
        "triples": triples,
        "sources": sources,
        "images": images,
    }


def _ensure_scope_exists(
    db: Session,
    knowledge_base_id: int,
    document_id: int | None,
    user: User,
) -> None:
    get_accessible_knowledge_base(db, knowledge_base_id, user)
    if document_id is None:
        return
    statement = select(Document).join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id).where(
        Document.id == document_id,
        Document.knowledge_base_id == knowledge_base_id,
        Document.is_deleted.is_(False),
    )
    if user.role != "admin":
        statement = statement.where(
            or_(
                Document.owner_user_id == user.id,
                KnowledgeBase.owner_user_id.is_(None),
            )
        )
    document = db.scalar(statement)
    if document is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Document not found.",
        )


def _scope_document_ids(payload: RetrievalQuery | QaStreamRequest) -> list[int]:
    raw_ids = getattr(payload, "document_ids", []) or []
    document_ids: list[int] = []
    seen: set[int] = set()
    for value in raw_ids:
        try:
            document_id = int(value)
        except (TypeError, ValueError):
            continue
        if document_id > 0 and document_id not in seen:
            document_ids.append(document_id)
            seen.add(document_id)
    return document_ids


def _merged_scope_summary(
    knowledge_base_id: int,
    document_ids: list[int],
    user: User,
    db: Session,
) -> dict[str, Any]:
    summaries = [
        graph_summary(
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
            _user=user,
            db=db,
        )
        for document_id in document_ids
    ]
    counts = {"nodes": 0, "edges": 0, "triples": 0}
    documents: list[dict[str, Any]] = []
    processed_run_ids: list[str] = []
    for summary in summaries:
        for key in counts:
            counts[key] += int(summary.get("counts", {}).get(key) or 0)
        documents.extend(item for item in summary.get("documents", []) if isinstance(item, dict))
        processed_run_ids.extend(str(run_id) for run_id in summary.get("processed_run_ids", []) if run_id)
    return {
        "source": "processed" if processed_run_ids else "empty",
        "knowledge_base_id": knowledge_base_id,
        "document_id": None,
        "documents": documents,
        "processed_run_ids": processed_run_ids,
        "counts": counts,
    }


def _merged_scope_artifact(
    artifact_name: str,
    list_key: str,
    knowledge_base_id: int,
    document_ids: list[int],
    user: User,
    db: Session,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    schema_version = f"kg.{list_key}.v1"
    for document_id in document_ids:
        artifact = graph_artifact(
            language="en",
            artifact_name=artifact_name,
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
            _user=user,
            db=db,
        )
        schema_version = str(artifact.get("schema_version") or schema_version)
        for item in artifact.get(list_key, []):
            if not isinstance(item, dict):
                continue
            item_id = _artifact_item_id(item, list_key)
            if item_id and item_id in seen_ids:
                continue
            if item_id:
                seen_ids.add(item_id)
            items.append(item)
    return {"schema_version": schema_version, "run_id": "merged_selected_documents", list_key: items}


def _artifact_item_id(item: dict[str, Any], list_key: str) -> str:
    if list_key == "nodes":
        return str(item.get("node_id") or item.get("id") or "")
    if list_key == "edges":
        return str(item.get("edge_id") or item.get("id") or "")
    return str(item.get("triple_id") or item.get("id") or "")


def _query_terms(query: str) -> list[str]:
    lower = query.lower().strip()
    terms: list[str] = []
    terms.extend(re.findall(r"[a-z0-9][a-z0-9_+-]{1,}", lower))
    cjk_chars = [char for char in lower if "\u4e00" <= char <= "\u9fff"]
    cjk_text = "".join(cjk_chars)
    if len(cjk_text) >= 2:
        terms.append(cjk_text)
        terms.extend("".join(cjk_chars[index:index + 2]) for index in range(len(cjk_chars) - 1))
    if len(cjk_text) >= 3:
        terms.extend("".join(cjk_chars[index:index + 3]) for index in range(len(cjk_chars) - 2))
    return list(dict.fromkeys(term for term in terms if term))


def _score_text(text: str, terms: list[str], query: str) -> int:
    value = text.lower()
    score = 0
    normalized_query = query.lower().strip()
    compact_query = "".join(normalized_query.split())
    compact_value = "".join(value.split())
    if compact_query and compact_query in compact_value:
        score += 20
    for term in terms:
        if not term:
            continue
        if term in value:
            score += 5 if len(term) >= 3 else 3
    return score


ANNOTATION_SCORE_WEIGHTS = {
    "已确认": 5,
    "重点": 4,
    "考点": 4,
    "适合问答引用": 5,
    "图片证据": 2,
    "适合课堂讲解": 2,
    "需人工复核": -1,
}
EXCLUDING_ANNOTATION_TAGS = {"错误抽取"}


def _annotation_score(annotation: dict[str, Any]) -> int:
    tags = _annotation_tags(annotation)
    return sum(ANNOTATION_SCORE_WEIGHTS.get(tag, 0) for tag in tags)


def _has_excluding_annotation(annotation: dict[str, Any]) -> bool:
    return any(tag in EXCLUDING_ANNOTATION_TAGS for tag in _annotation_tags(annotation))


def _annotation_tags(annotation: dict[str, Any]) -> list[str]:
    tags = annotation.get("tags") if isinstance(annotation, dict) else []
    if not isinstance(tags, list):
        return []
    return [str(tag) for tag in tags if str(tag).strip()]


def _node_annotations(node: dict[str, Any]) -> dict[str, Any]:
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    annotation = props.get("web_annotations") if isinstance(props, dict) else {}
    return annotation if isinstance(annotation, dict) else {}


def _triple_annotations(
    triple: dict[str, Any],
    *,
    node_by_id: dict[str, dict[str, Any]],
    edge_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    annotations: dict[str, Any] = {"tags": [], "note": ""}
    for annotation in [
        _node_annotations(node_by_id.get(str(triple.get("subject_node_id", "")), {})),
        _node_annotations(node_by_id.get(str(triple.get("object_node_id", "")), {})),
        _edge_annotations(edge_by_id.get(str(triple.get("edge_id", "")), {})),
        _property_annotations(triple),
    ]:
        _merge_annotation_payload(annotations, annotation)
    return annotations


def _edge_annotations(edge: dict[str, Any]) -> dict[str, Any]:
    return _property_annotations(edge)


def _property_annotations(item: dict[str, Any]) -> dict[str, Any]:
    props = item.get("properties") if isinstance(item.get("properties"), dict) else {}
    annotation = props.get("web_annotations") if isinstance(props, dict) else {}
    return annotation if isinstance(annotation, dict) else {}


def _merge_annotation_payload(target: dict[str, Any], annotation: dict[str, Any]) -> None:
    if not isinstance(annotation, dict):
        return
    tags = target.setdefault("tags", [])
    if isinstance(tags, list):
        for tag in _annotation_tags(annotation):
            if tag not in tags:
                tags.append(tag)
    note = str(annotation.get("note") or "").strip()
    if note and not target.get("note"):
        target["note"] = note


def _minimum_match_score(query: str) -> int:
    cjk_length = len([char for char in query if "\u4e00" <= char <= "\u9fff"])
    if _is_smalltalk_query(query):
        return 999
    if cjk_length <= 2 and not re.search(r"[a-z0-9]{2,}", query.lower()):
        return 20
    return 6


def _should_use_kg_context(
    *,
    query: str,
    context: dict[str, Any],
    answer_mode: AnswerMode,
) -> bool:
    if _is_smalltalk_query(query):
        return False
    if answer_mode == "strict":
        return context.get("evidence_level") != "none" and context.get("status") == "matched"
    if context.get("status") != "matched":
        return False
    return bool(context.get("related_nodes") or context.get("triples"))


def _is_smalltalk_query(query: str) -> bool:
    normalized = re.sub(r"[\s，。！？!?,.;；、~～]+", "", query.lower())
    smalltalk = {
        "你好",
        "您好",
        "hello",
        "hi",
        "嗨",
        "在吗",
        "谢谢",
        "感谢",
        "早上好",
        "中午好",
        "下午好",
        "晚上好",
    }
    return normalized in smalltalk


def _result_status(
    *,
    has_graph_data: bool,
    node_match_count: int,
    triple_match_count: int,
    used_fallback: bool,
) -> str:
    if not has_graph_data:
        return "no_graph"
    if node_match_count > 0 or triple_match_count > 0:
        return "matched"
    if used_fallback:
        return "fallback"
    return "no_matches"


def _evidence_level(
    *,
    result_status: str,
    related_nodes: list[dict[str, Any]],
    related_triples: list[dict[str, Any]],
) -> EvidenceLevel:
    if result_status in {"no_graph", "no_matches", "fallback"}:
        return "none"
    best_score = max(
        [int(item.get("score") or 0) for item in [*related_nodes, *related_triples]],
        default=0,
    )
    if len(related_triples) >= 2 or (related_nodes and related_triples and best_score >= 6):
        return "sufficient"
    return "limited"


def _status_message(
    result_status: str,
    *,
    uses_kg_context: bool = True,
    answer_mode: AnswerMode = "strict",
) -> str:
    if answer_mode == "free" and not uses_kg_context:
        return "当前问题未命中知识库的可靠依据，已按通用问答处理。"
    messages = {
        "matched": "已找到与问题相关的知识图谱依据。",
        "fallback": "未找到直接匹配依据，下面展示当前范围内最接近的图谱片段。",
        "no_matches": "当前范围内没有找到匹配的图谱依据。",
        "no_graph": "当前范围还没有可用的知识图谱，请先上传 PDF 并构建图谱。",
    }
    return messages[result_status]


def _node_search_text(node: dict[str, Any]) -> str:
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    parts = [
        node.get("node_id", ""),
        node.get("label", ""),
        props.get("title", ""),
        props.get("name", ""),
        props.get("period_name", ""),
        props.get("site_name", ""),
        props.get("culture_name", ""),
        props.get("system_name", ""),
        props.get("person_name", ""),
        props.get("definition", ""),
        props.get("description", ""),
        " ".join(str(alias) for alias in props.get("aliases", []) if alias),
        _figures_text(props.get("figures", [])),
        _evidence_text(props.get("evidence", [])),
    ]
    return " ".join(str(part) for part in parts if part)


def _triple_search_text(
    triple: dict[str, Any],
    *,
    node_by_id: dict[str, dict[str, Any]],
    edge_by_id: dict[str, dict[str, Any]],
) -> str:
    subject = node_by_id.get(str(triple.get("subject_node_id", "")), {})
    obj = node_by_id.get(str(triple.get("object_node_id", "")), {})
    edge = edge_by_id.get(str(triple.get("edge_id", "")), {})
    edge_props = edge.get("properties") if isinstance(edge.get("properties"), dict) else {}
    return " ".join(
        [
            _node_title(subject),
            str(triple.get("predicate", "")),
            _node_title(obj),
            str(edge_props.get("relation_label", "")),
            str(edge_props.get("rationale", "")),
            _figures_text(edge_props.get("figures", [])),
            _figures_text(triple.get("figures", [])),
            _evidence_text(triple.get("evidence", [])),
        ]
    )


def _node_response(node: dict[str, Any], score: int) -> dict[str, Any]:
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    evidence = _first_evidence(props.get("evidence", []))
    return {
        "id": _node_id(node),
        "label": node.get("label", "Node"),
        "title": _node_title(node),
        "description": props.get("definition") or props.get("description") or "",
        "score": score,
        "evidence": evidence,
        "figures": _figure_responses(props.get("figures", [])),
        "annotations": _node_annotations(node),
    }


def _triple_response(
    triple: dict[str, Any],
    score: int,
    *,
    node_by_id: dict[str, dict[str, Any]],
    edge_by_id: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    subject = node_by_id.get(str(triple.get("subject_node_id", "")), {})
    obj = node_by_id.get(str(triple.get("object_node_id", "")), {})
    edge = edge_by_id.get(str(triple.get("edge_id", "")), {})
    edge_props = edge.get("properties") if isinstance(edge.get("properties"), dict) else {}
    figures = _dedupe_figures(
        [
            *_figure_responses(edge_props.get("figures", [])),
            *_figure_responses(triple.get("figures", [])),
        ]
    )
    return {
        "id": triple.get("triple_id", ""),
        "subject": _node_title(subject) or str(triple.get("subject_node_id", "")),
        "predicate": triple.get("predicate", ""),
        "object": _node_title(obj) or str(triple.get("object_node_id", "")),
        "score": score,
        "rationale": edge_props.get("rationale", ""),
        "evidence": _first_evidence(triple.get("evidence", [])),
        "figures": figures,
        "annotations": _triple_annotations(triple, node_by_id=node_by_id, edge_by_id=edge_by_id),
    }


def _figure_responses(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    figures: list[dict[str, Any]] = []
    for figure in value:
        if not isinstance(figure, dict):
            continue
        image_path = str(figure.get("image_path") or "").strip()
        description = str(
            figure.get("description")
            or figure.get("text")
            or figure.get("caption")
            or figure.get("alt")
            or ""
        ).strip()
        if not image_path and not description:
            continue
        figures.append(
            {
                "figure_id": str(figure.get("figure_id") or figure.get("id") or image_path),
                "image_path": image_path,
                "description": description,
                "value_marker": str(figure.get("value_marker") or ""),
                "category": str(figure.get("category") or figure.get("taxonomy_label") or ""),
                "annotations": figure.get("web_annotations") if isinstance(figure.get("web_annotations"), dict) else {},
            }
        )
    return _dedupe_figures(figures)


def _dedupe_figures(figures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for figure in figures:
        key = str(figure.get("image_path") or figure.get("figure_id") or figure.get("description") or "")
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(figure)
    return result


def _figures_text(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    return " ".join(
        " ".join(str(figure.get(key) or "") for key in ["description", "caption", "value_marker", "category"])
        for figure in value
        if isinstance(figure, dict)
    )


def _build_qa_messages(
    *,
    query: str,
    context: dict[str, Any],
    answer_mode: AnswerMode,
    answer_style: AnswerStyle,
    history: list[dict[str, str]],
    use_kg_context: bool,
) -> list[dict[str, str]]:
    style_instruction = {
        "concise": "用简洁、直接的方式回答，先给结论，再补一句关键依据。",
        "textbook": "按中文教材讲解风格回答，概念清楚、层次分明，适合课堂理解。",
        "exam": "按考点总结风格回答，突出关键词、易考点和常见表述。",
        "student": "用学生容易听懂的话解释，可以适当类比，但不要牺牲准确性。",
    }[answer_style]
    if answer_mode == "strict":
        mode_instruction = (
            "只能根据给定知识图谱依据回答。证据不足时，明确说明缺少什么依据，不要编造。"
            "不要使用外部知识补全事实。"
        )
    else:
        mode_instruction = (
            "优先根据给定知识图谱依据回答。若依据有限，可以结合通用知识补充，"
            "但不要把补充内容伪装成知识图谱原文。系统会在答案开头自动展示自由补充提示。"
        )

    if not use_kg_context:
        messages: list[dict[str, str]] = [
            {
                "role": "system",
                "content": (
                    "你是“书脉”的中文学习问答助手，也可以像普通大模型一样回答日常、通用学习和解释类问题。"
                    "当前问题没有命中当前知识库的可靠知识图谱依据，因此不要声称“依据知识图谱”、"
                    "不要引用节点 ID、三元组 ID、图片文件名或教材来源。"
                    "如果用户只是问候，请自然、简短地回应，并引导用户继续提问。"
                    f"{style_instruction}"
                ),
            }
        ]
        messages.extend(history)
        messages.append({"role": "user", "content": query})
        return messages

    context_json = json_dumps_compact(_model_context_payload(context), limit=12000)
    messages: list[dict[str, str]] = [
        {
            "role": "system",
            "content": (
                "你是“书脉”中的教材知识图谱问答助手。必须使用中文回答。"
                "正文要像正常学习问答一样自然清楚，不要直接展示节点 ID、三元组 ID、JSON 字段名、文件路径或图片文件名。"
                "需要标注依据时，只在关键结论后使用短标记，例如 [依据1]、[依据2]。"
                "只能使用证据索引中已经给出的依据编号，不要自造编号；不需要逐句都标注，优先标 3 到 5 个关键结论。"
                "教材原文、节点、关系和图片细节由页面的折叠依据区展示，正文不要大段罗列出处。"
                f"{mode_instruction}{style_instruction}"
            ),
        }
    ]
    messages.extend(history)
    messages.append(
        {
            "role": "user",
            "content": (
                f"问题：\n{query}\n\n"
                f"证据充分度：{context['evidence_level']}\n\n"
                "可引用的证据索引 JSON：\n"
                f"{context_json}"
            ),
        }
    )
    return messages


def _model_context_payload(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "query": context["query"],
        "status": context["status"],
        "message": context["message"],
        "evidence_level": context["evidence_level"],
        "evidence_items": _evidence_items(context, include_details=False),
        "source_documents": [
            {"filename": source.get("filename", ""), "status": source.get("status", "")}
            for source in context.get("sources", [])
            if isinstance(source, dict)
        ],
    }


def _evidence_items(context: dict[str, Any], *, include_details: bool) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []

    def add_item(item: dict[str, Any]) -> None:
        if len(items) >= 12:
            return
        item["ref"] = f"依据{len(items) + 1}"
        items.append(item)

    for triple in context.get("triples", []):
        if not isinstance(triple, dict):
            continue
        evidence = triple.get("evidence") if isinstance(triple.get("evidence"), dict) else {}
        figures = triple.get("figures") if isinstance(triple.get("figures"), list) else []
        quote = _short_text(evidence.get("quote_or_summary") or "")
        item = {
            "kind": "关系",
            "title": (
                f"{triple.get('subject', '')} - "
                f"{_display_predicate_label(triple.get('predicate', ''))} - "
                f"{triple.get('object', '')}"
            ),
            "summary": quote or _short_text(triple.get("rationale") or ""),
            "quote": quote,
            "section": evidence.get("section_title", ""),
            "images": [
                {
                    "image_path": figure.get("image_path", ""),
                    "description": _short_text(figure.get("description") or figure.get("value_marker") or ""),
                }
                for figure in figures
                if isinstance(figure, dict)
            ][:3],
        }
        if include_details:
            item["triple"] = triple
        add_item(item)

    for node in context.get("related_nodes", []):
        if not isinstance(node, dict):
            continue
        evidence = node.get("evidence") if isinstance(node.get("evidence"), dict) else {}
        figures = node.get("figures") if isinstance(node.get("figures"), list) else []
        item = {
            "kind": "节点",
            "title": str(node.get("title") or ""),
            "summary": _short_text(node.get("description") or evidence.get("quote_or_summary") or ""),
            "quote": _short_text(evidence.get("quote_or_summary") or ""),
            "section": evidence.get("section_title", ""),
            "images": [
                {
                    "image_path": figure.get("image_path", ""),
                    "description": _short_text(figure.get("description") or figure.get("value_marker") or ""),
                }
                for figure in figures
                if isinstance(figure, dict)
            ][:3],
        }
        if include_details:
            item["node"] = node
        add_item(item)

    seen_images: set[str] = set()
    for image in context.get("images", []):
        if not isinstance(image, dict):
            continue
        image_path = str(image.get("image_path") or "")
        if image_path in seen_images:
            continue
        seen_images.add(image_path)
        item = {
            "kind": "图片",
            "title": _short_text(image.get("description") or image.get("figure_id") or "图片证据"),
            "summary": _short_text(image.get("value_marker") or image.get("category") or image.get("description") or ""),
            "quote": "",
            "section": "",
            "images": [
                {
                    "image_path": image_path,
                    "description": _short_text(image.get("description") or image.get("value_marker") or ""),
                }
            ],
        }
        if include_details:
            item["image"] = image
        add_item(item)

    return items


def _short_text(value: Any, *, limit: int = 260) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[:limit].rstrip()}..."


def _display_predicate_label(predicate: Any) -> str:
    labels = {
        "associated_with": "关联",
        "associated_with_culture": "关联文化",
        "belonged_to": "曾属于",
        "belongs_to": "属于",
        "belongs_to_period": "属于时期",
        "characterized_by": "特征为",
        "classified_as": "归类为",
        "composed_of": "由此组成",
        "contains": "包含",
        "defines": "定义",
        "defined_as": "定义为",
        "exemplifies": "举例说明",
        "exhibits": "展示",
        "exhibits_trait": "体现特征",
        "extends": "延伸",
        "formed_by": "形成于",
        "has_property": "具有性质",
        "influencedBy": "受影响于",
        "integrates": "整合",
        "located_at": "位于",
        "located_in": "位于",
        "part_of": "属于",
        "precedes": "早于",
        "produces": "产生",
        "prerequisite_for": "作为先修",
        "requires": "依赖",
        "tests": "考查",
        "uses_method": "使用方法",
    }
    text = str(predicate or "")
    return labels.get(text, text)


def _citation_payload(context: dict[str, Any]) -> dict[str, Any]:
    return {
        "query": context["query"],
        "source": context["source"],
        "counts": context["counts"],
        "status": context["status"],
        "message": context["message"],
        "evidence_level": context["evidence_level"],
        "uses_kg_context": context.get("uses_kg_context", False),
        "match_summary": context["match_summary"],
        "related_nodes": context["related_nodes"],
        "triples": context["triples"],
        "sources": context["sources"],
        "images": context["images"],
        "evidence_items": _evidence_items(context, include_details=True),
    }


def _history_messages(history: list[QaHistoryMessage], *, turns: int) -> list[dict[str, str]]:
    max_messages = _clamp_int(turns, default=3, minimum=0, maximum=10) * 2
    if max_messages <= 0:
        return []
    messages: list[dict[str, str]] = []
    for item in history[-max_messages:]:
        content = item.content.strip()
        if not content:
            continue
        messages.append({"role": item.role, "content": content[:4000]})
    return messages


def _stream_llm_chunks_with_heartbeat(
    chunks: Iterable[str],
    *,
    heartbeat_seconds: float = 1.5,
) -> Iterable[tuple[str, dict[str, Any]]]:
    events: queue.Queue[tuple[str, str | BaseException | None]] = queue.Queue()

    def consume() -> None:
        try:
            for chunk in chunks:
                if chunk:
                    events.put(("delta", str(chunk)))
            events.put(("done", None))
        except BaseException as error:
            events.put(("error", error))

    Thread(target=consume, daemon=True).start()
    waited_seconds = 0.0
    while True:
        try:
            event, value = events.get(timeout=heartbeat_seconds)
        except queue.Empty:
            waited_seconds += heartbeat_seconds
            yield (
                "status",
                {
                    "phase": "waiting_model",
                    "message": f"模型正在生成，已等待 {int(waited_seconds)} 秒...",
                },
            )
            continue
        if event == "done":
            return
        if event == "error":
            if isinstance(value, LlmClientError):
                raise value
            raise LlmClientError(f"Model streaming failed: {value}") from value
        for fragment in _answer_fragments(str(value or "")):
            yield ("delta", {"content": fragment})
            if len(str(value or "")) > 12:
                time.sleep(0.025)


def _answer_fragments(content: str, *, max_chars: int = 6) -> Iterable[str]:
    if len(content) <= max_chars:
        yield content
        return
    for index in range(0, len(content), max_chars):
        yield content[index:index + max_chars]


def _is_streaming_capability_question(query: str) -> bool:
    normalized = query.lower()
    streaming_terms = ["流式", "stream", "streaming", "逐字", "逐句", "实时输出", "打字"]
    system_terms = ["支持", "能不能", "可不可以", "可以吗", "不能", "网页", "页面", "系统", "前端", "后端", "接口", "api"]
    return any(term in normalized for term in streaming_terms) and any(term in normalized for term in system_terms)


def _is_knowledge_scope_question(query: str) -> bool:
    normalized = re.sub(r"[\s，。！？!?,.;；、~～]+", "", query.lower())
    scope_terms = ["范围", "内容", "知识范围", "知识库", "当前库", "当前知识库", "有哪些", "包含什么"]
    intent_terms = ["范围", "内容", "有哪些", "有什么", "包含什么", "覆盖什么", "学了什么"]
    return (
        any(term in normalized for term in scope_terms)
        and any(term in normalized for term in intent_terms)
        and len(normalized) <= 40
    )


def _scope_summary_answer(context: dict[str, Any]) -> str:
    counts = context.get("counts") if isinstance(context.get("counts"), dict) else {}
    match_summary = context.get("match_summary") if isinstance(context.get("match_summary"), dict) else {}
    sources = [source for source in context.get("sources", []) if isinstance(source, dict)]
    source_count = int(match_summary.get("source_documents") or len(sources) or 0)
    node_count = int(counts.get("nodes") or 0)
    edge_count = int(counts.get("edges") or 0)
    triple_count = int(counts.get("triples") or 0)

    if node_count == 0 and edge_count == 0 and triple_count == 0:
        return (
            "当前范围内还没有可用的知识图谱结果。\n\n"
            "你可以先在文档页上传 PDF，并依次执行 Parse PDF 和 Build Graph。"
            "图谱生成成功后，我就能根据当前知识库回答教材内容、提取依据并展示相关节点。"
        )

    lines = [
        "当前库中的知识范围可以这样理解：",
        "",
        f"- 已纳入图谱的文档：{source_count} 个。",
        f"- 图谱规模：约 {node_count} 个节点、{edge_count} 条边、{triple_count} 个三元组。",
    ]
    if sources:
        filenames = [str(source.get("filename") or "").strip() for source in sources[:6]]
        filenames = [filename for filename in filenames if filename]
        if filenames:
            suffix = "等" if len(sources) > len(filenames) else ""
            lines.append(f"- 当前依据主要来自：{'、'.join(filenames)}{suffix}。")
    if context.get("source") == "processed":
        lines.append("- 这些内容来自你已经生成的知识图谱，问答时会优先检索当前范围内的节点、关系、三元组和图片文字依据。")
    else:
        lines.append("- 当前没有检测到正式处理产物，范围说明可能不完整。")
    lines.extend([
        "",
        "如果你想看更具体的范围，可以问：这个库里有哪些章节？有哪些核心概念？某个 PDF 主要讲什么？",
    ])
    return "\n".join(lines)


def _get_user_conversation(db: Session, conversation_id: int, user: User) -> QaConversation:
    conversation = db.get(QaConversation, conversation_id)
    if conversation is None or conversation.is_deleted or conversation.user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    return conversation


def _create_conversation(
    db: Session,
    *,
    user: User,
    knowledge_base_id: int,
    document_id: int | None,
    title: str,
    provider: str,
    answer_mode: str,
    answer_style: str,
) -> QaConversation:
    now = utc_now_naive()
    conversation = QaConversation(
        user_id=user.id,
        knowledge_base_id=knowledge_base_id,
        document_id=document_id,
        title=_conversation_title(title),
        provider=provider,
        answer_mode=answer_mode,
        answer_style=answer_style,
        is_deleted=False,
        created_at=now,
        updated_at=now,
    )
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return conversation


def _save_qa_message(
    db: Session,
    conversation: QaConversation,
    *,
    role: str,
    content: str,
    citations: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> QaMessage:
    message = QaMessage(
        conversation_id=conversation.id,
        role=role,
        content=content,
        citations_json=json.dumps(citations or {}, ensure_ascii=False, separators=(",", ":")),
        metadata_json=json.dumps(metadata or {}, ensure_ascii=False, separators=(",", ":")),
        created_at=utc_now_naive(),
    )
    conversation.updated_at = utc_now_naive()
    db.add(message)
    db.add(conversation)
    db.commit()
    db.refresh(message)
    db.refresh(conversation)
    return message


def _conversation_history(db: Session, conversation: QaConversation, *, turns: int) -> list[dict[str, str]]:
    max_messages = _clamp_int(turns, default=3, minimum=0, maximum=10) * 2
    if max_messages <= 0:
        return []
    statement = (
        select(QaMessage)
        .where(QaMessage.conversation_id == conversation.id)
        .order_by(QaMessage.created_at.desc(), QaMessage.id.desc())
        .limit(max_messages)
    )
    stored_messages = list(reversed(db.scalars(statement).all()))
    return [
        {"role": message.role, "content": _history_content_for_model(message.content)}
        for message in stored_messages
        if message.role in {"user", "assistant"} and _history_content_for_model(message.content)
    ]


def _conversation_summary(conversation: QaConversation) -> dict[str, Any]:
    visible_messages = [message for message in conversation.messages if message.content.strip()]
    last_message = visible_messages[-1] if visible_messages else None
    return {
        "id": conversation.id,
        "knowledge_base_id": conversation.knowledge_base_id,
        "document_id": conversation.document_id,
        "title": conversation.title,
        "provider": conversation.provider,
        "answer_mode": conversation.answer_mode,
        "answer_style": conversation.answer_style,
        "message_count": len(visible_messages),
        "last_message_role": last_message.role if last_message else "",
        "last_message_preview": _message_preview(last_message.content) if last_message else "",
        "created_at": conversation.created_at.isoformat(),
        "updated_at": conversation.updated_at.isoformat(),
    }


def _conversation_detail(conversation: QaConversation) -> dict[str, Any]:
    return {
        **_conversation_summary(conversation),
        "messages": [_message_response(message) for message in conversation.messages],
    }


def _message_response(message: QaMessage) -> dict[str, Any]:
    return {
        "id": message.id,
        "conversation_id": message.conversation_id,
        "role": message.role,
        "content": message.content,
        "citations": _json_text_to_dict(message.citations_json),
        "metadata": _json_text_to_dict(message.metadata_json),
        "created_at": message.created_at.isoformat(),
    }


def _json_text_to_dict(value: str) -> dict[str, Any]:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _conversation_title(value: str) -> str:
    title = " ".join(value.strip().split())
    if not title:
        return "新会话"
    return title[:48]


def _message_preview(value: str) -> str:
    preview = " ".join(value.strip().split())
    if not preview:
        return ""
    return preview[:96]


def _optional_model_name(value: str | None) -> str:
    return (value or "").strip()


def _history_content_for_model(value: str) -> str:
    content = value.strip()
    if content.startswith(FREE_MODE_NOTICE):
        content = content[len(FREE_MODE_NOTICE):].strip()
    return content[:4000]


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, separators=(',', ':'))}\n\n"


def _sse_prelude() -> str:
    return f": {' ' * 2048}\n\n"


def _elapsed_ms(started_at: float) -> int:
    return int((time.perf_counter() - started_at) * 1000)


def _build_answer(
    query: str,
    related_nodes: list[dict[str, Any]],
    related_triples: list[dict[str, Any]],
    source: str,
    result_status: str,
) -> str:
    if result_status == "no_graph":
        return "当前范围还没有可用的知识图谱，请先上传 PDF 并构建图谱。"
    if result_status == "fallback":
        return f"没有直接匹配到“{query}”的图谱依据，下面展示最接近的图谱片段供参考。"
    if not related_nodes and not related_triples:
        return f"没有找到与“{query}”匹配的知识图谱依据。"
    node_names = "、".join(item["title"] for item in related_nodes[:3] if item.get("title"))
    triple_text = "；".join(
        f"{item['subject']} → {item['predicate']} → {item['object']}"
        for item in related_triples[:3]
    )
    parts = [f"基于当前 {source} 知识图谱"]
    if node_names:
        parts.append(f"相关节点包括：{node_names}")
    if triple_text:
        parts.append(f"相关三元组包括：{triple_text}")
    return "；".join(parts) + "。"


def json_dumps_compact(value: Any, *, limit: int = 12000) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))[:limit]


def _source_documents(
    db: Session,
    knowledge_base_id: int,
    document_id: int | None,
    user: User,
    *,
    document_ids: list[int] | None = None,
) -> list[dict[str, Any]]:
    statement = select(Document).join(KnowledgeBase, Document.knowledge_base_id == KnowledgeBase.id).where(
        Document.knowledge_base_id == knowledge_base_id,
        Document.is_deleted.is_(False),
    )
    if document_ids:
        statement = statement.where(Document.id.in_(document_ids))
    elif document_id is not None:
        statement = statement.where(Document.id == document_id)
    if user.role != "admin":
        statement = statement.where(
            or_(
                Document.owner_user_id == user.id,
                KnowledgeBase.owner_user_id.is_(None),
            )
        )
    return [
        {"id": document.id, "filename": document.filename, "status": document.status}
        for document in db.scalars(statement.order_by(Document.uploaded_at.desc()))
    ]


def _node_id(node: dict[str, Any]) -> str:
    return str(node.get("node_id") or node.get("id") or "")


def _edge_id(edge: dict[str, Any]) -> str:
    return str(edge.get("edge_id") or edge.get("id") or "")


def _node_title(node: dict[str, Any]) -> str:
    props = node.get("properties") if isinstance(node.get("properties"), dict) else {}
    for key in [
        "title",
        "name",
        "site_name",
        "period_name",
        "culture_name",
        "system_name",
        "person_name",
        "concept_name",
    ]:
        if props.get(key):
            return str(props[key])
    return str(node.get("label") or _node_id(node))


def _first_evidence(value: Any) -> dict[str, Any] | None:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        item = value[0]
        section = item.get("section") if isinstance(item.get("section"), dict) else {}
        return {
            "quote_or_summary": item.get("quote_or_summary", ""),
            "source_path": _safe_source_path(item.get("source_path", "")),
            "section_title": section.get("title", ""),
        }
    return None


def _evidence_text(value: Any) -> str:
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        parts.append(str(item.get("quote_or_summary", "")))
        section = item.get("section")
        if isinstance(section, dict):
            parts.append(str(section.get("title", "")))
    return " ".join(parts)


def _safe_source_path(value: Any) -> str:
    normalized = str(value or "").replace("\\", "/").strip()
    if not normalized:
        return ""
    parts = [part for part in normalized.split("/") if part]
    return "/".join(parts[-3:])


def _clamp_temperature(value: float | None, *, default: float) -> float:
    try:
        parsed = float(default if value is None else value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(parsed, 2.0))


def _clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))
