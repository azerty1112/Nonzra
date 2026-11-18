"""سيرفر API متكامل لحل الكبتشا (FastAPI)."""

import asyncio
import base64
import json
import os
import uuid
import time
import re
from contextlib import asynccontextmanager
from pathlib import Path
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
    Mind,
)

from api_server.policy import POLICY
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
    get_capabilities,
    probe_hcaptcha,
    engines_status,
    evaluate_expression,
    normalize_expression,
)
from solver_engine.synthetic import generate_batch as generate_synthetic_batch
from solver_engine.db import encrypt_value, decrypt_value

from intelligence.knowledge_corpus import catalog as knowledge_catalog, quiz as knowledge_quiz
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

    def get_remote_address(*args: Any, **kwargs: Any) -> str:  # type: ignore[misc]
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

API_VERSION = "0.7.0"

# المسار الجذري للمشروع (حتى تعمل لوحة التحكم من أي دليل تشغيل)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = PROJECT_ROOT / "web"

# في الوضع غير المحدود: المُحدِّد معطّل تمامًا (لا 429 على الإطلاق)
limiter = Limiter(key_func=get_remote_address, enabled=not POLICY.unlimited)

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

# --------- العقل الذاتي (يُحفظ تعلّمه على القرص) ----------
mind = Mind()

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
    mind=mind,
)
worker = AutoWorker(
    orchestrator=orchestrator,
    concurrency=POLICY.concurrency,
    max_concurrency=POLICY.max_concurrency,
)

# --------- التحسين الذاتي ----------
training_dataset = CaptchaDataset()
self_improver = SelfImprover(dataset=training_dataset)


async def _memory_sweeper() -> None:
    """ينظّف الذاكرة دوريًا (مهام منتهية، متتبّعات معدل) في الخلفية."""
    while True:
        try:
            await asyncio.sleep(60)
            _sweep_memory()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            continue


@asynccontextmanager
async def lifespan(_app: FastAPI):
    sweep_task = asyncio.create_task(_memory_sweeper())
    await worker.start()
    await scheduled_job_manager.start_scheduler(orchestrator)
    try:
        yield
    finally:
        sweep_task.cancel()
        try:
            mind.save()
        except Exception:  # noqa: BLE001
            pass
        # كتابة مؤجّلة: نحفظ ما تبقّى من عينات التدريب قبل الإيقاف
        try:
            training_dataset.flush()
        except Exception:  # noqa: BLE001
            pass
        await scheduled_job_manager.stop_scheduler()
        await worker.stop()


