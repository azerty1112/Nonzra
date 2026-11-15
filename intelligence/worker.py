"""العامل الخلفي الذاتي: يستهلك قائمة مهام ويعالجها تلقائيًا باستمرار."""

import asyncio
import uuid
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .orchestrator import AutoOrchestrator


def _log(msg: str) -> None:
    print(f"[AutoWorker] {msg}", flush=True)


@dataclass
class WorkerJob:
    job_id: str
    payload: Dict[str, Any]
    status: str = "queued"
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: Optional[str] = None


class AutoWorker:
    """عامل خلفي غير متزامن يعالج مهام الحل الذاتي بشكل مستمر وذاتي."""

    def __init__(self, orchestrator: AutoOrchestrator, concurrency: int = 2, max_concurrency: int = 8) -> None:
        self.orchestrator = orchestrator
        self.concurrency = concurrency
        self.max_concurrency = max_concurrency
        self.queue: "asyncio.Queue[str]" = asyncio.Queue()
        self.jobs: Dict[str, WorkerJob] = {}
        self._tasks: List["asyncio.Task[None]"] = []
        self._scale_task: Optional["asyncio.Task[None]"] = None
        self._running = False
        self.processed = 0
        self.failed = 0
        self.scale_events: List[Dict[str, Any]] = []

    def submit(self, payload: Dict[str, Any]) -> str:
        job_id = str(uuid.uuid4())
        self.jobs[job_id] = WorkerJob(job_id=job_id, payload=payload)
        self.queue.put_nowait(job_id)
        return job_id

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        for _ in range(self.concurrency):
            self._tasks.append(asyncio.create_task(self._loop()))
        self._scale_task = asyncio.create_task(self._scale_loop())

    async def stop(self) -> None:
        self._running = False
        if self._scale_task:
            self._scale_task.cancel()
        for t in self._tasks:
            t.cancel()
        self._tasks.clear()

    async def _scale_loop(self) -> None:
        while self._running:
            await asyncio.sleep(5)
            await self.auto_scale()

    async def auto_scale(self) -> None:
        """يُعّدل عدد العمال تلقائيًا حسب عمق الطابور."""
        qsize = self.queue.qsize()
        active = len([t for t in self._tasks if not t.done()])
        target = self.concurrency

        if qsize > active * 3 and self.concurrency < self.max_concurrency:
            self.concurrency += 1
            self._tasks.append(asyncio.create_task(self._loop()))
            self.scale_events.append({"at": time.time(), "action": "scale_up", "concurrency": self.concurrency, "queue": qsize})
            _log(f"التوسيع التلقائي: ↑ العمال إلى {self.concurrency} (الطابور: {qsize})")
        elif qsize < max(1, active // 2) and self.concurrency > 2:
            self.concurrency -= 1
            # لا نقتل المهام الجارية، فقط نمنع إنشاء مهام جديدة عند التوقف
            self.scale_events.append({"at": time.time(), "action": "scale_down", "concurrency": self.concurrency, "queue": qsize})
            _log(f"التوسيع التلقائي: ↓ العمال إلى {self.concurrency} (الطابور: {qsize})")

    async def _loop(self) -> None:
        while self._running:
            try:
                job_id = await asyncio.wait_for(self.queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break
            await self._process(job_id)

    async def _process(self, job_id: str) -> None:
        job = self.jobs.get(job_id)
        if not job:
            return
        job.status = "processing"
        try:
            result = await asyncio.to_thread(
                self.orchestrator.solve, **job.payload
            )
            job.result = result.to_dict()
            job.status = "completed" if result.result.success else "failed"
            self.processed += 1
            if not result.result.success:
                self.failed += 1
        except Exception as exc:  # noqa: BLE001
            job.status = "failed"
            job.error = str(exc)
            self.failed += 1
        finally:
            job.finished_at = datetime.now(timezone.utc).isoformat()

    def status(self, job_id: str) -> Optional[Dict[str, Any]]:
        job = self.jobs.get(job_id)
        if not job:
            return None
        return {
            "job_id": job.job_id,
            "status": job.status,
            "result": job.result,
            "error": job.error,
            "created_at": job.created_at,
            "finished_at": job.finished_at,
        }

    def snapshot(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "concurrency": self.concurrency,
            "max_concurrency": self.max_concurrency,
            "queued": self.queue.qsize(),
            "active_workers": len([t for t in self._tasks if not t.done()]),
            "processed": self.processed,
            "failed": self.failed,
            "jobs_tracked": len(self.jobs),
            "scale_events": self.scale_events[-10:],
        }


__all__ = ["WorkerJob", "AutoWorker"]
