from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import logging
from pathlib import Path
from sqlalchemy import text

from app.api.routes.api_settings import router as api_settings_router
from app.api.routes.auth import router as auth_router
from app.api.routes.documents import router as documents_router
from app.api.routes.document_schemas import router as document_schemas_router
from app.api.routes.knowledge_graph import router as knowledge_graph_router
from app.api.routes.knowledge_bases import router as knowledge_bases_router
from app.api.routes.retrieval import router as retrieval_router
from app.api.routes.system_settings import router as system_settings_router
from app.api.routes.users import router as users_router
from app.core.config import settings
from app.core.runtime_security import validate_runtime_security_config
from app.db.session import SessionLocal, init_db
from app.db.seed import seed_initial_data
from app.services.job_worker import PipelineJobWorker
from app.services.pipeline_runner import recover_interrupted_pipeline_jobs


logger = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    worker: PipelineJobWorker | None = None
    validate_runtime_security_config(settings)
    init_db()
    with SessionLocal() as db:
        seed_initial_data(db)
        recover_interrupted_pipeline_jobs(db)
    if settings.pipeline_worker_enabled:
        worker = PipelineJobWorker(
            interval_seconds=settings.pipeline_worker_interval_seconds,
            concurrency=settings.pipeline_worker_concurrency,
        )
        worker.start()
    logger.info(
        "FaMAS web server ready at http://127.0.0.1:8000; pipeline worker concurrency=%s",
        settings.pipeline_worker_concurrency if settings.pipeline_worker_enabled else 0,
    )
    try:
        yield
    finally:
        if worker is not None:
            worker.stop()


app = FastAPI(title="FaMAS Web API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_settings_router)
app.include_router(auth_router)
app.include_router(documents_router)
app.include_router(document_schemas_router)
app.include_router(knowledge_graph_router)
app.include_router(knowledge_bases_router)
app.include_router(retrieval_router)
app.include_router(system_settings_router)
app.include_router(users_router)

frontend_dist = settings.web_dir / "frontend" / "dist"


class CacheAwareStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):  # type: ignore[override]
        response = await super().get_response(path, scope)
        if response.status_code != 200:
            return response

        cache_control = _cache_control_for_static_path(path)
        response.headers["Cache-Control"] = cache_control
        if cache_control.startswith("no-cache"):
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response


def _cache_control_for_static_path(path: str) -> str:
    normalized = path.replace("\\", "/").lstrip("/")
    if normalized.endswith(".html"):
        return "no-cache, no-store, must-revalidate"
    if normalized.startswith("assets/") and _looks_hashed_asset(normalized):
        return "public, max-age=31536000, immutable"
    return "no-cache"


def _looks_hashed_asset(path: str) -> bool:
    filename = Path(path).name
    stem = Path(filename).stem
    return "-" in stem


@app.get("/api/health")
def health_check() -> dict[str, str]:
    database = "ok"
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:
        database = "error"

    return {"status": "ok", "service": "famas-web-api", "database": database}


@app.get("/api/health/ready")
def readiness_check() -> JSONResponse:
    report = _readiness_report()
    status_code = 200 if report["status"] == "ok" else 503
    return JSONResponse(report, status_code=status_code)


def _readiness_report() -> dict[str, object]:
    checks = {
        "database": _database_readiness(),
        "storage": _storage_readiness(),
        "frontend": _frontend_readiness(),
        "pipeline_python": _pipeline_python_readiness(),
    }
    blocking_states = {"error", "missing"}
    status = "error" if any(value in blocking_states for value in checks.values()) else "ok"
    return {
        "status": status,
        "service": "famas-web-api",
        "runtime_mode": settings.runtime_mode,
        "checks": checks,
    }


def _database_readiness() -> str:
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
    except Exception:
        return "error"
    return "ok"


def _storage_readiness() -> str:
    probe_path = settings.storage_dir / ".readiness-write-test"
    try:
        settings.storage_dir.mkdir(parents=True, exist_ok=True)
        probe_path.write_text("ok", encoding="ascii")
        probe_path.unlink(missing_ok=True)
    except Exception:
        return "error"
    return "ok"


def _frontend_readiness() -> str:
    if (frontend_dist / "index.html").exists():
        return "ok"
    return "missing"


def _pipeline_python_readiness() -> str:
    if settings.pipeline_mock:
        return "disabled"
    if not settings.pipeline_python:
        return "missing"
    if Path(settings.pipeline_python).exists():
        return "ok"
    if settings.pipeline_python == "python":
        return "ok"
    return "missing"


if frontend_dist.exists():
    app.mount("/", CacheAwareStaticFiles(directory=frontend_dist, html=True), name="frontend")
else:

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    def frontend_not_built() -> str:
        return (
            "<h1>FaMAS Web API is running</h1>"
            "<p>Build the frontend with <code>npm run build</code> in web/frontend "
            "to serve the web app from this backend.</p>"
        )
