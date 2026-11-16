"""سيرفر API متكامل لحل الكبتشا (FastAPI)."""

import base64
import json
import uuid
import time
import re
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone

from fastapi import FastAPI, File, Form, UploadFile, HTTPException, WebSocket, WebSocketDisconnect, Depends, Query, Request, Body
from fastapi.responses import JSONResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field
import httpx

from intelligence import (
    SolveEvent,
    SolveDecision,
    IntelligentMonitor,
    CaptchaAnalyzer,
    IntelligentSolverStrategy,
    HumanBehavior,
    AutoDetector,
    AdaptiveTuner,
    LearningEngine,
    AutoOrchestrator,
    AutoWorker,
    KnowledgeBase,
    ExperienceEngine,
)

from api_server.auth import (
    api_key_store,
    hash_api_key,
    generate_api_key,
    extract_api_key,
    ApiKeyStore,
)
from api_server.webhooks import webhook_deliverer
from api_server.auth_rbac import (
    UserRole,
    User,
    UserManager,
    user_manager,
    require_role,
)
from api_server.scheduler import (
    ScheduleType,
    ScheduledJob,
    ScheduledJobManager,
    scheduled_job_manager,
    _parse_interval,
)
from api_server.audit import audit_logger, audit_log
from api_server.backup import BackupManager, backup_manager

from solver_engine import (
    registry,
    CaptchaType,
    SolverResult,
    ImageSolveConfig,
    Database,
    configure_hcaptcha_external,
    get_hcaptcha_service_stats,
)
from solver_engine.db import encrypt_value, decrypt_value

from intelligence.training import CaptchaDataset
from intelligence.self_improver import SelfImprover

try:
    from slowapi import Limiter
    from slowapi.util import get_remote_address

    _SLOWAPI_AVAILABLE = True
except Exception:  # noqa: BLE001
    _SLOWAPI_AVAILABLE = False

    class Limiter:  # type: ignore[no-redef]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def limit(self, *args: Any, **kwargs: Any) -> Any:
            def deco(func: Any) -> Any:
                return func

            return deco

    def get_remote_address(*args: Any, **kwargs: Any) -> str:  # type: ignore[no-redef]
        return "local"

try:
    from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST
    from fastapi.responses import Response

    _PROM_AVAILABLE = True
    SOLVE_COUNT = Counter("nonecap_solve_total", "عدد محاولات الحل", ["captcha_type", "success"])
    SOLVE_LATENCY = Histogram("nonecap_solve_latency_seconds", "زمن الحل", ["captcha_type"])
except Exception:  # noqa: BLE001
    _PROM_AVAILABLE = False

    class Counter:  # type: ignore[no-redef, misc]
        def labels(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[return-value]
            return self

        def inc(self, *args: Any, **kwargs: Any) -> None:
            pass

    class Histogram:  # type: ignore[no-redef, misc]
        def labels(self, *args: Any, **kwargs: Any) -> Any:  # type: ignore[return-value]
            return self

        def observe(self, *args: Any, **kwargs: Any) -> None:
            pass

    SOLVE_COUNT = Counter()  # type: ignore[assignment, call-arg]
    SOLVE_LATENCY = Histogram()  # type: ignore[assignment, call-arg]

    class Response:  # type: ignore[no-redef, misc]
        pass

    def generate_latest() -> bytes:  # type: ignore[no-redef, misc]
        return b""

    CONTENT_TYPE_LATEST = "text/plain"

from solver_engine import (
    registry,
    CaptchaType,
    SolverResult,
    ImageSolveConfig,
    Database,
    configure_hcaptcha_external,
)

limiter = Limiter(key_func=get_remote_address)

security = HTTPBearer(auto_error=False)
db = Database()
monitor = IntelligentMonitor()
analyzer = CaptchaAnalyzer()
strategy = IntelligentSolverStrategy()
human_behavior = HumanBehavior()

# --------- الطبقة الذاتية ----------
detector = AutoDetector()
tuner = AdaptiveTuner()
learner = LearningEngine()

# قاعدة المعرفة المشتركة
knowledge_base = KnowledgeBase()
experience_engine = ExperienceEngine(knowledge_base=knowledge_base)

orchestrator = AutoOrchestrator(
    registry=registry,
    monitor=monitor,
    analyzer=analyzer,
    strategy=strategy,
    tuner=tuner,
    learner=learner,
    detector=detector,
    knowledge_base=knowledge_base,
    experience=experience_engine,
)
worker = AutoWorker(orchestrator=orchestrator, concurrency=2)

# --------- التحسين الذاتي ----------
training_dataset = CaptchaDataset()
self_improver = SelfImprover(dataset=training_dataset)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await worker.start()
    await scheduled_job_manager.start_scheduler(orchestrator)
    try:
        yield
    finally:
        await scheduled_job_manager.stop_scheduler()
        await worker.stop()


app = FastAPI(
    title="NoneCap Clone API",
    version="0.5.0",
    lifespan=lifespan,
    description="""
    # NoneCap Clone API

    إطار عمل مفتوح المصدر ومُستضاف ذاتيًا لحل الكبتشا تلقائيًا.

    ## الميزات الرئيسية

    * **حل الكبتشا التلقائي**: دعم جميع أنواع الكبتشا (صورة، hCaptcha، reCAPTCHA، Turnstile، Drag، Point)
    * **الذكاء الاصطناعي**: طبقة ذكاء متكاملة مع تعلّم ذاتي وتحليل صعوبة
    * **أمان متقدم**: مفاتيح API مع تشفير، حظر عناوين IP، معدل طلب متحرك
    * **مراقبة ذكية**: تنبيهات تلقائية عبر ديسكورد والويب هوك
    * **واجهة ويب احترافية**: لوحة تحكم واحدة-page مع إحصائيات مباشرة
    * **حل جماعي**: معالجة دفعات من الكبتشا مع تتبع الحالة
    * **تدريب ذاتي**: نموذج CNN للتعلم من الحلول الناجحة

    ## المصادقة

    معظم النقاط تتطلب مفتاح API. يمكن الحصول على مفتاح عبر نقطة `/api/keys`.

    ## حدود المعدل

    يتم تطبيق حد 120 طلب في الدقيقة لكل عنوان IP.
    """,
    contact={
        "name": "NoneCap Clone Support",
        "url": "https://github.com/azerty1112/Nonzra",
    },
    license_info={
        "name": "MIT License",
        "url": "https://opensource.org/licenses/MIT",
    },
    openapi_tags=[
        {"name": "solving", "description": "حل الكبتشا بأنواعه المختلفة"},
        {"name": "auto", "description": "الحل الذاتي الكامل مع الكشف التلقائي"},
        {"name": "bulk", "description": "الحل الجماعي للدفعات"},
        {"name": "keys", "description": "إدارة مفاتيح API"},
        {"name": "monitoring", "description": "المراقبة الذكية والإحصائيات"},
        {"name": "intelligence", "description": "الطبقة الذكية والتعلّم الذاتي"},
        {"name": "system", "description": "نقاط نهاية النظام (الحالة، الإحصائيات، إلخ)"},
    ],
)
app.state.limiter = limiter

# قاعدة بيانات آمنة مع تشفير مفاتيح API
secure_db = Database()

# خدمة الملفات الثابتة للوحة الويب
app.mount("/static", StaticFiles(directory="web/static"), name="static")


# --------- نظام أمان IP ومعدل طلب متحرك ----------

_IP_BLOCK_LIST: Dict[str, float] = {}
_REQUEST_TIMESTAMPS: Dict[str, List[float]] = {}
MAX_REQUESTS_PER_MINUTE = 120
BLOCK_DURATION_SECONDS = 300  # 5 دقائق


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_ip_blocked(ip: str) -> bool:
    if ip in _IP_BLOCK_LIST:
        if time.time() - _IP_BLOCK_LIST[ip] < BLOCK_DURATION_SECONDS:
            return True
        del _IP_BLOCK_LIST[ip]
    return False


def _block_ip(ip: str) -> None:
    _IP_BLOCK_LIST[ip] = time.time()


def _check_rate_limit(ip: str) -> bool:
    now = time.time()
    timestamps = _REQUEST_TIMESTAMPS.get(ip, [])
    # احتفظ فقط بطلبات الدقيقة الأخيرة
    timestamps = [t for t in timestamps if now - t < 60.0]
    if len(timestamps) >= MAX_REQUESTS_PER_MINUTE:
        _block_ip(ip)
        return False
    timestamps.append(now)
    _REQUEST_TIMESTAMPS[ip] = timestamps
    return True


@app.middleware("http")
async def security_middleware(request: Request, call_next: Any) -> Any:
    ip = _get_client_ip(request)
    if _is_ip_blocked(ip):
        return JSONResponse(
            status_code=429,
            content={"error": "تم حظر عنوان IP الخاص بك مؤقتًا بسبب عدد الطلبات الكبير"},
        )
    if not _check_rate_limit(ip):
        return JSONResponse(
            status_code=429,
            content={"error": "تم تجاوز الحد المسموح للطلبات في الدقيقة"},
        )
    response = await call_next(request)
    return response


@app.get("/web", response_class=HTMLResponse)
async def web_dashboard() -> Any:
    return FileResponse("web/templates/dashboard.html")

# --------- نظام التقدم الفوري ----------
JOB_PROGRESS: Dict[str, "JobProgress"] = {}


# مهام غير متزامنة قيد ejecución (للحصول على نتيجة الحل)
JOBS: Dict[str, Dict[str, Any]] = {}
# WebSocket العملاء المرتبطين بكل وظيفة (للتوافق مع النظام القديم)
JOB_SUBSCRIBERS: Dict[str, list] = {}


class JobProgress:
    """تتبع تقدم مهمة الحل مع تحديثات فورية."""

    def __init__(self, job_id: str) -> None:
        self.job_id = job_id
        self.status: str = "queued"
        self.progress: int = 0
        self.current_step: str = "في الانتظار"
        self.step_details: List[Dict[str, Any]] = []
        self.result: Optional[Dict[str, Any]] = None
        self.error: Optional[str] = None
        self.created_at: str = _now()
        self.finished_at: Optional[str] = None
        self.subscribers: List[WebSocket] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "status": self.status,
            "progress": self.progress,
            "current_step": self.current_step,
            "step_details": self.step_details,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }

    def add_step(self, step_name: str, details: Optional[Dict[str, Any]] = None, progress: Optional[int] = None) -> None:
        """إضافة خطوة تقدم جديدة."""
        step: Dict[str, Any] = {
            "step": step_name,
            "timestamp": _now(),
            "details": details or {},
        }
        if progress is not None:
            self.progress = progress
            step_progress: int = progress
            step["progress"] = step_progress
        self.step_details.append(step)
        self.current_step = step_name
        # إرسال التحديث لجميع المشتركين
        payload = {
            "job_id": self.job_id,
            "status": self.status,
            "progress": self.progress,
            "current_step": step_name,
            "step": step,
        }
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._publish_progress(payload))
        except Exception:  # noqa: BLE001
            pass

    async def _publish_progress(self, payload: Dict[str, Any]) -> None:
        """نشر التقدم للعملاء المتصلين عبر WebSocket."""
        for ws in list(self.subscribers):
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001
                if ws in self.subscribers:
                    self.subscribers.remove(ws)

    def set_result(self, result: Dict[str, Any], success: bool) -> None:
        """تعيين نتيجة الحل."""
        self.result = result
        self.status = "completed" if success else "failed"
        self.progress = 100
        self.finished_at = _now()
        payload = {
            "job_id": self.job_id,
            "status": self.status,
            "progress": self.progress,
            "current_step": self.current_step,
            "result": result,
            "error": self.error,
            "finished_at": self.finished_at,
        }
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._publish_progress(payload))
        except Exception:  # noqa: BLE001
            pass

    def set_error(self, error: str) -> None:
        """تعيين خطأ في الحل."""
        self.error = error
        self.status = "failed"
        self.progress = 100
        self.finished_at = _now()
        payload = {
            "job_id": self.job_id,
            "status": self.status,
            "progress": self.progress,
            "current_step": self.current_step,
            "error": error,
            "finished_at": self.finished_at,
        }
        import asyncio

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self._publish_progress(payload))
        except Exception:  # noqa: BLE001
            pass


