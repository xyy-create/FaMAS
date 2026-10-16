from __future__ import annotations

from collections.abc import Callable
from threading import Event, Thread

from sqlalchemy import select, update

from app.core.time import utc_now_naive
from app.db.session import SessionLocal
from app.models.document import Document
from app.models.processing_job import ProcessingJob
from app.services.pipeline_runner import PIPELINE_STAGE_STOP_AT, run_document_pipeline

PipelineRunner = Callable[[int], None]


class PipelineJobWorker:
    def __init__(self, *, interval_seconds: float = 2.0, concurrency: int = 1) -> None:
        self.interval_seconds = interval_seconds
        self.concurrency = max(1, concurrency)
        self._stop_event = Event()
        self._threads: list[Thread] = []

    def start(self) -> None:
        if any(thread.is_alive() for thread in self._threads):
            return
        self._stop_event.clear()
        self._threads = [
            Thread(
                target=self._run,
                name=f"famas-pipeline-worker-{index + 1}",
                daemon=True,
            )
            for index in range(self.concurrency)
        ]
        for thread in self._threads:
            thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        for thread in self._threads:
            if thread.is_alive():
                thread.join(timeout=max(1.0, self.interval_seconds + 1.0))

    def _run(self) -> None:
        while not self._stop_event.is_set():
            try:
                if process_next_pending_pipeline_job():
                    continue
            except Exception:
                pass
            self._stop_event.wait(self.interval_seconds)


def process_next_pending_pipeline_job(
    runner: PipelineRunner = run_document_pipeline,
    session_factory: Callable[[], object] = SessionLocal,
) -> bool:
    job_id = claim_next_pending_pipeline_job(session_factory=session_factory)
    if job_id is None:
        return False

    runner(job_id)
    return True


def claim_next_pending_pipeline_job(
    session_factory: Callable[[], object] = SessionLocal,
) -> int | None:
    with session_factory() as db:
        pending_job_ids = list(
            db.scalars(
                select(ProcessingJob.id)
                .where(
                    ProcessingJob.stage.in_(PIPELINE_STAGE_STOP_AT),
                    ProcessingJob.status == "pending",
                )
                .order_by(ProcessingJob.created_at.asc(), ProcessingJob.id.asc())
                .limit(10)
            )
        )

        for job_id in pending_job_ids:
            started_at = utc_now_naive()
            result = db.execute(
                update(ProcessingJob)
                .where(
                    ProcessingJob.id == job_id,
                    ProcessingJob.status == "pending",
                )
                .values(status="running", started_at=started_at)
            )
            if result.rowcount != 1:
                db.rollback()
                continue

            job = db.get(ProcessingJob, job_id)
            if job is not None:
                document = db.get(Document, job.document_id)
                if document is not None:
                    document.status = f"{job.stage}_running"
                    document.processing_started_at = started_at
            db.commit()
            return job_id

        return None
