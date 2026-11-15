"""سيرفر API متكامل لحل الكبتشا (FastAPI)."""

import base64
import json
import uuid
import time
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone

from fastapi import FastAPI, File, Form, UploadFile, HTTPException, WebSocket, WebSocketDisconnect, Depends, Query
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
    try:
        yield
    finally:
        await worker.stop()


app = FastAPI(title="NoneCap Clone API", version="0.5.0", lifespan=lifespan)
app.state.limiter = limiter

# خدمة الملفات الثابتة للوحة الويب
app.mount("/static", StaticFiles(directory="web/static"), name="static")


@app.get("/web", response_class=HTMLResponse)
async def web_dashboard() -> Any:
    return FileResponse("web/templates/dashboard.html")

# مهام غير متزامنة قيد ejecución
JOBS: Dict[str, Dict[str, Any]] = {}
# WebSocket العملاء المرتبطين بكل وظيفة
JOB_SUBSCRIBERS: Dict[str, list] = {}


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
    callback_url = kwargs.pop("callback_url", None)
    JOBS[job_id]["status"] = "processing"
    await _publish(job_id, {"job_id": job_id, "status": "processing"})
    try:
        if decision is not None and decision.strategy == "ensemble_with_fallback":
            solvers = registry.get_solvers(captcha_type)
            result = strategy.ensemble_solve(solvers, captcha_type, **kwargs)
        else:
            use_local = decision.use_local if decision else True
            result = await registry.solve_async(
                captcha_type, prefer_local=use_local, **kwargs
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
        await _publish(
            job_id,
            {
                "job_id": job_id,
                "status": JOBS[job_id]["status"],
                "result": result.to_dict(),
                "alerts": [a.__dict__ for a in new_alerts],
            },
        )
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
        await _publish(job_id, {"job_id": job_id, "status": "failed", "error": str(exc)})
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


@app.websocket("/ws/job/{job_id}")
async def ws_job(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()
    JOB_SUBSCRIBERS.setdefault(job_id, []).append(websocket)
    # إرسال الحالة الحالية فورًا
    job = JOBS.get(job_id)
    if job:
        await websocket.send_json({"job_id": job_id, "status": job["status"], "result": job.get("result")})
    try:
        while True:
            await websocket.receive_text()  # إبقاء الاتصال مفتوحًا
    except WebSocketDisconnect:
        pass
    finally:
        if job_id in JOB_SUBSCRIBERS and websocket in JOB_SUBSCRIBERS[job_id]:
            JOB_SUBSCRIBERS[job_id].remove(websocket)


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

    result = await asyncio.to_thread(
        orchestrator.solve,
        captcha_type=captcha_type,
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


@app.get("/metrics")
async def metrics() -> Response:
    if not _PROM_AVAILABLE:
        return Response(content="# prometheus_client غير مثبت\n".encode("utf-8"), media_type=CONTENT_TYPE_LATEST)
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def _auth(
    credentials: Optional[HTTPAuthorizationCredentials],
    x_api_key: Optional[str] = None,
    api_key_query: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    api_key = extract_api_key(credentials, x_api_key, api_key_query)
    if not api_key:
        return None  # التجريب محلياً دون مفتاح
    info = api_key_store.validate(api_key)
    if not info:
        raise HTTPException(status_code=401, detail="مفتاح API غير صالح")
    if api_key_store.is_rate_limited(info["key_id"]):
        raise HTTPException(status_code=429, detail="تم تجاوز الحد المسموح للمفتاح")
    api_key_store.record_usage(info["key_id"])
    return info
