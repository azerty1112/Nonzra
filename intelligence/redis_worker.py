"""عامل خلفي موزع باستخدام Redis للطابور والمشاركة بين عدة خوادم."""

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

try:
    import redis.asyncio as aioredis

    _REDIS_AVAILABLE = True
except Exception:  # noqa: BLE001
    _REDIS_AVAILABLE = False

    class aioredis:  # type: ignore[no-redef, misc]
        class Redis:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            async def close(self) -> None:
                pass

            async def xadd(self, *args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("Redis غير متوفر")

            async def xreadgroup(self, *args: Any, **kwargs: Any) -> Any:
                raise RuntimeError("Redis غير متوفر")

            async def xack(self, *args: Any, **kwargs: Any) -> Any:
                return 0

            async def llen(self, *args: Any, **kwargs: Any) -> int:
                return 0

            async def ping(self) -> bool:
                return False

from intelligence.orchestrator import AutoOrchestrator


@dataclass
class WorkerJob:
    job_id: str
    payload: Dict[str, Any]
    status: str = "queued"
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: Optional[str] = None
    worker_id: Optional[str] = None


class RedisAutoWorker:
    """عامل خلفي موزع يستخدم Redis Streams كطابور لمشاركة المهام بين عدة خوادم."""

    def __init__(
        self,
        orchestrator: AutoOrchestrator,
        redis_url: str = "redis://localhost:6379/0",
        stream_name: str = "nonecap:jobs",
        concurrency: int = 2,
        max_concurrency: int = 8,
        worker_id: Optional[str] = None,
        claim_idle_ms: int = 30000,
    ) -> None:
        if not _REDIS_AVAILABLE:
            raise RuntimeError("حزمة redis غير مثبتة. شغّل: pip install redis")
        self.orchestrator = orchestrator
        self.redis_url = redis_url
        self.stream_name = stream_name
        self.consumer_group = "nonecap:workers"
        self.concurrency = concurrency
        self.max_concurrency = max_concurrency
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.claim_idle_ms = claim_idle_ms
        self._redis: Optional[Any] = None
        self._tasks: List[asyncio.Task[None]] = []
        self._scale_task: Optional[asyncio.Task[None]] = None
        self._running = False
        self.processed = 0
        self.failed = 0
        self.scale_events: List[Dict[str, Any]] = []
        self.jobs: Dict[str, WorkerJob] = {}

    async def start(self) -> None:
        if self._running:
            return
        self._redis = aioredis.Redis.from_url(self.redis_url, decode_responses=True)
        await self._redis.ping()
        # إنشاء مجموعة المستهلكين إذا لم تكن موجودة
        try:
            await self._redis.xgroup_create(
                self.stream_name, self.consumer_group, id="0", mkstream=True
            )
        except Exception:  # noqa: BLE001
            # المجموعة موجودة بالفعل
            pass
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
        if self._redis:
            await self._redis.close()

    def submit(self, payload: Dict[str, Any]) -> str:
        job_id = str(uuid.uuid4())
        job = WorkerJob(job_id=job_id, payload=payload)
        self.jobs[job_id] = job
        if self._redis:
            asyncio.create_task(
                self._redis.xadd(
                    self.stream_name,
                    {
                        "job_id": job_id,
                        "payload": json.dumps(payload, ensure_ascii=False),
                        "created_at": job.created_at,
                    },
                )
            )
        return job_id

    async def _loop(self) -> None:
        assert self._redis is not None
        while self._running:
            try:
                messages = await self._redis.xreadgroup(
                    self.consumer_group,
                    self.worker_id,
                    {self.stream_name: ">"},
                    count=1,
                    block=2000,
                )
            except Exception:  # noqa: BLE001
                await asyncio.sleep(1)
                continue

            if not messages:
                # محاولة المطالبة بالمهام المتعثرة من عمال آخرين
                await self._claim_idle()
                continue

            for _stream, entries in messages:
                for message_id, fields in entries:
                    job_id = fields.get("job_id", "")
                    payload_str = fields.get("payload", "{}")
                    try:
                        payload = json.loads(payload_str)
                    except Exception:
                        payload = {}
                    await self._process(job_id, payload, message_id)

    async def _claim_idle(self) -> None:
        """المطالبة بالمهام التي تعطلت لدى عمال آخرين."""
        assert self._redis is not None
        try:
            pending = await self._redis.xpending(
                self.stream_name, self.consumer_group, min=self.claim_idle_ms, count=1
            )
        except Exception:
            return
        for entry in pending:
            message_id = entry[0]
            consumer = entry[1].decode() if isinstance(entry[1], bytes) else entry[1]
            if consumer == self.worker_id:
                continue
            await self._redis.xclaim(
                self.stream_name,
                self.consumer_group,
                self.worker_id,
                min_idle_time=self.claim_idle_ms,
                message_ids=[message_id],
            )

    async def _process(self, job_id: str, payload: Dict[str, Any], message_id: str) -> None:
        job = self.jobs.get(job_id)
        if not job:
            job = WorkerJob(job_id=job_id, payload=payload)
            self.jobs[job_id] = job
        job.status = "processing"
        job.worker_id = self.worker_id
        try:
            result = await asyncio.to_thread(self.orchestrator.solve, **payload)
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
            assert self._redis is not None
            await self._redis.xack(self.stream_name, self.consumer_group, message_id)

    async def _scale_loop(self) -> None:
        while self._running:
            await asyncio.sleep(5)
            await self.auto_scale()

    async def auto_scale(self) -> None:
        assert self._redis is not None
        qsize = await self._redis.xlen(self.stream_name)
        active = len([t for t in self._tasks if not t.done()])
        if qsize > active * 3 and self.concurrency < self.max_concurrency:
            self.concurrency += 1
            self._tasks.append(asyncio.create_task(self._loop()))
            self.scale_events.append(
                {"at": time.time(), "action": "scale_up", "concurrency": self.concurrency, "queue": qsize}
            )
        elif qsize < max(1, active // 2) and self.concurrency > 2:
            self.concurrency -= 1
            self.scale_events.append(
                {"at": time.time(), "action": "scale_down", "concurrency": self.concurrency, "queue": qsize}
            )

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
            "worker_id": job.worker_id,
        }

    def snapshot(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "worker_id": self.worker_id,
            "concurrency": self.concurrency,
            "max_concurrency": self.max_concurrency,
            "processed": self.processed,
            "failed": self.failed,
            "jobs_tracked": len(self.jobs),
            "scale_events": self.scale_events[-10:],
            "redis_available": _REDIS_AVAILABLE,
        }


__all__ = ["WorkerJob", "RedisAutoWorker"]