app = FastAPI(
    title="NoneCap Clone API",
    version=API_VERSION,
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

# --------- CORS: يسمح للوحات والإضافات بالاتصال بالسيرفر ----------
_CORS_ORIGINS_ENV = os.environ.get("NONECAP_CORS_ORIGINS", "")
if _CORS_ORIGINS_ENV.strip() in ("*", "all"):
    _CORS_ORIGINS: List[str] = ["*"]
elif _CORS_ORIGINS_ENV.strip():
    _CORS_ORIGINS = [o.strip() for o in _CORS_ORIGINS_ENV.split(",") if o.strip()]
else:
    _CORS_ORIGINS = []

if _CORS_ORIGINS:
    from fastapi.middleware.cors import CORSMiddleware

    app.add_middleware(
        CORSMiddleware,
        allow_origins=_CORS_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["X-Captcha-Text"],
    )

# قاعدة بيانات آمنة مع تشفير مفاتيح API
secure_db = Database()

# خدمة الملفات الثابتة للوحة الويب (مسار مطلق يعمل من أي دليل)
_STATIC_DIR = WEB_DIR / "static"
if _STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# --------- نظام أمان IP ومعدل طلب متحرك ----------

_IP_BLOCK_LIST: Dict[str, float] = {}
_REQUEST_TIMESTAMPS: Dict[str, List[float]] = {}
MAX_REQUESTS_PER_MINUTE = POLICY.per_ip_per_minute
BLOCK_DURATION_SECONDS = POLICY.ip_block_seconds


def _get_client_ip(request: Request) -> str:
    """عنوان العميل الحقيقي.

    ``X-Forwarded-For`` يُصدَّق **فقط** عند تفعيل ``NONECAP_TRUST_FORWARDED_FOR``،
    وإلا فأي عميل يزوّر العنوان ويُفلت من تحديد المعدل والحظر كليًا.
    """
    if POLICY.trust_forwarded_for:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            # آخر عنوان يضيفه الوكيل الموثوق هو الأدقّ من أوله (القابل للتزوير)
            parts = [p.strip() for p in forwarded.split(",") if p.strip()]
            if parts:
                return parts[-1]
    return request.client.host if request.client else "unknown"


def _is_ip_blocked(ip: str) -> bool:
    if ip in _IP_BLOCK_LIST:
        if time.time() - _IP_BLOCK_LIST[ip] < BLOCK_DURATION_SECONDS:
            return True
        del _IP_BLOCK_LIST[ip]
    return False


def _block_ip(ip: str) -> None:
    _IP_BLOCK_LIST[ip] = time.time()


#: سقف عدد العناوين المتتبَّعة — يمنع استنزاف الذاكرة برشّ عناوين وهمية.
MAX_TRACKED_IPS = max(100, int(os.environ.get("NONECAP_MAX_TRACKED_IPS", "10000")))


def _check_rate_limit(ip: str) -> bool:
    if MAX_REQUESTS_PER_MINUTE <= 0:
        return True  # الوضع غير المحدود
    now = time.time()
    if ip not in _REQUEST_TIMESTAMPS and len(_REQUEST_TIMESTAMPS) >= MAX_TRACKED_IPS:
        # عند الامتلاء: نطرد أقدم عناوين خاملة بدل النمو بلا حد
        stale = [
            key
            for key, stamps in _REQUEST_TIMESTAMPS.items()
            if not stamps or now - stamps[-1] > 60.0
        ]
        for key in stale[: max(1, len(stale))]:
            _REQUEST_TIMESTAMPS.pop(key, None)
        if len(_REQUEST_TIMESTAMPS) >= MAX_TRACKED_IPS:
            # لا شيء خامل: نرفض التتبّع الجديد بدل تجاوز السقف (fail-closed
            # على الذاكرة، مع السماح بالطلب نفسه حتى لا نحجب خدمة مشروعة)
            return True
    timestamps = _REQUEST_TIMESTAMPS.get(ip, [])
    # احتفظ فقط بطلبات الدقيقة الأخيرة
    timestamps = [t for t in timestamps if now - t < 60.0]
    if len(timestamps) >= MAX_REQUESTS_PER_MINUTE:
        if BLOCK_DURATION_SECONDS > 0:
            _block_ip(ip)
        return False
    timestamps.append(now)
    _REQUEST_TIMESTAMPS[ip] = timestamps
    return True


def _sweep_memory() -> None:
    """ينظّف المهام القديمة ومتتبّعات المعدل حتى لا تتضخّم الذاكرة على خادم دائم."""
    now = time.time()
    # حذف المهام المنتهية
    for job_id, job in list(JOBS.items()):
        finished = job.get("finished_at")
        if not finished:
            continue
        try:
            from datetime import datetime as _dt

            ts = _dt.fromisoformat(finished).timestamp()
        except Exception:  # noqa: BLE001
            ts = now
        if now - ts > POLICY.job_ttl_seconds:
            JOBS.pop(job_id, None)
            JOB_PROGRESS.pop(job_id, None)
            JOB_SUBSCRIBERS.pop(job_id, None)
    # سقف صلب للمهام المحفوظة (الأقدم أولًا)
    if len(JOBS) > POLICY.max_jobs_retained:
        oldest = sorted(
            JOBS.items(),
            key=lambda item: item[1].get("created_at") or "",
        )
        for job_id, _ in oldest[: len(JOBS) - POLICY.max_jobs_retained]:
            JOBS.pop(job_id, None)
            JOB_PROGRESS.pop(job_id, None)
            JOB_SUBSCRIBERS.pop(job_id, None)
    # تنظيف متتبّع معدل الطلبات لعناوين خاملة
    for ip, stamps in list(_REQUEST_TIMESTAMPS.items()):
        recent = [t for t in stamps if now - t < 60.0]
        if recent:
            _REQUEST_TIMESTAMPS[ip] = recent
        else:
            _REQUEST_TIMESTAMPS.pop(ip, None)
    for ip, blocked_at in list(_IP_BLOCK_LIST.items()):
        if now - blocked_at > max(1, BLOCK_DURATION_SECONDS):
            _IP_BLOCK_LIST.pop(ip, None)


class _BodySizeGuard:
    """يقطع قراءة الجسم عند تجاوز السقف — لا يقرأ 40 ميغابايت ليرفضها.

    حماية على مستوى ASGI لا على مستوى المسار: تعمل لكل نقطة نهاية، وتوقف
    القراءة عند الحد بدل جمع الرسالة كاملة في الذاكرة أولًا.
    """

    def __init__(self, app: Any, limit: int) -> None:
        self.app = app
        self.limit = limit

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope.get("type") != "http" or not self.limit:
            await self.app(scope, receive, send)
            return

        # رفض مبكر بلا قراءة إن أعلن العميل حجمًا أكبر من السقف
        for name, value in scope.get("headers") or []:
            if name == b"content-length":
                try:
                    if int(value) > self.limit:
                        await _send_413(send, self.limit)
                        return
                except ValueError:
                    pass

        consumed = 0
        rejected = False

        async def guarded_receive() -> Any:
            nonlocal consumed, rejected
            message = await receive()
            if message.get("type") == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > self.limit:
                    rejected = True
                    raise _BodyTooLarge(consumed)
            return message

        started = False

        async def guarded_send(message: Any) -> None:
            nonlocal started
            if message.get("type") == "http.response.start":
                started = True
            if not rejected:
                await send(message)

        try:
            await self.app(scope, guarded_receive, guarded_send)
        except _BodyTooLarge:
            pass
        if rejected and not started:
            await _send_413(send, self.limit)


class _BodyTooLarge(Exception):
    """إشارة داخلية: تجاوز الجسم السقف أثناء التدفّق."""


async def _send_413(send: Any, limit: int) -> None:
    body = json.dumps(
        {
            "detail": (
                f"جسم الطلب أكبر من الحد المسموح ({limit} بايت). "
                "صغّر الصورة أو ارفعها عبر حقل file."
            )
        },
        ensure_ascii=False,
    ).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json; charset=utf-8"),
                (b"content-length", str(len(body)).encode()),
                (b"connection", b"close"),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


# حدّ حجم الجسم: يعمل قبل أي توجيه أو تحليل، ويقطع القراءة عند الحد.
# (يُسجَّل هنا لأن الصنف معرَّف أعلاه؛ ترتيب التسجيل لا يغيّر الترتيب الداخلي.)
if POLICY.max_body_bytes:
    app.add_middleware(_BodySizeGuard, limit=POLICY.max_body_bytes)


@app.middleware("http")
async def security_middleware(request: Request, call_next: Any) -> Any:
    # الوضع غير المحدود: لا حظر ولا عدّ إطلاقًا (أقل حملًا وأسرع)
    if not POLICY.unlimited:
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
    if not POLICY.unlimited:
        response.headers["X-RateLimit-Limit"] = str(MAX_REQUESTS_PER_MINUTE)
    return response


@app.get("/web", response_class=HTMLResponse)
async def web_dashboard() -> Any:
    dashboard_path = WEB_DIR / "templates" / "dashboard.html"
    if not dashboard_path.is_file():
        raise HTTPException(status_code=404, detail="ملف لوحة التحكم غير موجود")
    return FileResponse(str(dashboard_path))


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def landing_page() -> Any:
    """الصفحة العامة: تعريف بالخادم، حالة التشغيل، وحلّ صورة مباشرة."""
    path = WEB_DIR / "templates" / "landing.html"
    if path.is_file():
        return FileResponse(str(path))
    from fastapi.responses import RedirectResponse

    return RedirectResponse(url="/dashboard")

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
            # دفاع على طبقتين: لا نُرمّز الصورة إطلاقًا إن كان التخزين معطّلًا.
            # (المجموعة تُسقطها أيضًا، لكن عدم تمريرها أفضل من تمريرها ثم إسقاطها.)
            image_b64 = None
            image_bytes = kwargs.get("image_bytes")
            if image_bytes is not None and training_dataset.store_images:
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
    """يفكّ ترميز base64 مع سقف حجم قبل الترميز — لا نفكّ ما لا نقبله.

    فكّ ترميز 40 ميغابايت ثم رفضها يعني أن العملية (والذاكرة) أُهدرت بالفعل.
    نقيس أولًا على طول النص المُرمَّز لأنه متاح بلا تكلفة.
    """
    if not value:
        return None
    limit = POLICY.max_image_bytes
    if limit and len(value) * 3 // 4 > limit + 1024:
        raise HTTPException(
            status_code=413,
            detail=(
                f"الصورة أكبر من الحد المسموح ({limit} بايت بعد فك الترميز). "
                "صغّر الصورة أو ارفعها عبر حقل file."
            ),
        )
    try:
        data = base64.b64decode(value)
    except Exception:
        return None
    if limit and len(data) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"الصورة أكبر من الحد المسموح ({limit} بايت بعد فك الترميز)",
        )
    return data


