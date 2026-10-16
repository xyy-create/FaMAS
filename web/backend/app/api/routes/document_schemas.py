from __future__ import annotations

from typing import Any
import json

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.time import utc_now_naive
from app.db.session import get_db
from app.models.document import Document
from app.models.document_schema_version import DocumentSchemaVersion
from app.models.user import User
from app.schemas.document_schema import (
    DocumentSchemaLlmRewriteRequest,
    DocumentSchemaTemplateRequest,
    DocumentSchemaVersionCreate,
    DocumentSchemaVersionResponse,
    DocumentSchemaVersionUpdate,
)
from app.services.knowledge_base_access import get_accessible_knowledge_base
from app.services import llm_client

router = APIRouter(prefix="/api/documents/{document_id}/schemas", tags=["document-schemas"])


@router.get("", response_model=list[DocumentSchemaVersionResponse])
def list_document_schema_versions(
    document_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> list[DocumentSchemaVersionResponse]:
    document = _get_accessible_document(db, document_id, user)
    versions = db.scalars(
        select(DocumentSchemaVersion)
        .where(DocumentSchemaVersion.document_id == document.id)
        .order_by(DocumentSchemaVersion.is_active.desc(), DocumentSchemaVersion.version_number.desc())
    )
    return [_to_response(version) for version in versions]


@router.post("", response_model=DocumentSchemaVersionResponse)
def create_document_schema_version(
    document_id: int,
    payload: DocumentSchemaVersionCreate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentSchemaVersionResponse:
    document = _get_accessible_document(db, document_id, user)
    _validate_schema(payload.schema_definition)
    version = DocumentSchemaVersion(
        document_id=document.id,
        owner_user_id=user.id,
        version_number=_next_version_number(db, document.id),
        title=_clean_title(payload.title, "自定义 schema"),
        source="user",
        prompt_text=payload.prompt_text.strip(),
        schema_json=_dump_schema(payload.schema_definition),
        is_active=False,
    )
    db.add(version)
    db.flush()
    if payload.activate or not _document_has_active_schema(db, document.id):
        _activate_version(db, document.id, version)
    db.commit()
    db.refresh(version)
    return _to_response(version)


@router.post("/system-template", response_model=DocumentSchemaVersionResponse)
def create_system_schema_template(
    document_id: int,
    payload: DocumentSchemaTemplateRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentSchemaVersionResponse:
    document = _get_accessible_document(db, document_id, user)
    template = _build_system_schema_template(document, payload.prompt_text)
    version = DocumentSchemaVersion(
        document_id=document.id,
        owner_user_id=user.id,
        version_number=_next_version_number(db, document.id),
        title=_clean_title(payload.title, "系统推荐 schema"),
        source="system",
        prompt_text=payload.prompt_text.strip(),
        schema_json=_dump_schema(template),
        is_active=False,
    )
    db.add(version)
    db.flush()
    if payload.activate or not _document_has_active_schema(db, document.id):
        _activate_version(db, document.id, version)
    db.commit()
    db.refresh(version)
    return _to_response(version)


@router.put("/{schema_id}", response_model=DocumentSchemaVersionResponse)
def update_document_schema_version(
    document_id: int,
    schema_id: int,
    payload: DocumentSchemaVersionUpdate,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentSchemaVersionResponse:
    document = _get_accessible_document(db, document_id, user)
    version = _get_schema_version(db, document.id, schema_id)
    if payload.title is not None:
        version.title = _clean_title(payload.title, version.title or "自定义 schema")
    if payload.prompt_text is not None:
        version.prompt_text = payload.prompt_text.strip()
    if payload.schema_definition is not None:
        _validate_schema(payload.schema_definition)
        version.schema_json = _dump_schema(payload.schema_definition)
        version.source = "user"
    version.updated_at = utc_now_naive()
    db.commit()
    db.refresh(version)
    return _to_response(version)


@router.post("/{schema_id}/activate", response_model=DocumentSchemaVersionResponse)
def activate_document_schema_version(
    document_id: int,
    schema_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentSchemaVersionResponse:
    document = _get_accessible_document(db, document_id, user)
    version = _get_schema_version(db, document.id, schema_id)
    _activate_version(db, document.id, version)
    db.commit()
    db.refresh(version)
    return _to_response(version)


@router.post("/{schema_id}/llm-rewrite", response_model=DocumentSchemaVersionResponse)
def rewrite_document_schema_with_llm(
    document_id: int,
    schema_id: int,
    payload: DocumentSchemaLlmRewriteRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> DocumentSchemaVersionResponse:
    document = _get_accessible_document(db, document_id, user)
    base_version = _get_schema_version(db, document.id, schema_id)
    instruction = _schema_rewrite_instruction(payload)
    if not instruction:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="请填写修改要求或选择一个快捷修改方向。",
        )

    try:
        result = llm_client.chat_completion_from_settings(
            db=db,
            user=user,
            provider=payload.provider,
            model_name=payload.model_name,
            temperature=0.2,
            max_tokens=4000,
            timeout_seconds=120,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是“书脉”的教材知识图谱 schema 设计助手。"
                        "你必须只返回一个 JSON 对象，不要输出 Markdown、解释、代码围栏或额外文字。"
                    ),
                },
                {
                    "role": "user",
                    "content": _build_schema_rewrite_prompt(document, base_version, instruction),
                },
            ],
        )
    except llm_client.LlmClientError as error:
        raise HTTPException(status_code=error.status_code, detail=error.message) from error

    rewritten_schema = _extract_schema_json(result["content"])
    _validate_schema(rewritten_schema)
    version = DocumentSchemaVersion(
        document_id=document.id,
        owner_user_id=user.id,
        version_number=_next_version_number(db, document.id),
        title=f"{base_version.title} · 模型修改",
        source="llm",
        prompt_text=instruction,
        schema_json=_dump_schema(rewritten_schema),
        is_active=False,
    )
    db.add(version)
    db.flush()
    if payload.activate:
        _activate_version(db, document.id, version)
    db.commit()
    db.refresh(version)
    return _to_response(version)


def _get_accessible_document(db: Session, document_id: int, user: User) -> Document:
    document = db.get(Document, document_id)
    if document is None or document.is_deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    get_accessible_knowledge_base(db, document.knowledge_base_id, user)
    if user.role != "admin" and document.owner_user_id != user.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return document


def _get_schema_version(db: Session, document_id: int, schema_id: int) -> DocumentSchemaVersion:
    version = db.get(DocumentSchemaVersion, schema_id)
    if version is None or version.document_id != document_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schema version not found.")
    return version


def _next_version_number(db: Session, document_id: int) -> int:
    current_max = db.scalar(
        select(func.max(DocumentSchemaVersion.version_number)).where(
            DocumentSchemaVersion.document_id == document_id
        )
    )
    return int(current_max or 0) + 1


def _document_has_active_schema(db: Session, document_id: int) -> bool:
    return db.scalar(
        select(DocumentSchemaVersion.id).where(
            DocumentSchemaVersion.document_id == document_id,
            DocumentSchemaVersion.is_active.is_(True),
        )
    ) is not None


def _activate_version(db: Session, document_id: int, version: DocumentSchemaVersion) -> None:
    for item in db.scalars(
        select(DocumentSchemaVersion).where(DocumentSchemaVersion.document_id == document_id)
    ):
        item.is_active = item.id == version.id


def _validate_schema(schema: dict[str, Any]) -> None:
    if not isinstance(schema, dict) or not schema:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Schema 必须是非空 JSON 对象。",
        )
    if not isinstance(schema.get("node_types", []), list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Schema 的 node_types 必须是列表。",
        )
    if not isinstance(schema.get("relation_types", []), list):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Schema 的 relation_types 必须是列表。",
        )