def get_or_create_job_progress(job_id: str) -> JobProgress:
    """الحصول على أو إنشاء كائن تقدم المهمة."""
    if job_id not in JOB_PROGRESS:
        JOB_PROGRESS[job_id] = JobProgress(job_id)
    return JOB_PROGRESS[job_id]


def cleanup_old_jobs(max_age_hours: int = 24) -> None:
    """تنظيف الوظائف القديمة من الذاكرة."""
    now = time.time()
    to_remove = []
    for job_id, job in JOB_PROGRESS.items():
        created = datetime.fromisoformat(job.created_at)
        age_hours = (datetime.now(timezone.utc) - created).total_seconds() / 3600
        if age_hours > max_age_hours:
            to_remove.append(job_id)
    for job_id in to_remove:
        del JOB_PROGRESS[job_id]
        if job_id in JOBS:
            del JOBS[job_id]
        if job_id in JOB_SUBSCRIBERS:
            del JOB_SUBSCRIBERS[job_id]




def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class BaseSolveRequest(BaseModel):
    sitekey: Optional[str] = None
    url: Optional[str] = None
    action: Optional[str] = None
    cdata: Optional[str] = None
    target_color: Optional[str] = None
    min_area: int = 20
    image_b64: Optional[str] = None
    template_b64: Optional[str] = None
    psm: int = 7
    oem: int = 3
    whitelist: Optional[str] = None
    preprocess: bool = True
    resize_width: int = 400
    threshold: str = "otsu"
    human_like: bool = False
    callback_url: Optional[str] = None


class SolveResponse(BaseModel):
    job_id: str
    status: str
    result: Optional[SolverResult] = None
    created_at: str
    analysis: Optional[Dict[str, Any]] = None
    alerts: List[Dict[str, Any]] = []
    strategy_used: Optional[str] = None


async def _publish(job_id: str, payload: Dict[str, Any]) -> None:
    for ws in list(JOB_SUBSCRIBERS.get(job_id, [])):
        try:
            await ws.send_json(payload)
        except Exception:
            JOB_SUBSCRIBERS[job_id].remove(ws)