async def _read_limited(upload: Any) -> bytes:
    """يقرأ ملفًا مرفوعًا بحدّ أقصى — يرفض 413 بدل استهلاك الذاكرة بلا سقف."""
    limit = POLICY.max_image_bytes
    data = await upload.read()
    if limit and len(data) > limit:
        raise HTTPException(
            status_code=413,
            detail=f"الملف المرفوع أكبر من الحد المسموح ({limit} بايت)",
        )
    return data


async def _parse_solve_request(request: Request) -> BaseSolveRequest:
    """يقرأ جسم الطلب بصيغة JSON أو form-data/multipart.

    الوثائق وأداة الـ CLI يرسلان form-data، بينما العملاء البرمجيون يرسلون JSON؛
    دعم الصيغتين يمنع أخطاء 422 التي كانت تحدث عند استخدام الصيغة الأخرى.
    """
    content_type = (request.headers.get("content-type") or "").lower()
    # حماية أولية بلا تكلفة: نصدّق Content-Length المعلن قبل قراءة الجسم.
    declared = request.headers.get("content-length")
    if declared and POLICY.max_body_bytes:
        try:
            if int(declared) > POLICY.max_body_bytes:
                raise HTTPException(
                    status_code=413,
                    detail=(
                        f"جسم الطلب أكبر من الحد المسموح ({POLICY.max_body_bytes} بايت)"
                    ),
                )
        except ValueError:
            pass
    if "application/json" in content_type:
        try:
            payload = await request.json()
        except Exception:  # noqa: BLE001
            payload = {}
        return BaseSolveRequest(**payload) if isinstance(payload, dict) else BaseSolveRequest()

    if "form" in content_type or "multipart" in content_type:
        form = await request.form()
        data: Dict[str, Any] = {}
        for key, value in form.multi_items():
            if key in ("file", "template") or not isinstance(value, str):
                continue
            data[key] = value
        # التحويل الضمني للحقول الرقمية/المنطقية
        for flag in ("preprocess", "human_like"):
            if flag in data and isinstance(data[flag], str):
                data[flag] = data[flag].strip().lower() in ("1", "true", "yes", "on")
        for number_field in ("psm", "oem", "resize_width", "min_area"):
            if number_field in data and isinstance(data[number_field], str):
                try:
                    data[number_field] = int(data[number_field])
                except ValueError:
                    data.pop(number_field, None)
        return BaseSolveRequest(**data)

    return BaseSolveRequest()


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
    request: Request, captcha_type: str,
    file: Optional[UploadFile] = File(None),
    template: Optional[UploadFile] = File(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> SolveResponse:
    _auth(credentials)
    req = await _parse_solve_request(request)
    try:
        ctype = CaptchaType(captcha_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"نوع كبتشا غير مدعوم: {captcha_type}")

    file_bytes = await _read_limited(file) if file else None
    template_bytes = await _read_limited(template) if template else None
    kwargs = _build_kwargs(req, file_bytes, template_bytes)

    # الأنواع المحلية تحتاج صورة فعلية: خطأ 400 واضح أفضل من فشل صامت
    _image_required = {
        CaptchaType.IMAGE,
        CaptchaType.TEXT,
        CaptchaType.MATH,
        CaptchaType.DRAG,
        CaptchaType.POINT,
        CaptchaType.SLIDER,
        CaptchaType.ROTATE,
    }
    if ctype in _image_required and not file_bytes and not req.image_b64:
        raise HTTPException(
            status_code=400,
            detail=f"يجب توفير صورة الكبتشا (file أو image_b64) للنوع {ctype.value}",
        )

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
    request: Request, captcha_type: str,
    file: Optional[UploadFile] = File(None),
    template: Optional[UploadFile] = File(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> SolveResponse:
    _auth(credentials)
    req = await _parse_solve_request(request)
    try:
        ctype = CaptchaType(captcha_type)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"نوع كبتشا غير مدعوم: {captcha_type}")

    file_bytes = await _read_limited(file) if file else None
    template_bytes = await _read_limited(template) if template else None
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
async def job_status(request: Request,
                     job_id: str, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> SolveResponse:
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
    request: Request, job_id: str,
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
async def stats(request: Request,
                credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Dict[str, Any]:
    _auth(credentials)
    return db.stats()


@app.get("/monitor")
@limiter.limit("60/minute")
async def monitor_report(request: Request,
                         credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)) -> Dict[str, Any]:
    _auth(credentials)
    return monitor.report()


# --------- تحليلات متقدمة ----------

@app.get("/analytics/summary")
@limiter.limit("60/minute")
async def analytics_summary(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
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
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
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
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """إحصائيات التدقيق."""
    _auth(credentials)
    if credentials is None:
        raise HTTPException(status_code=401, detail="مفتاح API مطلوب")

    return audit_logger.get_stats()


@app.get("/analytics/recent-activity")
@limiter.limit("60/minute")
async def analytics_recent_activity(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
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
    request: Request, file: UploadFile = File(...),
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
    request: Request, file: Optional[UploadFile] = File(None),
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

    file_bytes = await _read_limited(file) if file else None
    template_bytes = await _read_limited(template) if template else None

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
    request: Request, file: Optional[UploadFile] = File(None),
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
    file_bytes = await _read_limited(file) if file else None
    template_bytes = await _read_limited(template) if template else None
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
    request: Request, job_id: str,
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
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    _auth(credentials)
    return {
        "worker": worker.snapshot(),
        "learning": learner.snapshot(),
        "tuner": tuner.snapshot(),
        "monitor": monitor.report(),
        "mind": {
            "self_rating": mind.competence.self_rating(),
            "cycles": mind.total_cycles,
            "mood": mind._mood(),
            "next_experiment": mind.next_experiment(),
        },
    }


@app.post("/feedback")
@limiter.limit("120/minute")
async def feedback(
    request: Request, req: FeedbackRequest,
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
    mind.learn(
        captcha_type=req.captcha_type,
        success=req.success,
        confidence=req.confidence,
        latency_ms=req.response_time_ms,
    )
    return {
        "ok": True,
        "reward": round(reward, 3),
        "learning": learner.snapshot(),
        "self_rating": mind.competence.self_rating(),
    }


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
    request: Request, req: CreateKeyRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> CreateKeyResponse:
    _auth(credentials)
    key_id = str(uuid.uuid4())
    raw_key = generate_api_key()
    api_key_store.add(key_id, hash_api_key(raw_key), req.name)
    # حفظ المفتاح في قاعدة البيانات المشفّرة أيضًا (يبقى صالحًا بعد إعادة التشغيل)
    try:
        secure_db.add_api_key(key_id, raw_key, req.name)
    except Exception:  # noqa: BLE001
        pass
    return CreateKeyResponse(
        key_id=key_id,
        api_key=raw_key,
        key_hash_prefix=hash_api_key(raw_key)[:8],
        name=req.name,
    )


@app.get("/api/keys", response_model=list)
@limiter.limit("60/minute")
async def list_api_keys(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> list:
    _auth(credentials)
    return api_key_store.list_keys()


@app.delete("/api/keys/{key_id}")
@limiter.limit("30/minute")
async def delete_api_key(
    request: Request, key_id: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    _auth(credentials)
    ok = api_key_store.deactivate(key_id)
    # إلغاء التفعيل في قاعدة البيانات المشفّرة أيضًا
    try:
        ok = secure_db.deactivate_api_key(key_id) or ok
    except Exception:  # noqa: BLE001
        pass
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
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
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
    request: Request, req: CreateUserRequest,
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
    request: Request, user_id: str,
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
    request: Request, user_id: str,
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
    request: Request, user_id: str,
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
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
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
    request: Request, req: ScheduleJobRequest,
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
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
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
    request: Request, job_id: str,
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
    request: Request, job_id: str,
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
    request: Request, job_id: str,
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
    excluded: list[str] = []  # ملفات حسّاسة استُثنيت (شفافية الخصوصية)


@app.post("/backup/create", response_model=BackupResponse)
@limiter.limit("10/minute")
async def create_backup(
    request: Request, req: BackupRequest,
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
        excluded=backup.excluded,
    )


@app.get("/backup/list", response_model=list)
@limiter.limit("60/minute")
async def list_backups(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
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
    request: Request, backup_id: str,
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
    request: Request, req: BulkSubmitRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> BulkSubmitResponse:
    _auth(credentials)
    if len(req.items) > POLICY.max_batch_items:
        raise HTTPException(
            status_code=413,
            detail=f"الحد الأقصى {POLICY.max_batch_items} عنصرًا في الطلب الجماعي",
        )
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
    request: Request, bulk_id: str,
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


# --------- hCaptcha: فحص الوصول والحل المباشر ----------

class HCaptchaLiveRequest(BaseModel):
    sitekey: str = Field(..., description="مفتاح موقع hCaptcha")
    url: str = Field(..., description="صفحة الموقع التي تحتوي الكبتشا")
    host: Optional[str] = Field(None, description="المضيف، افتراضيًا من url")
    max_rounds: int = Field(2, ge=1, le=5)
    deadline_seconds: float = Field(90.0, ge=10, le=300, description="سقف زمني كلي للطلب")
    allow_abstain: bool = Field(
        True,
        description="الامتناع عن إرسال إجابة منخفضة الثقة بدل إحراق محاولة (موصى به)",
    )
    abstain_threshold: float = Field(
        0.45, ge=0.0, le=1.0, description="عتبة الاحتمال الدنيا للإرسال"
    )


@app.get("/hcaptcha/probe", tags=["solving"])
@limiter.limit("30/minute")
async def hcaptcha_probe(
    request: Request,
    sitekey: str = Query("10000000-ffff-ffff-ffff-000000000001"),
    url: str = Query("https://accounts.hcaptcha.com/demo"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """يفحص إن كانت هذه الشبكة تصل إلى hCaptcha، ويعرض محرّكات القراءة المتاحة."""
    _auth(credentials)
    return probe_hcaptcha(sitekey=sitekey, url=url)


@app.get("/ocr/engines", tags=["system"])
@limiter.limit("60/minute")
async def ocr_engines(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Dict[str, Any]:
    """محرّكات قراءة النص المتاحة فعليًا على هذا الجهاز وترتيب الأفضلية."""
    _auth(credentials)
    return engines_status()


@app.get("/training/samples", tags=["system"])
@limiter.limit("60/minute")
async def training_samples_stats(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Dict[str, Any]:
    """حالة مجموعة عينات التدريب وسياسة الخصوصية المطبّقة فعليًا."""
    _auth(credentials)
    return training_dataset.stats()


@app.delete("/training/samples", tags=["system"])
@limiter.limit("30/minute")
async def training_samples_purge(
    request: Request,
    captcha_type: Optional[str] = Query(None, description="حذف نوع محدّد فقط"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """حق الحذف: يمحو عينات التدريب (كلها أو لنوع) ويعيد عدد المحذوف.

    يُستخدم عند طلب المستخدم حذف بياناته، أو لتنظيف بيئة اختبار.
    """
    _auth(credentials)
    removed = training_dataset.purge(captcha_type=captcha_type)
    try:
        audit_log(
            action="training_purge",
            resource="training_samples",
            details={"captcha_type": captcha_type, "removed": removed},
        )
    except Exception:  # noqa: BLE001 - التدقيق لا يجب أن يعطّل الحذف
        pass
    return {"purged": removed, "captcha_type": captcha_type, **training_dataset.stats()}


@app.get("/health/resilience", tags=["system"])
@limiter.limit("60/minute")
async def health_resilience(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Dict[str, Any]:
    """حالة الاحتياطات: قواطع الدائرة، تعلّم القراءة، وحالة OCR — كلها في مكان واحد."""
    _auth(credentials)
    from intelligence.ocr_policy import get_policy
    from solver_engine.resilience import breakers_snapshot

    policy = get_policy()
    return {
        "breakers": breakers_snapshot(),
        "ocr": engines_status(),
        "learning": {
            "contexts": len(policy.snapshot().get("contexts", {})),
            "calibration_observations": policy.calibrator.total_observations,
        },
    }


@app.get("/ocr/policy", tags=["system"])
@limiter.limit("60/minute")
async def ocr_policy_snapshot(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Dict[str, Any]:
    """ما تعلّمته سياسة القراءة: أداء كل طريقة عرض لكل نوع صورة + معايرة الثقة."""
    _auth(credentials)
    from intelligence.ocr_policy import get_policy

    return get_policy().snapshot()


@app.post("/ocr/policy/save", tags=["system"])
@limiter.limit("30/minute")
async def ocr_policy_save(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Dict[str, Any]:
    """يحفظ التعلّم على القرص الآن (يُحفظ تلقائيًا عند الإيقاف أيضًا)."""
    _auth(credentials)
    from intelligence.ocr_policy import get_policy

    policy = get_policy()
    saved = policy.save()
    return {"saved": saved, "path": policy.path}


class OcrBenchRequest(BaseModel):
    count: int = Field(12, ge=4, le=60)
    level: str = Field("balanced", description="fast | balanced | max")
    seed: int = 7


@app.post("/ocr/bench", tags=["system"])
@limiter.limit("6/minute")
async def ocr_bench(
    request: Request, req: OcrBenchRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """يقيس دقة القراءة فعليًا على مجموعة اختبار ثابتة (نفس البذرة ⇒ نفس النتيجة)."""
    _auth(credentials)
    from solver_engine.bench import run as run_bench

    report = await asyncio.to_thread(
        run_bench, level=req.level, count=req.count, seed=req.seed, quiet=True
    )
    return report.to_dict()


@app.post("/hcaptcha/live", tags=["solving"])
@limiter.limit("30/minute")
async def hcaptcha_live_solve(
    request: Request, req: HCaptchaLiveRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """يحل hCaptcha مباشرة عبر بروتوكوله العام — بلا أي خدمة مدفوعة.

    يعمل مع التحديات النصية. التحديات متعددة الصور تحتاج نماذج كشف كائنات
    غير مضمّنة، فيعيد فشلًا صريحًا مع السبب.
    """
    _auth(credentials)
    import uuid

    from solver_engine.resilience import TimeoutExceeded
    from solver_engine.hcaptcha_live import HCaptchaLiveSolver

    request_id = uuid.uuid4().hex[:12]
    solver = HCaptchaLiveSolver(
        max_rounds=req.max_rounds,
        deadline_seconds=req.deadline_seconds,
        allow_abstain=req.allow_abstain,
        abstain_threshold=req.abstain_threshold,
    )
    # سقف زمني صارم على مستوى الطلب أيضًا: لا تعليق حتى لو تجاوز المحلّل مهلته
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(
                solver.solve, sitekey=req.sitekey, url=req.url, host=req.host
            ),
            timeout=req.deadline_seconds + 15,
        )
    except (asyncio.TimeoutError, TimeoutExceeded) as exc:
        from solver_engine.resilience import breakers_snapshot

        db.record_attempt(
            captcha_type="hcaptcha_live",
            success=False,
            confidence=0.0,
            response_time_ms=int(req.deadline_seconds * 1000),
            error="timeout",
        )
        return {
            "success": False,
            "token": None,
            "answer": None,
            "confidence": 0.0,
            "response_time_ms": int(req.deadline_seconds * 1000),
            "error": (
                f"انتهت المهلة القصوى ({req.deadline_seconds:.0f} ثانية) قبل إتمام الحل. "
                "أعد المحاولة أو ارفع deadline_seconds."
            ),
            "request_id": request_id,
            "metadata": {"stage": "deadline", "breakers": breakers_snapshot()},
        }

    db.record_attempt(
        captcha_type="hcaptcha_live",
        success=result.success,
        confidence=result.confidence,
        response_time_ms=result.response_time_ms,
        error=result.error,
    )
    payload = {
        "success": result.success,
        "token": result.token,
        "answer": result.text,
        "confidence": result.confidence,
        "response_time_ms": result.response_time_ms,
        "error": result.error,
        "metadata": result.metadata,
        "request_id": request_id,
    }
    if not result.success and result.metadata.get("retry_after_seconds"):
        payload["retry_after_seconds"] = result.metadata["retry_after_seconds"]
    return payload


# --------- العقل الذاتي: التقرير، التخطيط، والتأمّل ----------

class MindPlanRequest(BaseModel):
    captcha_type: str = "image"
    difficulty: float = Field(0.5, ge=0.0, le=1.0)
    external_available: bool = False
    prefer_speed: bool = False


class MindObserveRequest(BaseModel):
    captcha_type: str = "image"
    success: bool
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    latency_ms: int = Field(0, ge=0)
    error: Optional[str] = None


@app.get("/mind", tags=["intelligence"])
@limiter.limit("60/minute")
async def mind_report(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Dict[str, Any]:
    """تقرير العقل الذاتي: مهاراته، معايرة ثقته، دروسه، وخطته القادمة."""
    _auth(credentials)
    report = mind.self_report()
    report["notes"] = mind.notes()
    return report


@app.post("/mind/plan", tags=["intelligence"])
@limiter.limit("120/minute")
async def mind_plan(
    request: Request, req: MindPlanRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """يسأل العقل: ما أفضل مسار لهذا النوع الآن؟ ولماذا؟"""
    _auth(credentials)
    decision = mind.think(
        captcha_type=req.captcha_type,
        difficulty=req.difficulty,
        external_available=req.external_available,
        prefer_speed=req.prefer_speed,
    )
    return decision.to_dict()


@app.post("/mind/observe", tags=["intelligence"])
@limiter.limit("120/minute")
async def mind_observe(
    request: Request, req: MindObserveRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """يغذّي العقل بنتيجة خارجية (من عميل أو متصفح) ليتعلّم منها."""
    _auth(credentials)
    cycle = mind.learn(
        captcha_type=req.captcha_type,
        success=req.success,
        confidence=req.confidence,
        latency_ms=req.latency_ms,
        error=req.error,
    )
    return {
        "cycle": cycle.to_dict(),
        "self_rating": mind.competence.self_rating(),
        "notes": mind.notes()[:3],
    }


@app.get("/mind/accept", tags=["intelligence"])
@limiter.limit("120/minute")
async def mind_accept(
    request: Request,
    confidence: float = Query(0.7, ge=0.0, le=1.0),
    threshold: Optional[float] = Query(None, ge=0.0, le=1.0),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """هل نقبل نتيجة بثقة معيّنة أم نعيد المحاولة؟ (قرار بالقيمة المتوقعة)."""
    _auth(credentials)
    return mind.should_accept(confidence, threshold)


@app.get("/mind/skills", tags=["intelligence"])
@limiter.limit("60/minute")
async def mind_skills(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Dict[str, Any]:
    """كفاءة النظام لكل نوع: ترتيب، نقاط قوة وضعف، وتقييم عام."""
    _auth(credentials)
    return mind.competence.snapshot()


@app.get("/mind/calibration", tags=["intelligence"])
@limiter.limit("60/minute")
async def mind_calibration(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Dict[str, Any]:
    """منحنى المعايرة: كيف تُترجم الثقة الخامّة إلى احتمال نجاح فعلي."""
    _auth(credentials)
    return mind.calibrator.snapshot()


@app.get("/mind/reflect", tags=["intelligence"])
@limiter.limit("60/minute")
async def mind_reflect(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Dict[str, Any]:
    """الدروس المستفادة من الإخفاقات ومدى فعّالية النصائح."""
    _auth(credentials)
    snapshot = mind.reflector.snapshot()
    snapshot["next_experiment"] = mind.next_experiment()
    return snapshot


@app.post("/mind/save", tags=["intelligence"])
@limiter.limit("10/minute")
async def mind_save(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Dict[str, Any]:
    """يحفظ حالة العقل (معايرة، كفاءة، دورات) على القرص الآن."""
    _auth(credentials)
    mind.save()
    return {"ok": True, "cycles": mind.total_cycles}


# --------- الذخيرة المعرفية: بطاقات معلومات وكويز ----------

@app.get("/knowledge", tags=["intelligence"])
@limiter.limit("120/minute")
async def list_knowledge(
    request: Request,
    category: Optional[str] = Query(None, description="type / technique / risk"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """كل بطاقات المعرفة (معلومات، تقنيات، مصائد) مرتبة حسب الفئة."""
    _auth(credentials)
    cards = knowledge_catalog(category)
    return {
        "count": len(cards),
        "category": category,
        "cards": cards,
    }


@app.get("/knowledge/for/{captcha_type}", tags=["intelligence"])
@limiter.limit("120/minute")
async def knowledge_for_type(
    request: Request, captcha_type: str,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """معرفة العقل عن نوع معيّن + شرح قراره ومصائده."""
    _auth(credentials)
    return mind.explain(captcha_type)


@app.get("/knowledge/quiz", tags=["intelligence"])
@limiter.limit("60/minute")
async def knowledge_quiz_endpoint(
    request: Request,
    limit: int = Query(5, ge=1, le=20),
    seed: Optional[int] = Query(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """أسئلة تدريب مولّدة من الذخيرة (لتقييم معرفة النظام/المستخدم)."""
    _auth(credentials)
    items = knowledge_quiz(limit=limit, seed=seed)
    return {"count": len(items), "questions": items}


@app.post("/knowledge/quiz/answer", tags=["intelligence"])
@limiter.limit("120/minute")
async def knowledge_quiz_answer(
    request: Request,
    card: str = Query(...),
    chosen_index: int = Query(..., ge=0),
    correct_index: int = Query(..., ge=0),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """يقيّم إجابة ويغذّي العقل بنتيجة الفهم (نجاح/إخفاق معرفي)."""
    _auth(credentials)
    correct = chosen_index == correct_index
    cycle = mind.learn(
        captcha_type=f"knowledge:{card}",
        success=correct,
        confidence=0.9 if correct else 0.4,
        latency_ms=0,
        error=None if correct else f"خطأ معرفي في البطاقة {card}",
    )
    return {
        "correct": correct,
        "lesson": cycle.lesson,
        "self_rating": mind.competence.self_rating(),
    }


# --------- أدوات مساعدة: العمليات الحسابية والبيانات الصناعية ----------

class MathRequest(BaseModel):
    expression: str = Field(..., description="تعبير حسابي مثل 5+3 أو 12 × 4")
    image_b64: Optional[str] = Field(None, description="بدلًا من التعبير: صورة كبتشا حسابية")


class MathResponse(BaseModel):
    success: bool
    expression: Optional[str] = None
    answer: Optional[str] = None
    error: Optional[str] = None


@app.post("/math/evaluate", response_model=MathResponse, tags=["solving"])
@limiter.limit("120/minute")
async def math_evaluate(
    request: Request, req: MathRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> MathResponse:
    """يحسب تعبيرًا حسابيًا بأمان، أو يقرأ صورة كبتشا حسابية ويحلّها."""
    _auth(credentials)

    if req.image_b64:
        image_bytes = _decode_b64(req.image_b64)
        if not image_bytes:
            raise HTTPException(status_code=400, detail="image_b64 غير صالح")
        result = await registry.solve_async(CaptchaType.MATH, image_bytes=image_bytes)
        return MathResponse(
            success=result.success,
            expression=(result.metadata or {}).get("expression"),
            answer=result.text,
            error=result.error,
        )

    expression = normalize_expression(req.expression)
    ok, value, error = evaluate_expression(expression)
    if not ok or value is None:
        return MathResponse(success=False, expression=expression, error=error)
    from solver_engine.math import format_number

    return MathResponse(success=True, expression=expression, answer=format_number(value))


class SyntheticRequest(BaseModel):
    count: int = Field(5, ge=1, le=200, description="عدد العينات")
    length: int = Field(4, ge=1, le=12, description="عدد أحرف كل كبتشا")
    charset: Optional[str] = Field(None, description="مجموعة الأحرف المسموحة")
    width: int = Field(160, ge=60, le=600)
    height: int = Field(60, ge=24, le=300)
    seed: Optional[int] = Field(None, description="بذرة عشوائية للتكرار")
    with_png: bool = Field(True, description="إرجاع الصور PNG بترميز base64")


@app.post("/synthetic/batch", tags=["training"])
@limiter.limit("20/minute")
async def synthetic_batch(
    request: Request, req: SyntheticRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """يُولّد دفعة صور كبتشا صناعية مع تسمياتها (لتدريب CNN أو الاختبار)."""
    _auth(credentials)
    from solver_engine.synthetic import DEFAULT_CHARSET

    items = generate_synthetic_batch(
        count=req.count,
        length=req.length,
        charset=req.charset or DEFAULT_CHARSET,
        width=req.width,
        height=req.height,
        seed=req.seed,
    )
    if not req.with_png:
        for item in items:
            item.pop("png_base64", None)
    return {
        "count": len(items),
        "charset": req.charset or DEFAULT_CHARSET,
        "items": items,
    }


@app.get("/synthetic/sample", tags=["training"])
@limiter.limit("60/minute")
async def synthetic_sample(
    request: Request,
    length: int = Query(4, ge=1, le=12),
    seed: Optional[int] = Query(None),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Any:
    """يُرجع صورة كبتشا صناعية واحدة كملف PNG مباشرة (مفيد للاختبار السريع)."""
    _auth(credentials)
    from fastapi.responses import Response as FastAPIResponse
    from solver_engine.synthetic import encode_png, generate_sample

    image, text = generate_sample(length=length, seed=seed)
    return FastAPIResponse(
        content=encode_png(image),
        media_type="image/png",
        headers={"X-Captcha-Text": text},
    )


class BatchSolveItem(BaseModel):
    image_b64: str
    captcha_type: Optional[str] = None
    template_b64: Optional[str] = None


class BatchSolveRequest(BaseModel):
    items: List[BatchSolveItem] = Field(..., min_length=1, max_length=200)
    captcha_type: Optional[str] = Field(None, description="نوع افتراضي لكل العناصر")
    preprocess: bool = True


@app.post("/batch/solve", tags=["solving"])
@limiter.limit("20/minute")
async def batch_solve(
    request: Request, req: BatchSolveRequest,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    """يحل حتى 200 كبتشا في طلب واحد (متزامن، مناسب للصور الصغيرة)."""
    _auth(credentials)
    if len(req.items) > POLICY.max_batch_items:
        raise HTTPException(
            status_code=413,
            detail=f"الحد الأقصى {POLICY.max_batch_items} عنصرًا لكل طلب",
        )
    import asyncio

    async def _one(index: int, item: BatchSolveItem) -> Dict[str, Any]:
        image_bytes = _decode_b64(item.image_b64)
        if not image_bytes:
            return {
                "index": index,
                "success": False,
                "error": "image_b64 غير صالح",
            }
        type_name = item.captcha_type or req.captcha_type or "image"
        try:
            ctype = CaptchaType(type_name)
        except ValueError:
            return {
                "index": index,
                "success": False,
                "error": f"نوع كبتشا غير مدعوم: {type_name}",
            }
        kwargs: Dict[str, Any] = {"image_bytes": image_bytes}
        template_bytes = _decode_b64(item.template_b64)
        if template_bytes:
            kwargs["template_bytes"] = template_bytes
        started = time.time()
        result = await registry.solve_async(ctype, **kwargs)
        db.record_attempt(
            captcha_type=ctype.value,
            success=result.success,
            confidence=result.confidence,
            response_time_ms=result.response_time_ms,
            error=result.error,
        )
        return {
            "index": index,
            "captcha_type": ctype.value,
            "success": result.success,
            "text": result.text,
            "token": result.token,
            "confidence": result.confidence,
            "response_time_ms": result.response_time_ms,
            "error": result.error,
            "total_ms": int((time.time() - started) * 1000),
        }

    results = await asyncio.gather(
        *[_one(i, item) for i, item in enumerate(req.items)]
    )
    succeeded = sum(1 for r in results if r.get("success"))
    return {
        "count": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
        "success_rate": round(succeeded / len(results) * 100, 2) if results else 0.0,
        "results": results,
    }


# --------- التحسين الذاتي ----------

@app.get("/self-improve/stats")
@limiter.limit("60/minute")
async def self_improve_stats(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    _auth(credentials)
    return self_improver.stats()


@app.post("/self-improve/confirm/{sample_id}")
@limiter.limit("60/minute")
async def self_improve_confirm(
    request: Request, sample_id: str,
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
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    _auth(credentials)
    return self_improver.maybe_retrain()


# --------- تجربة النظام والمعرفة ----------

@app.get("/experience/stats")
@limiter.limit("60/minute")
async def experience_stats(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    _auth(credentials)
    return experience_engine.status()


@app.get("/experience/knowledge")
@limiter.limit("60/minute")
async def experience_knowledge(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
) -> Dict[str, Any]:
    _auth(credentials)
    return knowledge_base.stats()


@app.post("/experience/find")
@limiter.limit("60/minute")
async def experience_find(
    request: Request, req: ExperienceFindRequest,
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
    request: Request, req: ConfigureHCaptchaExternalRequest,
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


@app.get("/status", tags=["system"])
async def service_status() -> Dict[str, Any]:
    """ملخّص الملاءمة التشغيلية: الوضع، الحدود، الحمل الحالي، وقدرات الحل."""
    caps = get_capabilities()
    snapshot = worker.snapshot()
    return {
        "service": "nonecap-clone",
        "version": API_VERSION,
        "mode": "unlimited" if POLICY.unlimited else "guarded",
        "free": True,
        "policy": POLICY.to_dict(),
        "requires_api_key": POLICY.require_api_key,
        "supported_types": caps["supported_types"],
        "solvers": caps["total_solvers"],
        "load": {
            "worker_running": bool(snapshot.get("running")),
            "concurrency": snapshot.get("concurrency"),
            "queued": snapshot.get("queued", 0),
            "processed": snapshot.get("processed", 0),
        },
        "storage": {
            "jobs_in_memory": len(JOBS),
            "job_ttl_seconds": POLICY.job_ttl_seconds,
            "max_jobs": POLICY.max_jobs_retained,
        },
    }


@app.get("/health", tags=["system"])
async def health() -> Dict[str, Any]:
    """فحص صحة شامل: حالة السيرفر، قاعدة البيانات، والعامل الخلفي."""
    worker_snapshot = worker.snapshot()
    return {
        "status": "ok",
        "service": "nonecap-clone",
        "version": API_VERSION,
        "database": "sqlite/postgres" if getattr(db, "_available", False) else "memory",
        "worker": {
            "running": bool(worker_snapshot.get("running")),
            "processed": worker_snapshot.get("processed", 0),
            "queued": worker_snapshot.get("queue_size", 0),
        },
    }


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Any:
    """مقاييس Prometheus بصيغة النص القياسية (صالحة للسكراب مباشرة)."""
    if not _PROM_AVAILABLE:
        return JSONResponse(
            status_code=503,
            content={"error": "prometheus_client غير مثبت"},
        )
    from fastapi.responses import Response as FastAPIResponse
    from prometheus_client import generate_latest

    return FastAPIResponse(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/capabilities", tags=["system"])
async def capabilities() -> Dict[str, Any]:
    """أنواع الكبتشا المدعومة فعليًا مع المحرّكات المسجّلة لكل نوع."""
    data = get_capabilities()
    data["version"] = API_VERSION
    data["external_services"] = {
        "hcaptcha": len(get_hcaptcha_service_stats()),
    }
    return data


@app.get("/types", tags=["system"], include_in_schema=False)
async def list_types() -> Dict[str, Any]:
    """اختصار: قائمة أنواع الكبتشا المدعومة فقط."""
    return {"types": get_capabilities()["supported_types"]}


def _auth(
    credentials: Optional[HTTPAuthorizationCredentials],
    x_api_key: Optional[str] = None,
    api_key_query: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    api_key = extract_api_key(credentials, x_api_key, api_key_query)
    if not api_key:
        if POLICY.require_api_key:
            raise HTTPException(status_code=401, detail="مفتاح API مطلوب")
        return None  # وضع مفتوح: بلا مفتاح
    # أولاً تحقق من المفتاح في قاعدة البيانات الآمنة (مشفّر)
    key_info = secure_db.verify_api_key(api_key)
    if key_info:
        return key_info
    # fallback إلى المتجر في الذاكرة (للتوافق مع التكوين القديم)
    info = api_key_store.validate(api_key)
    if not info:
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح")
    if not POLICY.unlimited and api_key_store.is_rate_limited(info["key_id"]):
        raise HTTPException(status_code=429, detail="تم تجاوز الحد المسموح للمفتاح")
    api_key_store.record_usage(info["key_id"])
    return info