def _dump_schema(schema: dict[str, Any]) -> str:
    return json.dumps(schema, ensure_ascii=False, indent=2, sort_keys=True)


def _load_schema(text: str) -> dict[str, Any]:
    try:
        value = json.loads(text or "{}")
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _clean_title(value: str, fallback: str) -> str:
    title = value.strip()
    return title[:255] if title else fallback


def _to_response(version: DocumentSchemaVersion) -> DocumentSchemaVersionResponse:
    return DocumentSchemaVersionResponse(
        id=version.id,
        document_id=version.document_id,
        owner_user_id=version.owner_user_id,
        version_number=version.version_number,
        title=version.title,
        source=version.source,
        prompt_text=version.prompt_text,
        schema_definition=_load_schema(version.schema_json),
        is_active=version.is_active,
        created_at=version.created_at,
        updated_at=version.updated_at,
    )


def _build_system_schema_template(document: Document, prompt_text: str = "") -> dict[str, Any]:
    subject = document.subject or "general"
    return {
        "schema_version": "shumai.document_schema.v1",
        "metadata": {
            "document_id": document.id,
            "filename": document.filename,
            "subject": document.subject,
            "grade": document.grade,
            "publisher": document.publisher,
            "textbook": document.textbook,
            "textbook_version": document.textbook_version,
            "user_requirements": prompt_text.strip(),
        },
        "node_types": _default_node_types(subject),
        "relation_types": _default_relation_types(),
        "extraction_rules": [
            "优先抽取教材正文、章节标题、核心概念、实验活动、例题问题、图片说明和表格信息。",
            "不要把页眉页脚、目录噪声、版权信息和重复说明抽成核心节点。",
            "图片、表格和练习题应保留来源说明，并尽量关联到对应章节或知识点。",
            "节点名称应使用教材中的中文表达，避免直接使用内部英文枚举作为显示名。",
        ],
        "quality_constraints": [
            "避免重复节点，语义相同的知识点应合并。",
            "关系必须能被教材文本、图片或表格证据支持。",
            "无明确依据的关系不要强行抽取。",
            "优先保留可用于课堂讲解和问答引用的内容。",
        ],
    }