async def _run_job(
    job_id: str,
    captcha_type: CaptchaType,
    kwargs: Dict[str, Any],
    decision: Optional[SolveDecision] = None,
) -> None:
    """تشغيل مهمة الحل مع تتبع التقدم الفوري عبر WebSocket."""
    progress = get_or_create_job_progress(job_id)
    callback_url = kwargs.pop("callback_url", None)

    # مرحلة 1: بدء المعالجة
    progress.status = "processing"
    progress.add_step("البدء", {"captcha_type": captcha_type.value}, progress=10)
    await _publish(
        job_id,
        {
            "job_id": job_id,
            "status": "processing",
            "progress": progress.progress,
            "current_step": progress.current_step,
            "step_details": progress.step_details,
        },
    )

    # مرحلة 2: التحليل الذكي
    progress.add_step("التحليل الذكي", {"type": captcha_type.value}, progress=20)
    await _publish(
        job_id,
        {
            "job_id": job_id,
            "status": "processing",
            "progress": progress.progress,
            "current_step": progress.current_step,
            "step_details": progress.step_details,
        },
    )

    try:
        # مرحلة 3: تطبيق الاستراتيجية
        progress.add_step(
            "تطبيق الاستراتيجية",
            {
                "strategy": decision.strategy if decision else "default",
                "use_local": decision.use_local if decision else True,
            },
            progress=40,
        )
        await _publish(
            job_id,
            {
                "job_id": job_id,
                "status": "processing",
                "progress": progress.progress,
                "current_step": progress.current_step,
                "step_details": progress.step_details,
            },
        )

        if decision is not None and decision.strategy == "ensemble_with_fallback":
            solvers = registry.get_solvers(captcha_type)
            result = strategy.ensemble_solve(solvers, captcha_type, **kwargs)
        else:
            use_local = decision.use_local if decision else True
            result = await registry.solve_async(
                captcha_type, prefer_local=use_local, **kwargs
            )

        # مرحلة 4: إنهاء الحل
        progress.add_step(
            "إنهاء الحل",
            {
                "success": result.success,
                "confidence": result.confidence,
                "response_time_ms": result.response_time_ms,
            },
            progress=80,
        )
        await _publish(
            job_id,
            {
                "job_id": job_id,
                "status": "processing",
                "progress": progress.progress,
                "current_step": progress.current_step,
                "step_details": progress.step_details,
            },
        )

        JOBS[job_id]["status"] = "completed" if result.success else "failed"
        JOBS[job_id]["result"] = result.to_dict()
        JOBS[job_id]["finished_at"] = _now()
        db.record_attempt(
            captcha_type=captcha_type.value,
            success=result.success,
            confidence=result.confidence,
            response_time_ms=result.response_time_ms,
            error=result.error,
        )
        # --------- المراقبة الذكية ----------
        event = SolveEvent(
            timestamp=_now(),
            captcha_type=captcha_type.value,
            success=result.success,
            response_time_ms=result.response_time_ms,
            confidence=result.confidence,
            strategy=(decision.strategy if decision else "default"),
            error=result.error,
        )
        new_alerts = monitor.record(event)
        JOBS[job_id]["alerts"] = [a.__dict__ for a in new_alerts]

        # تسجيل في محرك الخبرة إذا كانت الثقة عالية
        if result.success and result.confidence >= self_improver.retrain_confidence_threshold:
            image_b64 = None
            image_bytes = kwargs.get("image_bytes")
            if image_bytes is not None:
                import base64

                image_b64 = base64.b64encode(image_bytes).decode("utf-8")
            self_improver.auto_confirm(
                job_id=job_id,
                captcha_type=captcha_type.value,
                image_b64=image_b64,
                text=result.text or result.token,
                confidence=result.confidence,
            )

        # إرسال النتيجة النهائية عبر WebSocket
        progress.set_result(result.to_dict(), result.success)

        await _publish(
            job_id,
            {
                "job_id": job_id,
                "status": JOBS[job_id]["status"],
                "progress": 100,
                "current_step": progress.current_step,
                "result": result.to_dict(),
                "alerts": [a.__dict__ for a in new_alerts],
            },
        )
        if callback_url:
            await webhook_deliverer.deliver(
                callback_url,
                webhook_deliverer.build_payload(
                    job_id=job_id,
                    status=JOBS[job_id]["status"],
                    result=result.to_dict(),
                    finished_at=JOBS[job_id].get("finished_at"),
                ),
            )
    except Exception as exc:  # noqa: BLE001
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = str(exc)
        JOBS[job_id]["finished_at"] = _now()
        db.record_attempt(captcha_type=captcha_type.value, success=False, error=str(exc))
        event = SolveEvent(
            timestamp=_now(),
            captcha_type=captcha_type.value,
            success=False,
            response_time_ms=0,
            confidence=0.0,
            strategy=(decision.strategy if decision else "default"),
            error=str(exc),
        )
        monitor.record(event)
        progress.set_error(str(exc))
        await _publish(job_id, {"job_id": job_id, "status": "failed", "error": str(exc), "progress": 100})
        if callback_url:
            await webhook_deliverer.deliver(
                callback_url,
                webhook_deliverer.build_payload(
                    job_id=job_id,
                    status="failed",
                    error=str(exc),
                    finished_at=JOBS[job_id].get("finished_at"),
                ),
            )


def _decode_b64(value: Optional[str]) -> Optional[bytes]:
    if not value:
        return None
    try:
        return base64.b64decode(value)
    except Exception:
        return None


def _build_kwargs(req: BaseSolveRequest, file_bytes: Optional[bytes] = None, template_bytes: Optional[bytes] = None) -> Dict[str, Any]:
    kwargs: Dict[str, Any] = {}
    if file_bytes is not None:
        kwargs["image_bytes"] = file_bytes
    elif req.image_b64:
        kwargs["image_bytes"] = _decode_b64(req.image_b64)
    if template_bytes is not None:
        kwargs["template_bytes"] = template_bytes
    elif req.template_b64:
        kwargs["template_bytes"] = _decode_b64(req.template_b64)
    kwargs.update(
        sitekey=req.sitekey,
        url=req.url,
        action=req.action,
        cdata=req.cdata,
        target_color=req.target_color,
        min_area=req.min_area,
        config=ImageSolveConfig(
            psm=req.psm,
            oem=req.oem,
            whitelist=req.whitelist,
            preprocess=req.preprocess,
            resize_width=req.resize_width,
            threshold=req.threshold,
        ),
    )
    return {k: v for k, v in kwargs.items() if v is not None}


# ---------- نقاط النهاية المتزامنة ----------

