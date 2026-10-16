from __future__ import annotations

import json
import sys

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
import app.main as main_module


def test_readiness_check_reports_ok(
    db_session_factory: sessionmaker[Session],
    monkeypatch,
    runtime_dir,
) -> None:
    frontend_dist = runtime_dir / "frontend_dist"
    frontend_dist.mkdir(parents=True)
    (frontend_dist / "index.html").write_text("<!doctype html>", encoding="utf-8")

    monkeypatch.setattr(main_module, "SessionLocal", db_session_factory)
    monkeypatch.setattr(main_module, "frontend_dist", frontend_dist)
    monkeypatch.setattr(settings, "storage_dir", runtime_dir / "storage")
    monkeypatch.setattr(settings, "pipeline_mock", False)
    monkeypatch.setattr(settings, "pipeline_python", sys.executable)

    response = main_module.readiness_check()
    payload = json.loads(response.body)

    assert response.status_code == 200
    assert payload["status"] == "ok"
    assert payload["checks"] == {
        "database": "ok",
        "storage": "ok",
        "frontend": "ok",
        "pipeline_python": "ok",
    }


def test_readiness_check_fails_when_frontend_build_is_missing(
    db_session_factory: sessionmaker[Session],
    monkeypatch,
    runtime_dir,
) -> None:
    monkeypatch.setattr(main_module, "SessionLocal", db_session_factory)
    monkeypatch.setattr(main_module, "frontend_dist", runtime_dir / "missing_dist")
    monkeypatch.setattr(settings, "storage_dir", runtime_dir / "storage")
    monkeypatch.setattr(settings, "pipeline_mock", False)
    monkeypatch.setattr(settings, "pipeline_python", sys.executable)

    response = main_module.readiness_check()
    payload = json.loads(response.body)

    assert response.status_code == 503
    assert payload["status"] == "error"
    assert payload["checks"]["frontend"] == "missing"