def _default_node_types(subject: str) -> list[dict[str, Any]]:
    base_types = [
        {"type": "chapter", "display_name": "章节", "description": "教材章节或小节标题"},
        {"type": "knowledge_point", "display_name": "知识点", "description": "可独立讲解的核心内容"},
        {"type": "concept", "display_name": "概念", "description": "定义、术语或关键概念"},
        {"type": "problem", "display_name": "问题", "description": "教材问题、例题、探究任务或练习"},
        {"type": "image", "display_name": "图片", "description": "教材插图、图示、地图、流程图等视觉证据"},
        {"type": "table", "display_name": "表格", "description": "教材表格或结构化对比信息"},
    ]
    subject_types = {
        "chemistry": [
            {"type": "substance", "display_name": "物质", "description": "化学物质、材料、溶液或混合物"},
            {"type": "experiment", "display_name": "实验", "description": "实验活动、实验现象和实验结论"},
            {"type": "reaction", "display_name": "反应", "description": "化学反应、转化过程或方程式"},
        ],
        "history": [
            {"type": "person", "display_name": "人物", "description": "历史人物或群体"},
            {"type": "event", "display_name": "事件", "description": "历史事件、制度变迁或社会活动"},
            {"type": "place", "display_name": "地点", "description": "国家、地区、遗址、城市或地理范围"},
        ],
    }
    return base_types + subject_types.get(subject, [])


def _schema_rewrite_instruction(payload: DocumentSchemaLlmRewriteRequest) -> str:
    preset_instructions = {
        "image": "强化图片、表格、地图、流程图等视觉材料的抽取规则，并让图片更容易关联到对应知识点。",
        "classroom": "面向课堂讲解优化 schema，突出重点、难点、易错点、例题和适合提问的知识点。",
        "dedupe": "减少重复节点、弱关系和无依据关系，强化合并规则与质量约束。",
        "exam": "面向考试复习优化 schema，突出考点、概念辨析、题目、答案依据和易错提醒。",
    }
    parts = []
    preset = preset_instructions.get(payload.preset.strip().lower())
    if preset:
        parts.append(preset)
    if payload.instruction.strip():
        parts.append(payload.instruction.strip())
    return "\n".join(parts).strip()


def _build_schema_rewrite_prompt(
    document: Document,
    base_version: DocumentSchemaVersion,
    instruction: str,
) -> str:
    return (
        "请基于当前 schema 生成一份修改后的新版 schema。\n"
        "要求：\n"
        "- 保持 JSON 顶层对象结构清晰。\n"
        "- 保留 schema_version、metadata、node_types、relation_types、extraction_rules、quality_constraints 等核心区域。\n"
        "- 字段名使用稳定英文标识，display_name、description 和规则说明使用中文。\n"
        "- 不要删除教材知识图谱抽取所必需的基础节点类型和关系类型。\n"
        "- 只返回 JSON 对象，不要输出任何解释。\n\n"
        f"文档信息：\n"
        f"- 文件名：{document.filename}\n"
        f"- 学科：{document.subject or '未填写'}\n"
        f"- 年级：{document.grade or '未填写'}\n"
        f"- 出版社：{document.publisher or '未填写'}\n"
        f"- 教材：{document.textbook or '未填写'}\n"
        f"- 教材版本：{document.textbook_version or '未填写'}\n\n"
        f"用户修改要求：\n{instruction}\n\n"
        f"当前 schema：\n{base_version.schema_json}"
    )


def _extract_schema_json(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="模型没有返回可解析的 schema JSON。",
            ) from exc
        try:
            value = json.loads(text[start : end + 1])
        except json.JSONDecodeError as nested_exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="模型返回的 schema JSON 格式不正确。",
            ) from nested_exc
    if not isinstance(value, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="模型返回的 schema 不是 JSON 对象。",
        )
    return value


def _default_relation_types() -> list[dict[str, Any]]:
    return [
        {"type": "belongs_to", "display_name": "属于", "description": "知识点、问题或图片归属到章节"},
        {"type": "explains", "display_name": "解释", "description": "概念、图片或表格解释某个知识点"},
        {"type": "supports", "display_name": "支持", "description": "证据支持某个结论或关系"},
        {"type": "classified_as", "display_name": "归类为", "description": "对象按照某标准归入类别"},
        {"type": "causes", "display_name": "导致", "description": "原因、条件和结果之间的关系"},
        {"type": "located_in", "display_name": "位于", "description": "人物、事件、遗址或对象所在地点"},
        {"type": "related_to", "display_name": "相关", "description": "有教材依据的弱关联关系"},
    ]