@app.post("/solve/{captcha_type}", response_model=SolveResponse)
@limiter.limit("30/minute")
async def solve_sync(
    captcha_type: str,
    req: BaseSolveRequest,
    file: Optional[UploadFile] = File(None),
    template: Optional[UploadFile] = File(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> SolveResponse:
    _auth(credentials)
    try:
        ctype = CaptchaType(captcha_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"نوع كبتشا غير مدعوم: {captcha_type}")

    file_bytes = await file.read() if file else None
    template_bytes = await template.read() if template else None
    kwargs = _build_kwargs(req, file_bytes, template_bytes)

    # --------- الذكاء التحليلي ----------
    analysis_dict: Optional[Dict[str, Any]] = None
    image_for_analysis = None
    if file_bytes is not None:
        try:
            import numpy as np
            import cv2
            nparr = np.frombuffer(file_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is not None:
                image_for_analysis = img
                analysis = analyzer.analyze_image(img)
                analysis_dict = analyzer.recommend(analysis)
        except Exception:  # noqa: BLE001
            analysis_dict = None

    # --------- قرار الحل الذكي ----------
    decision = strategy.decide(
        ctype,
        image=image_for_analysis,
        sitekey=req.sitekey,
        url=req.url,
        prefer_human_like=req.human_like if hasattr(req, "human_like") else False,
    )

    # تطبيق الاستراتيجية: تجميع محركات أو استدعاء مباشر
    try:
        if decision.strategy == "ensemble_with_fallback":
            solvers = registry.get_solvers(ctype)
            result = strategy.ensemble_solve(solvers, ctype, **kwargs)
        else:
            result = await registry.solve_async(ctype, prefer_local=decision.use_local, **kwargs)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))

    # --------- المراقبة الذكية ----------
    event = SolveEvent(
        timestamp=_now(),
        captcha_type=ctype.value,
        success=result.success,
        response_time_ms=result.response_time_ms,
        confidence=result.confidence,
        strategy=decision.strategy,
        error=result.error,
    )
    new_alerts = monitor.record(event)
    db.record_attempt(
        captcha_type=ctype.value,
        success=result.success,
        confidence=result.confidence,
        response_time_ms=result.response_time_ms,
        error=result.error,
    )

    # --------- التدقيق ----------
    current_user = None
    if credentials:
        current_user = user_manager.authenticate(credentials.credentials)
    audit_log(
        action="solve_captcha",
        resource="captcha",
        resource_id=captcha_type,
        user_id=current_user.user_id if current_user else None,
        username=current_user.username if current_user else None,
        details={
            "captcha_type": ctype.value,
            "success": result.success,
            "confidence": result.confidence,
            "response_time_ms": result.response_time_ms,
            "strategy": decision.strategy,
        },
        success=result.success,
        error_message=result.error,
    )

    return SolveResponse(
        job_id="sync",
        status="completed" if result.success else "failed",
        result=result,
        created_at=_now(),
        analysis=analysis_dict,
        alerts=[a.__dict__ for a in new_alerts],
        strategy_used=decision.strategy,
    )


# --------- المهام غير المتزامنة ----------

@app.post("/solve/async/{captcha_type}", response_model=SolveResponse)
@limiter.limit("60/minute")
async def solve_async(
    captcha_type: str,
    req: BaseSolveRequest,
    file: Optional[UploadFile] = File(None),
    template: Optional[UploadFile] = File(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> SolveResponse:
    _auth(credentials)
    try:
        ctype = CaptchaType(captcha_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"نوع كبتشا غير مدعوم: {captcha_type}")

    file_bytes = await file.read() if file else None
    template_bytes = await template.read() if template else None
    kwargs = _build_kwargs(req, file_bytes, template_bytes)

    # --------- الذكاء التحليلي ----------
    analysis_dict: Optional[Dict[str, Any]] = None
    image_for_analysis = None
    if file_bytes is not None:
        try:
            import numpy as np
            import cv2
            nparr = np.frombuffer(file_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            if img is not None:
                image_for_analysis = img
                analysis = analyzer.analyze_image(img)
                analysis_dict = analyzer.recommend(analysis)
        except Exception:  # noqa: BLE001
            analysis_dict = None

    # --------- قرار الحل الذكي ----------
    decision = strategy.decide(
        ctype,
        image=image_for_analysis,
        sitekey=req.sitekey,
        url=req.url,
        prefer_human_like=req.human_like,
    )

    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "status": "queued",
        "captcha_type": ctype.value,
        "created_at": _now(),
        "result": None,
        "error": None,
        "finished_at": None,
        "analysis": analysis_dict,
        "strategy": decision.strategy,
        "decision": {
            "use_local": decision.use_local,
            "use_external": decision.use_external,
            "max_attempts": decision.max_attempts,
            "confidence_threshold": decision.confidence_threshold,
            "reasoning": decision.reasoning,
        },
    }
    JOB_SUBSCRIBERS[job_id] = []
    # تهيئة نظام التقدم
    progress = get_or_create_job_progress(job_id)
    progress.add_step("في الطابور", {"captcha_type": ctype.value}, progress=0)
    import asyncio

    asyncio.create_task(_run_job(job_id, ctype, kwargs, decision))
    return SolveResponse(
        job_id=job_id,
        status="queued",
        result=None,
        created_at=_now(),
        analysis=analysis_dict,
        alerts=[],
        strategy_used=decision.strategy,
    )


@app.get("/job/{job_id}", response_model=SolveResponse)
@limiter.limit("120/minute")
async def job_status(job_id: str, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> SolveResponse:
    _auth(credentials)
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="الوظيفة غير موجودة")
    result = None
    if job.get("result"):
        result = SolverResult(**job["result"])
    return SolveResponse(
        job_id=job_id,
        status=job["status"],
        result=result,
        created_at=job.get("created_at", _now()),
    )


@app.get("/job/{job_id}/progress")
@limiter.limit("120/minute")
async def job_progress(
    job_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """الحصول على تقدم المهمة مع تفاصيل الخطوات."""
    _auth(credentials)
    progress = get_or_create_job_progress(job_id)
    return progress.to_dict()


@app.websocket("/ws/job/{job_id}")
async def ws_job(websocket: WebSocket, job_id: str) -> None:
    """اتصال WebSocket للتحديثات الفورية لتقدم مهمة الحل."""
    await websocket.accept()
    progress = get_or_create_job_progress(job_id)
    progress.subscribers.append(websocket)

    # إرسال الحالة الحالية فورًا
    await websocket.send_json(progress.to_dict())

    try:
        while True:
            await websocket.receive_text()  # إبقاء الاتصال مفتوحًا
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in progress.subscribers:
            progress.subscribers.remove(websocket)


# --------- الإحصائيات ----------

@app.get("/stats")
@limiter.limit("60/minute")
async def stats(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Dict[str, Any]:
    _auth(credentials)
    return db.stats()


@app.get("/monitor")
@limiter.limit("60/minute")
async def monitor_report(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Dict[str, Any]:
    _auth(credentials)
    return monitor.report()


# --------- تحليلات متقدمة ----------

@app.get("/analytics/summary")
@limiter.limit("60/minute")
async def analytics_summary(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """ملخص التحليلات الشاملة."""
    _auth(credentials)
    if credentials is None:
        raise HTTPException(status_code=401, detail="مفتاح API مطلوب")
    current_user = user_manager.authenticate(credentials.credentials)
    if current_user is None:
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح")

    db_stats = db.stats()
    learning_stats = self_improver.stats()
    experience_stats = experience_engine.status()
    audit_stats = audit_logger.get_stats()
    monitor_report_data = monitor.report()

    return {
        "database": db_stats,
        "learning": learning_stats,
        "experience": experience_stats,
        "audit": audit_stats,
        "monitor": monitor_report_data,
    }


@app.get("/analytics/captcha-types")
@limiter.limit("60/minute")
async def analytics_captcha_types(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """إحصائيات حسب نوع الكبتشا."""
    _auth(credentials)
    if credentials is None:
        raise HTTPException(status_code=401, detail="مفتاح API مطلوب")

    db_stats = db.stats()
    by_type = db_stats.get("by_type", {})

    # حساب النسب المئوية
    total = db_stats.get("total", 0)
    type_percentages = {}
    for captcha_type, count in by_type.items():
        type_percentages[captcha_type] = {
            "count": count,
            "percentage": round((count / total * 100) if total > 0 else 0, 2),
        }

    return {
        "total": total,
        "by_type": type_percentages,
    }


@app.get("/analytics/audit")
@limiter.limit("60/minute")
async def analytics_audit(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """إحصائيات التدقيق."""
    _auth(credentials)
    if credentials is None:
        raise HTTPException(status_code=401, detail="مفتاح API مطلوب")

    return audit_logger.get_stats()


@app.get("/analytics/recent-activity")
@limiter.limit("60/minute")
async def analytics_recent_activity(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    limit: int = 50,
) -> Dict[str, Any]:
    """النشاط الأخير."""
    _auth(credentials)
    if credentials is None:
        raise HTTPException(status_code=401, detail="مفتاح API مطلوب")

    events = audit_logger.get_events(limit=limit)
    return {
        "recent_events": [e.to_dict() for e in events],
        "total": len(events),
    }


@app.post("/analysis/image")
@limiter.limit("60/minute")
async def analyze_image(
    file: UploadFile = File(...),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    _auth(credentials)
    data = await file.read()
    try:
        import numpy as np
        import cv2
        nparr = np.frombuffer(data, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(status_code=400, detail="صورة غير صالحة")
        analysis = analyzer.analyze_image(img)
        return analyzer.recommend(analysis)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc))


# --------- الحل الذاتي الكامل (Auto) ----------

class FeedbackRequest(BaseModel):
    strategy: str
    success: bool
    confidence: float = 0.0
    response_time_ms: int = 0
    captcha_type: str = "image"
    params: Optional[Dict[str, Any]] = None


@app.post("/auto")
@limiter.limit("30/minute")
async def auto_solve(
    file: Optional[UploadFile] = File(None),
    captcha_type: Optional[str] = Form(None),
    sitekey: Optional[str] = Form(None),
    url: Optional[str] = Form(None),
    action: Optional[str] = Form(None),
    cdata: Optional[str] = Form(None),
    template: Optional[UploadFile] = File(None),
    human_like: bool = Form(False),
    max_escalations: int = Form(2),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    _auth(credentials)
    import asyncio

    file_bytes = await file.read() if file else None
    template_bytes = await template.read() if template else None

    # Enhanced intelligence: analyze and preprocess before solving
    image = None
    if file_bytes is not None:
        try:
            import numpy as np
            import cv2
            nparr = np.frombuffer(file_bytes, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        except Exception:
            pass

    # Enhanced analysis with fallback
    captcha_type_provided = captcha_type
    if captcha_type is None:
        # Auto-detect type if not provided
        if image is not None:
            try:
                detection = detector.detect(image)
                captcha_type_provided = detection.captcha_type
            except Exception:
                captcha_type_provided = "image"
        else:
            captcha_type_provided = "image"

    # Run orchestrator with enhanced parameters
    result = await asyncio.to_thread(
        orchestrator.solve,
        captcha_type=captcha_type_provided,
        image_bytes=file_bytes,
        template_bytes=template_bytes,
        sitekey=sitekey,
        url=url,
        action=action,
        cdata=cdata,
        human_like=human_like,
        max_escalations=max_escalations,
    )
    db.record_attempt(
        captcha_type=result.detected_type,
        success=result.result.success,
        confidence=result.result.confidence,
        response_time_ms=result.result.response_time_ms,
        error=result.result.error,
    )
    return result.to_dict()


@app.post("/captcha-solve/url")
async def solve_url(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """تحميل صورة من رابط URL وحلها تلقائيًا."""
    _auth(credentials)
    import asyncio
    import httpx

    # قراءة جسم الطلب
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="جسم الطلب غير صالح (JSON مطلوب)")

    url = body.get("url")
    captcha_type = body.get("captcha_type")
    sitekey = body.get("sitekey")
    page_url = body.get("page_url")
    human_like = body.get("human_like", False)
    max_escalations = body.get("max_escalations", 2)

    if not url:
        raise HTTPException(status_code=400, detail="حقل url مطلوب")

    # تحميل الصورة من الرابط
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            image_bytes = resp.content
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=f"فشل تحميل الصورة من الرابط: {exc}")

    result = await asyncio.to_thread(
        orchestrator.solve,
        captcha_type=captcha_type,
        image_bytes=image_bytes,
        sitekey=sitekey,
        url=page_url,
        human_like=human_like,
        max_escalations=max_escalations,
    )
    db.record_attempt(
        captcha_type=result.detected_type,
        success=result.result.success,
        confidence=result.result.confidence,
        response_time_ms=result.result.response_time_ms,
        error=result.result.error,
    )
    return result.to_dict()


@app.post("/auto/async")
@limiter.limit("60/minute")
async def auto_submit(
    file: Optional[UploadFile] = File(None),
    captcha_type: Optional[str] = Form(None),
    sitekey: Optional[str] = Form(None),
    url: Optional[str] = Form(None),
    action: Optional[str] = Form(None),
    cdata: Optional[str] = Form(None),
    template: Optional[UploadFile] = File(None),
    human_like: bool = Form(False),
    max_escalations: int = Form(2),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    _auth(credentials)
    file_bytes = await file.read() if file else None
    template_bytes = await template.read() if template else None
    payload: Dict[str, Any] = {
        "captcha_type": captcha_type,
        "image_bytes": file_bytes,
        "template_bytes": template_bytes,
        "sitekey": sitekey,
        "url": url,
        "action": action,
        "cdata": cdata,
        "human_like": human_like,
        "max_escalations": max_escalations,
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    job_id = worker.submit(payload)
    return {"job_id": job_id, "status": "queued", "created_at": _now()}


@app.get("/auto/job/{job_id}")
@limiter.limit("120/minute")
async def auto_job_status(
    job_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    _auth(credentials)
    status = worker.status(job_id)
    if status is None:
        raise HTTPException(status_code=404, detail="المهمة غير موجودة")
    return status


@app.get("/auto/status")
@limiter.limit("60/minute")
async def auto_status(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    _auth(credentials)
    return {
        "worker": worker.snapshot(),
        "learning": learner.snapshot(),
        "tuner": tuner.snapshot(),
        "monitor": monitor.report(),
    }


@app.post("/feedback")
@limiter.limit("120/minute")
async def feedback(
    req: FeedbackRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    _auth(credentials)
    reward = learner.reward_from_result(req.success, req.confidence, req.response_time_ms)
    learner.update(req.strategy, reward)
    if req.params is not None:
        tuner.record(
            req.captcha_type, req.params, req.success, req.confidence, req.response_time_ms
        )
    event = SolveEvent(
        timestamp=_now(),
        captcha_type=req.captcha_type,
        success=req.success,
        response_time_ms=req.response_time_ms,
        confidence=req.confidence,
        strategy=req.strategy,
        error=None,
    )
    monitor.record(event)
    return {"ok": True, "reward": round(reward, 3), "learning": learner.snapshot()}


# --------- مفاتيح API ----------

class CreateKeyRequest(BaseModel):
    name: Optional[str] = None


class CreateKeyResponse(BaseModel):
    key_id: str
    api_key: str
    key_hash_prefix: str
    name: Optional[str] = None


class KeyInfo(BaseModel):
    key_id: str
    name: str
    is_active: bool
    created_at: Optional[float] = None
    usage_count: int = 0
    key_hash_prefix: str = ""


@app.post("/api/keys", response_model=CreateKeyResponse)
@limiter.limit("20/minute")
async def create_api_key(
    req: CreateKeyRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> CreateKeyResponse:
    _auth(credentials)
    key_id = str(uuid.uuid4())
    raw_key = generate_api_key()
    api_key_store.add(key_id, hash_api_key(raw_key), req.name)
    return CreateKeyResponse(
        key_id=key_id,
        api_key=raw_key,
        key_hash_prefix=hash_api_key(raw_key)[:8],
        name=req.name,
    )


@app.get("/api/keys", response_model=list)
@limiter.limit("60/minute")
async def list_api_keys(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> list:
    _auth(credentials)
    return api_key_store.list_keys()


@app.delete("/api/keys/{key_id}")
@limiter.limit("30/minute")
async def delete_api_key(
    key_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    _auth(credentials)
    ok = api_key_store.deactivate(key_id)
    if not ok:
        raise HTTPException(status_code=404, detail="المفتاح غير موجود")
    return {"ok": True}


# --------- إدارة المستخدمين والتحكم في الوصول (RBAC) ----------

class CreateUserRequest(BaseModel):
    username: str
    role: str = "user"
    api_key: Optional[str] = None


class UserResponse(BaseModel):
    user_id: str
    username: str
    role: str
    is_active: bool
    created_at: str
    last_login: Optional[str] = None
    total_solves: int = 0
    total_attempts: int = 0


class UpdateUserRequest(BaseModel):
    role: Optional[str] = None
    is_active: Optional[bool] = None


@app.get("/users", response_model=list)
@limiter.limit("60/minute")
async def list_users(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> list:
    """قائمة جميع المستخدمين (مخصص للمشرفين فقط)."""
    _auth(credentials)
    if credentials is None:
        raise HTTPException(status_code=401, detail="مفتاح API مطلوب")
    current_user = user_manager.authenticate(credentials.credentials)
    if current_user is None:
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح")
    if not user_manager.has_permission(current_user, UserRole.ADMIN):
        raise HTTPException(
            status_code=403,
            detail="هذا الطريق مخصص للمشرفين فقط",
        )
    return user_manager.to_dict_list()


@app.post("/users", response_model=UserResponse)
@limiter.limit("30/minute")
async def create_user(
    req: CreateUserRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> UserResponse:
    """إنشاء مستخدم جديد (مخصص للمشرفين فقط)."""
    _auth(credentials)
    if credentials is None:
        raise HTTPException(status_code=401, detail="مفتاح API مطلوب")
    current_user = user_manager.authenticate(credentials.credentials)
    if current_user is None:
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح")
    if not user_manager.has_permission(current_user, UserRole.ADMIN):
        raise HTTPException(
            status_code=403,
            detail="هذا الطريق مخصص للمشرفين فقط",
        )

    try:
        role = UserRole(req.role)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"دور غير صالح: {req.role}. الأدوار المتاحة: admin, operator, user, guest",
        )

    user = user_manager.create_user(
        username=req.username,
        role=role,
        api_key=req.api_key,
    )
    return UserResponse(
        user_id=user.user_id,
        username=user.username,
        role=user.role.value,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login=user.last_login,
        total_solves=user.total_solves,
        total_attempts=user.total_attempts,
    )


@app.get("/users/{user_id}", response_model=UserResponse)
@limiter.limit("60/minute")
async def get_user(
    user_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> UserResponse:
    """الحصول على تفاصيل مستخدم."""
    _auth(credentials)
    if credentials is None:
        raise HTTPException(status_code=401, detail="مفتاح API مطلوب")
    current_user = user_manager.authenticate(credentials.credentials)
    if current_user is None:
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح")
    if not user_manager.has_permission(current_user, UserRole.ADMIN):
        raise HTTPException(
            status_code=403,
            detail="هذا الطريق مخصص للمشرفين فقط",
        )

    user = user_manager.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")
    return UserResponse(
        user_id=user.user_id,
        username=user.username,
        role=user.role.value,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login=user.last_login,
        total_solves=user.total_solves,
        total_attempts=user.total_attempts,
    )


@app.put("/users/{user_id}", response_model=UserResponse)
@limiter.limit("30/minute")
async def update_user(
    user_id: str,
    req: UpdateUserRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> UserResponse:
    """تحديث مستخدم (مخصص للمشرفين فقط)."""
    _auth(credentials)
    if credentials is None:
        raise HTTPException(status_code=401, detail="مفتاح API مطلوب")
    current_user = user_manager.authenticate(credentials.credentials)
    if current_user is None:
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح")
    if not user_manager.has_permission(current_user, UserRole.ADMIN):
        raise HTTPException(
            status_code=403,
            detail="هذا الطريق مخصص للمشرفين فقط",
        )

    role = None
    if req.role is not None:
        try:
            role = UserRole(req.role)
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail=f"دور غير صالح: {req.role}",
            )

    user = user_manager.update_user(
        user_id=user_id,
        role=role,
        is_active=req.is_active,
    )
    if not user:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")
    return UserResponse(
        user_id=user.user_id,
        username=user.username,
        role=user.role.value,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login=user.last_login,
        total_solves=user.total_solves,
        total_attempts=user.total_attempts,
    )


@app.delete("/users/{user_id}")
@limiter.limit("30/minute")
async def delete_user(
    user_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """حذف مستخدم (مخصص للمشرفين فقط)."""
    _auth(credentials)
    if credentials is None:
        raise HTTPException(status_code=401, detail="مفتاح API مطلوب")
    current_user = user_manager.authenticate(credentials.credentials)
    if current_user is None:
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح")
    if not user_manager.has_permission(current_user, UserRole.ADMIN):
        raise HTTPException(
            status_code=403,
            detail="هذا الطريق مخصص للمشرفين فقط",
        )

    try:
        ok = user_manager.delete_user(user_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if not ok:
        raise HTTPException(status_code=404, detail="المستخدم غير موجود")
    return {"ok": True}


@app.get("/users/me", response_model=UserResponse)
@limiter.limit("60/minute")
async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> UserResponse:
    """الحصول على بيانات المستخدم الحالي."""
    _auth(credentials)
    if credentials is None:
        raise HTTPException(status_code=401, detail="مفتاح API مطلوب")
    user = user_manager.authenticate(credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح")
    return UserResponse(
        user_id=user.user_id,
        username=user.username,
        role=user.role.value,
        is_active=user.is_active,
        created_at=user.created_at,
        last_login=user.last_login,
        total_solves=user.total_solves,
        total_attempts=user.total_attempts,
    )


# --------- الجدولة التلقائية ----------

class ScheduleJobRequest(BaseModel):
    name: str
    captcha_type: str
    schedule_type: str = "interval"
    interval_seconds: Optional[int] = None
    cron_expression: Optional[str] = None
    sitekey: Optional[str] = None
    url: Optional[str] = None
    action: Optional[str] = None
    cdata: Optional[str] = None
    image_url: Optional[str] = None


class ScheduleJobResponse(BaseModel):
    job_id: str
    name: str
    captcha_type: str
    schedule_type: str
    next_run: Optional[str]
    is_active: bool


@app.post("/schedule/jobs", response_model=ScheduleJobResponse)
@limiter.limit("30/minute")
async def create_scheduled_job(
    req: ScheduleJobRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> ScheduleJobResponse:
    """إنشاء مهمة مجدولة جديدة للتحل التلقائي."""
    _auth(credentials)
    if credentials is None:
        raise HTTPException(status_code=401, detail="مفتاح API مطلوب")
    current_user = user_manager.authenticate(credentials.credentials)
    if current_user is None:
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح")

    job = scheduled_job_manager.create_job(
        name=req.name,
        captcha_type=req.captcha_type,
        schedule_type=req.schedule_type,
        interval_seconds=req.interval_seconds,
        cron_expression=req.cron_expression,
        sitekey=req.sitekey,
        url=req.url,
        action=req.action,
        cdata=req.cdata,
        image_url=req.image_url,
    )
    return ScheduleJobResponse(
        job_id=job.job_id,
        name=job.name,
        captcha_type=job.captcha_type,
        schedule_type=job.schedule_type.value,
        next_run=job.next_run,
        is_active=job.is_active,
    )


@app.get("/schedule/jobs", response_model=list)
@limiter.limit("60/minute")
async def list_scheduled_jobs(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> list:
    """قائمة جميع المهام المجدولة."""
    _auth(credentials)
    if credentials is None:
        raise HTTPException(status_code=401, detail="مفتاح API مطلوب")
    current_user = user_manager.authenticate(credentials.credentials)
    if current_user is None:
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح")
    return [job.to_dict() for job in scheduled_job_manager.list_jobs()]


@app.get("/schedule/jobs/{job_id}", response_model=ScheduleJobResponse)
@limiter.limit("60/minute")
async def get_scheduled_job(
    job_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> ScheduleJobResponse:
    """الحصول على تفاصيل مهمة مجدولة."""
    _auth(credentials)
    if credentials is None:
        raise HTTPException(status_code=401, detail="مفتاح API مطلوب")
    current_user = user_manager.authenticate(credentials.credentials)
    if current_user is None:
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح")

    job = scheduled_job_manager.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="المهمة المجدولة غير موجودة")
    return ScheduleJobResponse(
        job_id=job.job_id,
        name=job.name,
        captcha_type=job.captcha_type,
        schedule_type=job.schedule_type.value,
        next_run=job.next_run,
        is_active=job.is_active,
    )


@app.put("/schedule/jobs/{job_id}", response_model=ScheduleJobResponse)
@limiter.limit("30/minute")
async def update_scheduled_job(
    job_id: str,
    req: ScheduleJobRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> ScheduleJobResponse:
    """تحديث مهمة مجدولة."""
    _auth(credentials)
    if credentials is None:
        raise HTTPException(status_code=401, detail="مفتاح API مطلوب")
    current_user = user_manager.authenticate(credentials.credentials)
    if current_user is None:
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح")

    job = scheduled_job_manager.update_job(
        job_id=job_id,
        is_active=req.is_active if hasattr(req, 'is_active') else None,
        interval_seconds=req.interval_seconds,
        cron_expression=req.cron_expression,
    )
    if not job:
        raise HTTPException(status_code=404, detail="المهمة المجدولة غير موجودة")
    return ScheduleJobResponse(
        job_id=job.job_id,
        name=job.name,
        captcha_type=job.captcha_type,
        schedule_type=job.schedule_type.value,
        next_run=job.next_run,
        is_active=job.is_active,
    )


@app.delete("/schedule/jobs/{job_id}")
@limiter.limit("30/minute")
async def delete_scheduled_job(
    job_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """حذف مهمة مجدولة."""
    _auth(credentials)
    if credentials is None:
        raise HTTPException(status_code=401, detail="مفتاح API مطلوب")
    current_user = user_manager.authenticate(credentials.credentials)
    if current_user is None:
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح")

    ok = scheduled_job_manager.delete_job(job_id)
    if not ok:
        raise HTTPException(status_code=404, detail="المهمة المجدولة غير موجودة")
    return {"ok": True}


# --------- النسخ الاحتياطي ----------

class BackupRequest(BaseModel):
    include_db: bool = True
    include_config: bool = True
    include_intelligence: bool = True
    backup_type: str = "full"


class BackupResponse(BaseModel):
    backup_id: str
    timestamp: str
    backup_type: str
    file_path: str
    file_size: int
    includes_db: bool
    includes_config: bool
    includes_intelligence: bool
    status: str
    error: Optional[str] = None


@app.post("/backup/create", response_model=BackupResponse)
@limiter.limit("10/minute")
async def create_backup(
    req: BackupRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> BackupResponse:
    """إنشاء نسخة احتياطية من النظام."""
    _auth(credentials)
    if credentials is None:
        raise HTTPException(status_code=401, detail="مفتاح API مطلوب")
    current_user = user_manager.authenticate(credentials.credentials)
    if current_user is None:
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح")

    backup = backup_manager.create_backup(
        include_db=req.include_db,
        include_config=req.include_config,
        include_intelligence=req.include_intelligence,
        backup_type=req.backup_type,
    )
    return BackupResponse(
        backup_id=backup.backup_id,
        timestamp=backup.timestamp,
        backup_type=backup.backup_type,
        file_path=backup.file_path,
        file_size=backup.file_size,
        includes_db=backup.includes_db,
        includes_config=backup.includes_config,
        includes_intelligence=backup.includes_intelligence,
        status=backup.status,
        error=backup.error,
    )


@app.get("/backup/list", response_model=list)
@limiter.limit("60/minute")
async def list_backups(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> list:
    """قائمة جميع النسخ الاحتياطية."""
    _auth(credentials)
    if credentials is None:
        raise HTTPException(status_code=401, detail="مفتاح API مطلوب")
    current_user = user_manager.authenticate(credentials.credentials)
    if current_user is None:
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح")

    return [b.to_dict() for b in backup_manager.list_backups()]


@app.post("/backup/restore/{backup_id}")
@limiter.limit("10/minute")
async def restore_backup(
    backup_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """استعادة نسخة احتياطية."""
    _auth(credentials)
    if credentials is None:
        raise HTTPException(status_code=401, detail="مفتاح API مطلوب")
    current_user = user_manager.authenticate(credentials.credentials)
    if current_user is None:
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح")

    return backup_manager.restore_backup(backup_id)


# --------- الحل الجماعي ----------

class BulkItem(BaseModel):
    captcha_type: str
    sitekey: Optional[str] = None
    url: Optional[str] = None
    action: Optional[str] = None
    cdata: Optional[str] = None
    image_b64: Optional[str] = None
    template_b64: Optional[str] = None
    human_like: bool = False
    max_escalations: int = 2
    callback_url: Optional[str] = None


class BulkSubmitRequest(BaseModel):
    items: list[BulkItem]
    callback_url: Optional[str] = None


class BulkSubmitResponse(BaseModel):
    bulk_id: str
    job_ids: list
    count: int


class ExperienceFindRequest(BaseModel):
    captcha_type: str
    features: Optional[Dict[str, Any]] = None


BULK_JOBS: Dict[str, Dict[str, Any]] = {}


@app.post("/bulk/auto", response_model=BulkSubmitResponse)
@limiter.limit("10/minute")
async def bulk_auto(
    req: BulkSubmitRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> BulkSubmitResponse:
    _auth(credentials)
    bulk_id = str(uuid.uuid4())
    job_ids: list = []
    for item in req.items:
        payload = {
            "captcha_type": item.captcha_type,
            "sitekey": item.sitekey,
            "url": item.url,
            "action": item.action,
            "cdata": item.cdata,
            "image_bytes": _decode_b64(item.image_b64),
            "template_bytes": _decode_b64(item.template_b64),
            "human_like": item.human_like,
            "max_escalations": item.max_escalations,
            "callback_url": item.callback_url or req.callback_url,
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        job_id = worker.submit(payload)
        job_ids.append(job_id)
    BULK_JOBS[bulk_id] = {
        "bulk_id": bulk_id,
        "job_ids": job_ids,
        "count": len(job_ids),
        "created_at": _now(),
    }
    return BulkSubmitResponse(bulk_id=bulk_id, job_ids=job_ids, count=len(job_ids))


@app.get("/bulk/{bulk_id}")
@limiter.limit("60/minute")
async def bulk_status(
    bulk_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    _auth(credentials)
    bulk = BULK_JOBS.get(bulk_id)
    if not bulk:
        raise HTTPException(status_code=404, detail="المهمة الجماعية غير موجودة")
    job_statuses = []
    for jid in bulk["job_ids"]:
        st = worker.status(jid) or {"job_id": jid, "status": "unknown"}
        job_statuses.append(st)
    completed = sum(1 for s in job_statuses if s.get("status") == "completed")
    failed = sum(1 for s in job_statuses if s.get("status") == "failed")
    bulk["completed"] = completed
    bulk["failed"] = failed
    bulk["jobs"] = job_statuses
    return bulk


# --------- التحسين الذاتي ----------

@app.get("/self-improve/stats")
@limiter.limit("60/minute")
async def self_improve_stats(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    _auth(credentials)
    return self_improver.stats()


@app.post("/self-improve/confirm/{sample_id}")
@limiter.limit("60/minute")
async def self_improve_confirm(
    sample_id: str,
    text: Optional[str] = None,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    _auth(credentials)
    ok = self_improver.confirm(sample_id, text)
    if not ok:
        raise HTTPException(status_code=404, detail="العينات غير موجودة")
    return {"ok": True}


@app.post("/self-improve/retrain")
@limiter.limit("10/minute")
async def self_improve_retrain(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    _auth(credentials)
    return self_improver.maybe_retrain()


# --------- تجربة النظام والمعرفة ----------

@app.get("/experience/stats")
@limiter.limit("60/minute")
async def experience_stats(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    _auth(credentials)
    return experience_engine.status()


@app.get("/experience/knowledge")
@limiter.limit("60/minute")
async def experience_knowledge(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    _auth(credentials)
    return knowledge_base.stats()


@app.post("/experience/find")
@limiter.limit("60/minute")
async def experience_find(
    req: ExperienceFindRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    _auth(credentials)
    feat_dict = {k: float(v) for k, v in (req.features or {}).items()}
    known = experience_engine.find_known_solution(captcha_type=req.captcha_type, features=feat_dict)
    if not known:
        return {"found": False}
    return {"found": True, **known}


# --------- ضبط خدمة خارجية لـ hCaptcha (nindiad / nonecap) ----------

class ConfigureHCaptchaExternalRequest(BaseModel):
    api_key: str
    external_api: str
    external_api_type: str = "nindiad"  # "nindiad" أو "nonecap"
    max_retries: int = 10
    retry_delay: float = 5.0


class ConfigureHCaptchaExternalResponse(BaseModel):
    ok: bool
    message: str
    configured: bool


@app.post("/api/hcaptcha/external", response_model=ConfigureHCaptchaExternalResponse)
@limiter.limit("10/minute")
async def configure_hcaptcha_external_endpoint(
    req: ConfigureHCaptchaExternalRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> ConfigureHCaptchaExternalResponse:
    _auth(credentials)
    configure_hcaptcha_external(
        api_key=req.api_key,
        external_api=req.external_api,
        external_api_type=req.external_api_type,
        max_retries=req.max_retries,
        retry_delay=req.retry_delay,
    )
    return ConfigureHCaptchaExternalResponse(
        ok=True,
        message=f"تم ضبط خدمة hCaptcha الخارجية ({req.external_api_type}) مع إعادة المحاولة حتى النجاح",
        configured=True,
    )


# --------- لوحة التحكم ----------
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang=\"ar\" dir=\"rtl\">
<head>
<meta charset=\"UTF-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\">
<title>NoneCap Clone - لوحة التحكم</title>
<style>
*{box-sizing:border-box}body{font-family:system-ui,Segoe UI,Roboto,Arial;background:#0f172a;color:#e2e8f0;margin:0;padding:20px}
h1{color:#38bdf8;font-size:20px;margin-bottom:16px}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:16px;margin-bottom:24px}
.card{background:#1e293b;padding:16px;border-radius:10px;border:1px solid #334155}
.card .big{font-size:28px;font-weight:700;color:#22d3ee;margin:4px 0}
.card .lbl{font-size:12px;color:#94a3b8}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:8px;border-bottom:1px solid #334155;text-align:right}
th{color:#94a3b8}
form{background:#1e293b;padding:16px;border-radius:10px;border:1px solid #334155;margin-bottom:20px}
input,select{width:100%;padding:8px;margin:6px 0;border-radius:6px;border:1px solid #334155;background:#0b1120;color:#e2e8f0}
button{width:100%;padding:10px;border:none;border-radius:6px;background:#38bdf8;color:#000;font-weight:700;cursor:pointer}
button:hover{background:#7dd3fc}
#result{margin-top:12px;padding:10px;background:#0b1120;border-radius:6px;white-space:pre-wrap;color:#a5f3fc}
.small{font-size:12px;color:#94a3b8}
</style>
</head>
<body>
<h1>NoneCap Clone - لوحة التحكم والحل السريع</h1>
<div class=\"grid\">
<div class=\"card\"><div class=\"lbl\">إجمالي المحاولات</div><div id=\"stat-total\" class=\"big\">-</div></div>
<div class=\"card\"><div class=\"lbl\">ناجحة</div><div id=\"stat-success\" class=\"big\">-</div></div>
<div class=\"card\"><div class=\"lbl\">معدل النجاح</div><div id=\"stat-rate\" class=\"big\">-</div></div>
<div class=\"card\"><div class=\"lbl\">متوسط זמן الاستجابة</div><div id=\"stat-avg\" class=\"big\">- ms</div></div>
</div>

<form id=\"solveForm\">
<label>نوع الكبتشا</label>
<select id=\"ctype\">
<option value=\"image\">صورة/نص (Image)</option>
<option value=\"hcaptcha\">hCaptcha</option>
<option value=\"recaptcha_v2\">reCAPTCHA v2</option>
<option value=\"recaptcha_v3\">reCAPTCHA v3</option>
<option value=\"turnstile\">Turnstile</option>
<option value=\"drag\">Drag puzzle</option>
<option value=\"point\">Point-on-image</option>
</select>
<label>رابط الصفحة (url)</label><input id=\"url\" placeholder=\"https://example.com\">
<label>المفتاح العام (sitekey)</label><input id=\"sitekey\" placeholder=\"sitekey\">
<label>صورة (base64 أو رفع عبر السيرفر فقط)</label><input id=\"image_b64\" placeholder="بيانات base64 للصورة">
<label>psm</label><input id=\"psm\" type=\"number\" value=\"7\">
<button type=\"button\" onclick=\"solve()\">حل الكبتشا</button>
</form>
<div id=\"result\">اضغط على \"حل الكبتشا\" بعد تعبئة البيانات.</div>

<script>
async function loadStats(){
  const r=await fetch('/stats'); const d=await r.json();
  document.getElementById('stat-total').textContent=d.total;
  document.getElementById('stat-success').textContent=d.success;
  document.getElementById('stat-rate').textContent=d.success_rate+'%';
  document.getElementById('stat-avg').textContent=d.avg_response_time_ms;
}
async function solve(){
  const fd=new FormData();
  fd.append('ctype',document.getElementById('ctype').value);
  const el=document.getElementById('result'); el.textContent='جاري الحل...';
  const body={
    url:document.getElementById('url').value||undefined,
    sitekey:document.getElementById('sitekey').value||undefined,
    image_b64:document.getElementById('image_b64').value||undefined,
    psm:parseInt(document.getElementById('psm').value)||7,
  };
  try{
    const r=await fetch('/solve/'+document.getElementById('ctype').value,{
      method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)
    });
    const d=await r.json();
    el.textContent=JSON.stringify(d,null,2);
  }catch(e){el.textContent='خطأ: '+e.message;}
}
loadStats(); setInterval(loadStats,5000);
</script>
</body>
</html>
"""


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard() -> HTMLResponse:
    return HTMLResponse(content=DASHBOARD_HTML)


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok", "service": "nonecap-clone", "version": "0.4.0"}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> dict:
    if not _PROM_AVAILABLE:
        return {"error": "prometheus_client غير مثبت"}
    from fastapi.responses import Response
    from prometheus_client import generate_latest
    return {"metrics": generate_latest().decode("utf-8")}


def _auth(
    credentials: Optional[HTTPAuthorizationCredentials],
    x_api_key: Optional[str] = None,
    api_key_query: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    api_key = extract_api_key(credentials, x_api_key, api_key_query)
    if not api_key:
        return None  # التجريب محلياً دون مفتاح
    # أولاً تحقق من المفتاح في قاعدة البيانات الآمنة (مشفّر)
    key_info = secure_db.verify_api_key(api_key)
    if key_info:
        return key_info
    # fallback إلى المتجر في الذاكرة (للتوافق مع التكوين القديم)
    info = api_key_store.validate(api_key)
    if not info:
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح")
    if api_key_store.is_rate_limited(info["key_id"]):
        raise HTTPException(status_code=429, detail="تم تجاوز الحد المسموح للمفتاح")
    api_key_store.record_usage(info["key_id"])
    return info

@app.post("/test-simple-request")
async def test_simple_request(request: Request):
    body = await request.json()
    return {"received": body, "method": request.method}

@app.post("/test-with-deps")
async def test_with_deps(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
):
    body = await request.json()
    return {"received": body, "auth": bool(credentials)}
