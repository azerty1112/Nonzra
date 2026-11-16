"""نظام التحقق التلقائي المجدول (Scheduled Solving).

يتيح للمستخدمين جدولة حل الكبتشا بشكل تلقائي في أوقات محددة أو فترات دورية.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone, timedelta
from enum import Enum
import asyncio
import uuid
import time


class ScheduleType(str, Enum):
    """أنواع الجدولة."""
    INTERVAL = "interval"  # كل فترة زمنية محددة
    CRON = "cron"          # في أوقات محددة (مثل كل ساعة، كل يوم)
    ONCE = "once"          # مرة واحدة في وقت محدد


@dataclass
class ScheduledJob:
    """مهمة جدولة للتحل التلقائي."""
    job_id: str
    name: str
    captcha_type: str
    sitekey: Optional[str] = None
    url: Optional[str] = None
    action: Optional[str] = None
    cdata: Optional[str] = None
    image_url: Optional[str] = None
    schedule_type: ScheduleType = ScheduleType.INTERVAL
    interval_seconds: Optional[int] = None  # للفاصل الزمني
    cron_expression: Optional[str] = None   # للتوقيتات المجدولة
    next_run: Optional[str] = None          # وقت التشغيل التالي
    is_active: bool = True
    total_runs: int = 0
    successful_runs: int = 0
    failed_runs: int = 0
    created_at: str = field(default_factory=lambda: _now())
    last_run: Optional[str] = None
    last_result: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "name": self.name,
            "captcha_type": self.captcha_type,
            "sitekey": self.sitekey,
            "url": self.url,
            "action": self.action,
            "cdata": self.cdata,
            "image_url": self.image_url,
            "schedule_type": self.schedule_type.value,
            "interval_seconds": self.interval_seconds,
            "cron_expression": self.cron_expression,
            "next_run": self.next_run,
            "is_active": self.is_active,
            "total_runs": self.total_runs,
            "successful_runs": self.successful_runs,
            "failed_runs": self.failed_runs,
            "created_at": self.created_at,
            "last_run": self.last_run,
            "last_result": self.last_result,
        }


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _parse_interval(interval_str: str) -> int:
    """تحويل سلسلة زمنية إلى ثواني."""
    import re
    match = re.match(r"(\d+)\s*([smhd])", interval_str)
    if not match:
        raise ValueError("صيغة الوقت غير صالحة. استخدم: 60s, 5m, 2h, 1d")
    value = int(match.group(1))
    unit = match.group(2)
    multipliers = {"s": 1, "m": 60, "h": 3600, "d": 86400}
    return value * multipliers[unit]


class ScheduledJobManager:
    """مدير المهام المجدولة."""

    def __init__(self) -> None:
        self.jobs: Dict[str, ScheduledJob] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None

    def create_job(
        self,
        name: str,
        captcha_type: str,
        schedule_type: str = "interval",
        interval_seconds: Optional[int] = None,
        cron_expression: Optional[str] = None,
        sitekey: Optional[str] = None,
        url: Optional[str] = None,
        action: Optional[str] = None,
        cdata: Optional[str] = None,
        image_url: Optional[str] = None,
    ) -> ScheduledJob:
        """إنشاء مهمة مجدولة جديدة."""
        job_id = str(uuid.uuid4())
        now = datetime.now(timezone.utc)
        next_run = now

        schedule_type_enum = ScheduleType(schedule_type)

        if schedule_type_enum == ScheduleType.INTERVAL and interval_seconds:
            next_run = now + timedelta(seconds=interval_seconds)
        elif schedule_type_enum == ScheduleType.CRON and cron_expression:
            # بسيط - يمكن تحسينه لاحقًا
            next_run = now + timedelta(hours=1)

        job = ScheduledJob(
            job_id=job_id,
            name=name,
            captcha_type=captcha_type,
            sitekey=sitekey,
            url=url,
            action=action,
            cdata=cdata,
            image_url=image_url,
            schedule_type=schedule_type_enum,
            interval_seconds=interval_seconds,
            cron_expression=cron_expression,
            next_run=next_run.isoformat(),
        )

        self.jobs[job_id] = job
        return job

    def get_job(self, job_id: str) -> Optional[ScheduledJob]:
        """الحصول على مهمة مجدولة."""
        return self.jobs.get(job_id)

    def list_jobs(self) -> List[ScheduledJob]:
        """قائمة جميع المهام المجدولة."""
        return list(self.jobs.values())

    def update_job(
        self,
        job_id: str,
        is_active: Optional[bool] = None,
        interval_seconds: Optional[int] = None,
        cron_expression: Optional[str] = None,
    ) -> Optional[ScheduledJob]:
        """تحديث مهمة مجدولة."""
        job = self.jobs.get(job_id)
        if not job:
            return None

        if is_active is not None:
            job.is_active = is_active
        if interval_seconds is not None:
            job.interval_seconds = interval_seconds
            job.schedule_type = ScheduleType.INTERVAL
            job.next_run = (
                datetime.now(timezone.utc) + timedelta(seconds=interval_seconds)
            ).isoformat()
        if cron_expression is not None:
            job.cron_expression = cron_expression
            job.schedule_type = ScheduleType.CRON

        return job

    def delete_job(self, job_id: str) -> bool:
        """حذف مهمة مجدولة."""
        if job_id in self.jobs:
            del self.jobs[job_id]
            return True
        return False

    async def start_scheduler(self, orchestrator: Any) -> None:
        """بدء جدول المهام."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop(orchestrator))

    async def stop_scheduler(self) -> None:
        """إيقاف جدول المهام."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None

    async def _scheduler_loop(self, orchestrator: Any) -> None:
        """حلقة الجدولة الرئيسية."""
        while self._running:
            now = datetime.now(timezone.utc)
            jobs_to_run = []

            for job in self.jobs.values():
                if not job.is_active:
                    continue
                if job.next_run:
                    next_run = datetime.fromisoformat(job.next_run)
                    if now >= next_run:
                        jobs_to_run.append(job)

            for job in jobs_to_run:
                try:
                    await self._execute_job(orchestrator, job)
                except Exception as exc:  # noqa: BLE001
                    print(f"خطأ في تنفيذ المهمة {job.job_id}: {exc}")

            await asyncio.sleep(10)  # التحقق كل 10 ثوان

    async def _execute_job(self, orchestrator: Any, job: ScheduledJob) -> None:
        """تنفيذ مهمة مجدولة."""
        import httpx

        job.total_runs += 1
        job.last_run = _now()

        try:
            result = await asyncio.to_thread(
                orchestrator.solve,
                captcha_type=job.captcha_type,
                image_url=job.image_url,
                sitekey=job.sitekey,
                url=job.url,
                action=job.action,
                cdata=job.cdata,
            )

            if result.success:
                job.successful_runs += 1
            else:
                job.failed_runs += 1

            job.last_result = result.to_dict()

            # حساب وقت التشغيل التالي
            if job.interval_seconds:
                job.next_run = (
                    datetime.now(timezone.utc) + timedelta(seconds=job.interval_seconds)
                ).isoformat()

        except Exception as exc:  # noqa: BLE001
            job.failed_runs += 1
            job.last_result = {"success": False, "error": str(exc)}


# مثيل واحد من مدير المهام المجدولة
scheduled_job_manager = ScheduledJobManager()


__all__ = [
    "ScheduleType",
    "ScheduledJob",
    "ScheduledJobManager",
    "scheduled_job_manager",
    "_parse_interval",
]
