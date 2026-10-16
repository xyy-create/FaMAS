from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
FRONTEND_ROOT = PROJECT_ROOT / "web" / "frontend"

UI_SOURCE_GLOBS = [
    "index.html",
    "src/**/*.vue",
    "src/**/*.js",
    "public/chemistry/index.html",
    "public/chemistry/app.js",
]

MOJIBAKE_MARKERS = [
    "�",
    "鍥",
    "鐭",
    "閫",
    "瀵",
    "鏂",
    "妯",
    "绠",
    "娑",
    "顓",
    "惌",
    "鎼",
]

FORBIDDEN_VISIBLE_ENGLISH = [
    "Default KB",
    "<title>frontend</title>",
    'lang="en"',
    "Request failed with status",
    "Request failed with a network error.",
    "Retrying chunk",
    'title="Clear focus"',
    "Switch to English",
]


def _ui_source_files() -> list[Path]:
    files: list[Path] = []
    for pattern in UI_SOURCE_GLOBS:
        files.extend(FRONTEND_ROOT.glob(pattern))
    return sorted(path for path in files if path.is_file())


def test_frontend_ui_sources_do_not_contain_mojibake() -> None:
    failures: list[str] = []
    for path in _ui_source_files():
        text = path.read_text(encoding="utf-8-sig")
        for marker in MOJIBAKE_MARKERS:
            if marker in text:
                failures.append(f"{path.relative_to(PROJECT_ROOT)} contains mojibake marker {marker!r}")

    assert failures == []


def test_frontend_ui_sources_do_not_regress_to_known_english_fallbacks() -> None:
    failures: list[str] = []
    for path in _ui_source_files():
        text = path.read_text(encoding="utf-8-sig")
        for marker in FORBIDDEN_VISIBLE_ENGLISH:
            if marker in text:
                failures.append(f"{path.relative_to(PROJECT_ROOT)} contains visible fallback {marker!r}")

    assert failures == []


def test_raw_status_values_are_rendered_with_labels() -> None:
    documents_page = (FRONTEND_ROOT / "src" / "pages" / "DocumentsPage.vue").read_text(encoding="utf-8-sig")
    settings_page = (FRONTEND_ROOT / "src" / "pages" / "SettingsPage.vue").read_text(encoding="utf-8-sig")
    retrieval_page = (FRONTEND_ROOT / "src" / "pages" / "RetrievalPage.vue").read_text(encoding="utf-8-sig")

    assert "{{ documentStatusLabel(document.status) }}" in documents_page
    assert "{{ roleLabel(systemSettings?.admin?.role) }}" in settings_page
    assert "{{ approvalStatusLabel(systemSettings?.admin?.approval_status) }}" in settings_page
    assert "{{ documentStatusLabel(source.status) }}" in retrieval_page


def test_qa_evidence_uses_chinese_display_helpers() -> None:
    retrieval_page = (FRONTEND_ROOT / "src" / "pages" / "RetrievalPage.vue").read_text(encoding="utf-8-sig")

    assert "{{ evidenceKindLabel(evidence) }}" in retrieval_page
    assert "{{ evidenceKindLabel(activeEvidence.item) }}" in retrieval_page
    assert "{{ evidenceMessage(message.citations) }}" in retrieval_page
    assert "{{ nodeTitle(node) }}" in retrieval_page
    assert "{{ nodeDescription(node) }}" in retrieval_page
    assert "{{ node.title }}" not in retrieval_page
    assert "{{ node.description }}" not in retrieval_page
    assert "{{ evidence.kind }}" not in retrieval_page


def test_graph_viewer_zh_mode_does_not_fallback_to_english_labels() -> None:
    viewer = (FRONTEND_ROOT / "public" / "chemistry" / "app.js").read_text(encoding="utf-8-sig")

    assert 'return I18N.zh.typeLabels?.[type] || displayValueLabels[type] || "节点";' in viewer
    assert 'return I18N.zh.predicateLabels?.[predicate] || displayValueLabels[predicate] || "关系";' in viewer
    assert 'return I18N.zh.fieldNames?.[key] || displayValueLabels[key] || "字段";' in viewer
    assert "function displayText(value)" in viewer
    assert ".map(displayText).filter(Boolean)" in viewer
