"""حلّ hCaptcha عبر بروتوكول hCaptcha العام نفسه (بلا أي خدمة مدفوعة).

الفكرة: خدمة hCaptcha تكشف ``/checksiteconfig`` ثم ``/getcaptcha``. تُستخرج
الصور، يُقرأ نصها بواسطة OCR المحلي (Tesseract)، ثم تُرسل الإجابة إلى
``/checkcaptcha`` للحصول على ``pass_token`` — وهو نفس التسلسل الذي تقوم به
الواجهة في المتصفح.

الحدود الصريحة:
- التحديات متعددة الصور («اختر كل ما يحتوي على…») تحتاج نماذج كشف كائنات،
  وهذا المشروع لا يستخدمها؛ لذا هذا المسار يعمل مع التحديات النصية فقط.
- hCaptcha أحيانًا تُرجع تحديًا بلا صور نصية → يفشل المسار بصراحة.
- إن حجب مزوّد الشبكة نطاق hCaptcha (كما في بيئات الحوسبة السحابية أحيانًا)
  فلن يعمل شيء حتى تُمرَّر الطلبات عبر وكيل/نفق: ``NONECAP_HCAPTCHA_PROXY``.

كل الاستدعاءات تمرّ عبر ``solver_engine.net.NETWORK`` لتحترم الوكيل والمهلة.
"""

from __future__ import annotations

import base64
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .base import BaseSolver, CaptchaType, SolverResult
from .net import NETWORK, hcaptcha_base_url
from .abstain import decide as decide_abstain
from .abstain import threshold_for_round
from .resilience import (
    AttemptLog,
    TimeoutExceeded,
    get_breaker,
    run_with_timeout,
)

_IMAGE_KEYS = ("image_urls", "images", "image", "image_url")


@dataclass
class Challenge:
    """تحدي hCaptcha واحد."""

    kind: str  # "text" | "multi_image" | "unsupported"
    prompt: str
    image_urls: List[str] = field(default_factory=list)
    key: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict)


def _dig(obj: Any, *keys: str) -> Any:
    """يبحث عن أول مفتاح موجود في قاموس متداخل."""
    if not isinstance(obj, dict):
        return None
    for key in keys:
        if key in obj and obj[key]:
            return obj[key]
    return None


def parse_challenge(payload: Dict[str, Any]) -> Challenge:
    """يحوّل استجابة hCaptcha الخام إلى ``Challenge`` مفهومة."""
    # الاستجابة قد تكون ملفوفة داخل {"c": ...} أو مباشرة
    body: Dict[str, Any] = payload
    if isinstance(payload.get("c"), dict):
        body = payload["c"]

    req_type = str(_dig(body, "request_type", "type") or "").lower()
    prompt = str(_dig(body, "requester_question", "question", "prompt") or "")
    if isinstance(_dig(body, "requester_question"), dict):
        prompt = str(_dig(_dig(body, "requester_question"), "ar", "en") or prompt)

    urls: List[str] = []
    for key in _IMAGE_KEYS:
        value = body.get(key)
        if isinstance(value, list):
            urls.extend(str(v) for v in value if v)
        elif isinstance(value, str) and value:
            urls.append(value)

    key = _dig(body, "key", "generated_pass_UUID", "challenge_key")

    if urls:
        kind = "multi_image" if len(urls) > 1 or "image" in req_type else "text"
        if len(urls) > 1:
            kind = "multi_image"
        return Challenge(kind=kind, prompt=prompt, image_urls=urls, key=key, raw=body)

    if req_type in ("text", "image_label_binary", "image_label_area_select"):
        return Challenge(kind=req_type, prompt=prompt, key=key, raw=body)

    return Challenge(kind="unsupported", prompt=prompt, key=key, raw=body)


def _absolute_url(url: str) -> str:
    """يحوّل الروابط النسبية إلى مطلقة (hCaptcha قد تُرجع مسارات نسبية)."""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    base = hcaptcha_base_url()
    if url.startswith("//"):
        return "https:" + url
    return base.rstrip("/") + "/" + url.lstrip("/")


def _download_image(url: str) -> Optional[bytes]:
    """تنزيل صورة التحدي عبر إعدادات الشبكة (وكيل/مهلة)."""
    import httpx

    url = _absolute_url(url)
    try:
        with httpx.Client(**NETWORK.client_kwargs()) as client:
            resp = client.get(url, headers=NETWORK.headers({"Accept": "image/*"}))
            resp.raise_for_status()
            return resp.content
    except Exception:  # noqa: BLE001
        return None


OCR_CHARSET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

# ترتيبات مختلفة لطرق العرض — كل جولة تبدأ من طريقة أخرى، فتنويع القراءة
# بدل تكرار نفس الخطأ. مبني على ما قِيس فعليًا: القصّ+حشو كبير، والقصّ+مطّ
# عمودي، والقراءة البسيطة المحشوّة.
ROUND_ORDERS: List[List[str]] = [
    ["crop_pad", "padded", "crop_pad_tall", "upscaled"],
    ["padded", "crop_pad_tall", "upscaled", "crop_pad"],
    ["crop_pad_tall", "upscaled", "crop_pad", "padded"],
    ["upscaled", "crop_pad", "padded", "crop_pad_tall"],
]


def _retry_suggestion(attempted: List[Dict[str, Any]], last_error: str) -> str:
    """توصية عملية مبنية على سبب الفشل الفعلي (لا نص عام)."""
    if not attempted:
        return "لم تُقرأ أي إجابة. تحقّق من الوكيل/الشبكة ثم أعد المحاولة."
    certainties = [float(item.get("certainty") or 0.0) for item in attempted]
    best = max(certainties) if certainties else 0.0
    if best < 0.4:
        return (
            "كل القراءات كانت منخفضة الثقة (الصورة صعبة/مشوّشة). "
            "أعد الطلب للحصول على تحدٍّ آخر، أو ارفع max_rounds."
        )
    if "invalid" in (last_error or "").lower() or "مرفوض" in (last_error or ""):
        return (
            "القراءة كانت واثقة لكن hCaptcha رفضتها — غالبًا حرف متشابه بصريًا "
            "(O/0، I/1، S/5). أعد المحاولة: النظام يضيّق الاحتمالات تلقائيًا "
            "بعد كل رفض."
        )
    return "أعد المحاولة بعد لحظات؛ إن تكرر الفشل راجع السجل في metadata.logs."


def _read_text_detailed(
    data: bytes,
    expected_len: Optional[int] = None,
    deep: bool = False,
    order: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """قراءة كاملة لصورة تحدي مع كل مؤشرات الثقة (قابلة للتفسير والتشخيص).

    ``deep=True`` يوسّع طرق العرض إلى أقصى مستوى (تصحيح ميل، إزالة خطوط،
    تباين) — يُستخدم فقط عند الشك، حفاظًا على السرعة.
    """
    from .ocr import read_text_bytes

    result = read_text_bytes(
        data,
        allowlist=OCR_CHARSET,
        expected_len=expected_len,
        ensemble=True,
        level="max" if deep else "balanced",
        order=order,
    )
    payload = result.to_dict()
    payload["text"] = result.text if result.success else None
    return payload


def _read_text_from(url: str, expected_len: Optional[int] = None) -> Tuple[Optional[str], float, str]:
    """يقرأ نص التحدي من صورة عبر المحرّك الموحّد (متوافق مع الإصدار السابق)."""
    data = _download_image(url)
    if not data:
        return None, 0.0, "download_failed"
    details = _read_text_detailed(data, expected_len=expected_len)
    return details.get("text"), float(details.get("confidence") or 0.0), str(
        details.get("engine") or "none"
    )


def _learn(details: Dict[str, Any], accepted: bool, answer: str) -> None:
    """يغذّي سياسة التعلّم بنتيجة حقيقية من hCaptcha (قبول/رفض).

    هذا هو أهم مصدر تعلّم: حكم الخدمة نفسها على إجابتنا. نستخدمه لمعايرة
    الثقة (هل 0.9 تعني فعلًا 90%؟) ولبناء سجل نجاح لكل طريقة عرض/سياق.
    لا يفشل المسار إن تعذّر التعلّم (مثلًا في اختبارات معزولة).
    """
    try:
        from intelligence.ocr_policy import get_policy

        policy = get_policy()
        confidence = float(details.get("confidence") or 0.0)
        policy.observe_confidence(confidence, accepted)
        context = str(details.get("context") or "unknown")
        engine = str(details.get("engine") or "none")
        # اسم طريقة العرض الحقيقية إن عُرف، وإلا اسم المحرّك
        strategy = str(details.get("strategy") or engine).split(":")[-1]
        policy.record(
            context,
            strategy,
            expected=answer if accepted else None,
            got=answer,
            accepted=accepted,
        )
    except Exception:  # noqa: BLE001 - التعلّم تحسين لا شرط للعمل
        pass


def _calibrated_probability(details: Dict[str, Any]) -> Optional[float]:
    """احتمال نجاح الإجابة بحسب التعلّم السابق (None إن لم تتوفر سياسة)."""
    try:
        from intelligence.ocr_policy import get_policy

        confidence = float(details.get("confidence") or 0.0)
        return float(get_policy().calibrated(confidence))
    except Exception:  # noqa: BLE001
        return None


def _certainty(details: Dict[str, Any]) -> float:
    """ثقة مركّبة: الثقة المصحّحة × اتساق الطول × عدد طرق العرض المتوافقة.

    الغرض: التمييز بين «قراءة واثقة حقًا» و«قراءة ناقصة بثقة خام عالية»، لأن
    الثانية يجب أن تُقابل بمحاولة جديدة بدلًا من إرسال إجابة خاطئة.
    """
    confidence = float(details.get("confidence") or 0.0)
    sanity = float(details.get("plausibility") or 0.0)
    text = details.get("text") or ""
    length_factor = 1.0 if len(text) >= 3 else 0.55
    return confidence * sanity * length_factor


class HCaptchaLiveSolver(BaseSolver):
    """يحل تحديات hCaptcha النصية عبر الواجهة العامة مباشرة."""

    captcha_type = CaptchaType.HCAPTCHA

    def __init__(
        self,
        max_rounds: int = 2,
        deadline_seconds: float = 120.0,
        call_timeout: Optional[float] = None,
        abstain_threshold: float = 0.45,
        allow_abstain: bool = True,
    ) -> None:
        self.max_rounds = max(1, max_rounds)
        # عتبة الامتناع: أقل من هذا الاحتمال نطلب تحدٍّ جديدًا بدل إحراق محاولة
        self.abstain_threshold = abstain_threshold
        self.allow_abstain = allow_abstain
        # مهلة كل استدعاء شبكي/قراءة (افتراضيًا مهلة الشبكة + هامش)
        self.call_timeout = call_timeout or max(10.0, NETWORK.timeout_seconds)
        # سقف زمني كلي: لا يسمح لأي مسار أن يعلّق الطلب إلى الأبد
        self.deadline_seconds = max(10.0, deadline_seconds)

    # ---------- مساعدات الاحتياط ----------

    def _guard(self, func, *args, timeout: Optional[float] = None, name: str = "call", **kwargs):
        """ينفّذ استدعاء بمهلة صارمة — يحوّل التعلّق إلى فشل صريح."""
        return run_with_timeout(
            func, *args, timeout=timeout or self.call_timeout, name=name, **kwargs
        )

    @staticmethod
    def _breaker():
        return get_breaker(
            "hcaptcha", failure_threshold=3, recovery_seconds=20.0
        )

    # ---------- بروتوكول hCaptcha ----------

    def checksiteconfig(self, sitekey: str, url: str, host: str = "accounts.hcaptcha.com") -> Dict[str, Any]:
        """الخطوة 1: هل التحدي مطلوب، وما الإعدادات؟"""
        import httpx

        params = {
            "host": host,
            "sitekey": sitekey,
            "sc": "1",
            "swa": "1",
            "sp": "1",
        }
        with httpx.Client(**NETWORK.client_kwargs()) as client:
            resp = client.get(
                f"{hcaptcha_base_url()}/checksiteconfig",
                params=params,
                headers=NETWORK.headers({"Referer": url, "Origin": "https://" + host}),
            )
            resp.raise_for_status()
            return resp.json()

    def getcaptcha(
        self,
        sitekey: str,
        url: str,
        host: str = "accounts.hcaptcha.com",
        req_config: Optional[str] = None,
        host_token: str = "",
    ) -> Dict[str, Any]:
        """الخطوة 2: طلب التحدي."""
        import httpx

        payload = {
            "sitekey": sitekey,
            "host": host,
            "hl": "en",
            "motionData": "{}",
            "hostToken": host_token or None,
            "n": req_config,
            "v": "1.2.0",
            "c": "{}",
        }
        with httpx.Client(**NETWORK.client_kwargs()) as client:
            resp = client.post(
                f"{hcaptcha_base_url()}/getcaptcha/{sitekey}",
                json=payload,
                headers=NETWORK.headers({"Referer": url, "Origin": "https://" + host}),
            )
            resp.raise_for_status()
            return resp.json()

    def checkcaptcha(self, sitekey: str, answer: str, key: str, host: str = "accounts.hcaptcha.com") -> Dict[str, Any]:
        """الخطوة 3: إرسال الإجابة واستلام pass_token عند النجاح."""
        import httpx

        payload = {"sitekey": sitekey, "host": host, "text": answer, "key": key}
        with httpx.Client(**NETWORK.client_kwargs()) as client:
            resp = client.post(
                f"{hcaptcha_base_url()}/checkcaptcha",
                json=payload,
                headers=NETWORK.headers({"Origin": "https://" + host}),
            )
            resp.raise_for_status()
            return resp.json()

    # ---------- التنفيذ ----------

    def solve(  # type: ignore[override]
        self,
        sitekey: Optional[str] = None,
        url: Optional[str] = None,
        host: Optional[str] = None,
        **kwargs: Any,
    ) -> SolverResult:
        start = time.time()
        if not sitekey or not url:
            return SolverResult(
                success=False,
                captcha_type=self.captcha_type,
                error="hCaptcha المباشر يحتاج sitekey و url",
                response_time_ms=0,
            )

        host = host or self._host_from_url(url)
        breaker = self._breaker()
        logs: List[AttemptLog] = []

        # 0) قاطع الدائرة: إن كانت الخدمة معطّلة الآن فلا نُهدر وقت المستخدم
        if not breaker.allow():
            wait = breaker.wait_seconds
            return SolverResult(
                success=False,
                captcha_type=self.captcha_type,
                error=(
                    "hCaptcha غير متاحة مؤقتًا (قاطع الدائرة مفتوح بعد أعطال متتالية). "
                    f"أعد المحاولة بعد ~{wait:.0f} ثانية."
                ),
                response_time_ms=int((time.time() - start) * 1000),
                metadata={
                    "stage": "circuit_open",
                    "breaker": breaker.snapshot(),
                    "retry_after_seconds": round(wait, 1),
                    **NETWORK.to_dict(),
                },
            )

        try:
            config = self._guard(
                self.checksiteconfig, sitekey, url, host, name="checksiteconfig"
            )
            breaker.record_success()
        except TimeoutExceeded as exc:
            breaker.record_failure(str(exc))
            return self._network_failure(start, "checksiteconfig", exc, logs, breaker)
        except Exception as exc:  # noqa: BLE001
            breaker.record_failure(f"{type(exc).__name__}: {exc}")
            return self._network_failure(start, "checksiteconfig", exc, logs, breaker)

        if config.get("pass") is True:
            token = _dig(config, "generated_pass_UUID", "pass_token") or ""
            return SolverResult(
                success=bool(token),
                captcha_type=self.captcha_type,
                token=token or None,
                confidence=1.0,
                response_time_ms=int((time.time() - start) * 1000),
                metadata={"stage": "checksiteconfig", "no_challenge": True, "attempts": []},
            )

        req_config = _dig(config, "c", "req") or _dig(config, "req")
        host_token = str(_dig(config, "c", "hostToken") or _dig(config, "hostToken") or "")
        last_error = ""
        last_text: Optional[str] = None
        last_engine = "none"
        last_certainty = 0.0
        last_expected_len: Optional[int] = None
        keep_expected = False
        attempted: List[Dict[str, Any]] = []
        abstained: List[Any] = []

        for round_no in range(1, self.max_rounds + 1):
            if time.time() - start > self.deadline_seconds:
                logs.append(
                    AttemptLog(round_no, "deadline", False, "انتهت المدة القصوى للطلب")
                )
                break

            try:
                captcha = self._guard(
                    self.getcaptcha,
                    sitekey,
                    url,
                    host,
                    req_config,
                    host_token,
                    name="getcaptcha",
                )
                breaker.record_success()
            except TimeoutExceeded as exc:
                breaker.record_failure(str(exc))
                return self._network_failure(start, "getcaptcha", exc, logs, breaker, attempted)
            except Exception as exc:  # noqa: BLE001
                breaker.record_failure(f"{type(exc).__name__}: {exc}")
                return self._network_failure(start, "getcaptcha", exc, logs, breaker, attempted)

            challenge = parse_challenge(captcha)
            if challenge.kind == "unsupported" or not challenge.image_urls:
                logs.append(AttemptLog(round_no, "parse", False, challenge.kind))
                return SolverResult(
                    success=False,
                    captcha_type=self.captcha_type,
                    error=(
                        "التحدي ليس نصيًا (يحتاج نماذج كشف كائنات) — "
                        f"النوع: {challenge.kind}"
                    ),
                    response_time_ms=int((time.time() - start) * 1000),
                    metadata={
                        "stage": "parse",
                        "challenge_kind": challenge.kind,
                        "prompt": challenge.prompt,
                        "unsupported": True,
                        "suggestion": (
                            "أعد الطلب للحصول على تحدٍّ نصي، أو استخدم مسارًا "
                            "بخدمة كشف كائنات (غير مضمّن)."
                        ),
                        "attempts": [log.to_dict() for log in logs],
                    },
                )

            if len(challenge.image_urls) > 1:
                logs.append(AttemptLog(round_no, "parse", False, "multi_image"))
                return SolverResult(
                    success=False,
                    captcha_type=self.captcha_type,
                    error=(
                        f"تحدي متعدد الصور ({len(challenge.image_urls)} صورة) — "
                        "يحتاج كشف كائنات لا يتوفر محليًا"
                    ),
                    response_time_ms=int((time.time() - start) * 1000),
                    metadata={
                        "stage": "parse",
                        "prompt": challenge.prompt,
                        "unsupported": True,
                        "attempts": [log.to_dict() for log in logs],
                    },
                )

            if not challenge.key:
                logs.append(AttemptLog(round_no, "parse", False, "no_key"))
                return SolverResult(
                    success=False,
                    captcha_type=self.captcha_type,
                    error="لا يوجد مفتاح تحدي في استجابة hCaptcha",
                    response_time_ms=int((time.time() - start) * 1000),
                    metadata={"stage": "parse", "attempts": [log.to_dict() for log in logs]},
                )

            data = _download_image(challenge.image_urls[0])
            if not data:
                logs.append(AttemptLog(round_no, "download", False, "فشل تنزيل الصورة"))
                last_error = "تعذّر تنزيل صورة التحدي (شبكة/وكيل)"
                continue  # تحدٍّ جديد قد يحمل صورة أوضح

            # تنويع مقصود: كل جولة تبدأ من طريقة عرض مختلفة حتى لا نكرّر
            # نفس الخطأ عندما يعيد الخادم صورة مشابهة.
            order = ROUND_ORDERS[(round_no - 1) % len(ROUND_ORDERS)]
            try:
                details = self._guard(
                    _read_text_detailed,
                    data,
                    expected_len=last_expected_len if keep_expected else None,
                    deep=round_no >= 3,
                    order=order,
                    name="ocr",
                )
            except TimeoutExceeded as exc:
                logs.append(
                    AttemptLog(round_no, "ocr", False, f"تجاوز مهلة القراءة: {exc}")
                )
                last_error = "تعذّر قراءة الصورة في الوقت المحدد"
                continue

            text = details.get("text")
            confidence = float(details.get("confidence") or 0.0)
            engine = str(details.get("engine") or "none")
            if not text:
                logs.append(AttemptLog(round_no, "ocr", False, "لا نص مقروء"))
                last_error = "تعذّر قراءة نص التحدي من الصورة"
                last_engine = engine
                continue

            certainty = _certainty(details)
            attempted.append(
                {
                    "round": round_no,
                    "answer": text,
                    "certainty": round(certainty, 4),
                    "strategy": details.get("strategy"),
                    "ocr": details,
                }
            )
            logs.append(
                AttemptLog(
                    round_no,
                    "ocr",
                    True,
                    text,
                    extra={
                        "confidence": round(confidence, 4),
                        "certainty": round(certainty, 4),
                        "strategy": details.get("strategy"),
                    },
                )
            )
            last_text, last_engine, last_certainty = text, engine, certainty

            # بوّابة الثقة: قراءة غير واثقة تُقرأ مرة أخرى بعمق أكبر قبل
            # إحراق جولة — إعادة القراءة أرخص من إجابة مرفوضة.
            if round_no < self.max_rounds:
                probable = _calibrated_probability(details)
                if probable is not None and probable < 0.35:
                    try:
                        deep = self._guard(
                            _read_text_detailed,
                            data,
                            deep=True,
                            expected_len=None,
                            order=list(reversed(ROUND_ORDERS[0])),
                            name="ocr_deep",
                        )
                    except Exception:  # noqa: BLE001 - التعميق اختياري
                        deep = {}
                    if deep.get("text") and deep.get("confidence", 0) > confidence:
                        details, text = deep, deep["text"]
                        confidence = float(deep.get("confidence") or 0.0)
                        engine = str(deep.get("engine") or engine)
                        attempted.append(
                            {
                                "round": round_no,
                                "answer": text,
                                "certainty": round(_certainty(details), 4),
                                "strategy": details.get("strategy"),
                                "ocr": details,
                                "escalated": True,
                            }
                        )
                        logs.append(
                            AttemptLog(
                                round_no, "escalate", True, text, extra={"reason": "low_certainty"}
                            )
                        )

            # --------- قرار الإرسال: أُرسل أم أمتنع؟ ---------
            rounds_left = self.max_rounds - round_no
            vote = decide_abstain(
                confidence=confidence,
                threshold=threshold_for_round(round_no, self.abstain_threshold),
                expected_len=len(text),
                text=text,
                rounds_left=rounds_left,
                plausibility=float(details.get("plausibility") or 0.0) or None,
            )
            abstained.append(vote)
            # الامتناع يعمل دائمًا (حتى في آخر جولة): قراءة فاشلة لا تُرسل.
            # إيقافه متاح صراحةً عبر allow_abstain=False.
            if self.allow_abstain and not vote.send:
                logs.append(
                    AttemptLog(
                        round_no,
                        "abstain",
                        False,
                        vote.reason,
                        extra={"probability": round(vote.probability, 4), "answer": text},
                    )
                )
                last_error = vote.reason
                # نتجاهل هذه القراءة ونطلب تحديًا جديدًا (بلا إرسال)
                continue

            try:
                checked = self._guard(
                    self.checkcaptcha,
                    sitekey,
                    text,
                    challenge.key,
                    host,
                    name="checkcaptcha",
                )
                breaker.record_success()
            except TimeoutExceeded as exc:
                breaker.record_failure(str(exc))
                last_error = f"checkcaptcha تجاوز المهلة: {exc}"
                logs.append(AttemptLog(round_no, "checkcaptcha", False, str(exc)))
                break
            except Exception as exc:  # noqa: BLE001
                breaker.record_failure(f"{type(exc).__name__}: {exc}")
                last_error = f"checkcaptcha فشل: {exc}"
                logs.append(AttemptLog(round_no, "checkcaptcha", False, str(exc)))
                break

            token = _dig(checked, "generated_pass_UUID", "pass_token") or ""
            if token:
                _learn(details, accepted=True, answer=text)
                logs.append(AttemptLog(round_no, "checkcaptcha", True, "token"))
                return SolverResult(
                    success=True,
                    captcha_type=self.captcha_type,
                    token=token,
                    text=text,
                    confidence=max(confidence, 0.5),
                    response_time_ms=int((time.time() - start) * 1000),
                    metadata={
                        "stage": "checkcaptcha",
                        "rounds": round_no,
                        "prompt": challenge.prompt,
                        "answer": text,
                        "ocr_confidence": round(confidence, 4),
                        "ocr_engine": engine,
                        "certainty": round(certainty, 4),
                        "ocr": details,
                        "attempts": attempted,
                        "logs": [log.to_dict() for log in logs],
                        "abstentions": [v.to_dict() for v in abstained],
                    },
                )

            _learn(details, accepted=False, answer=text)
            last_error = str(_dig(checked, "error", "message") or "إجابة مرفوضة")
            logs.append(
                AttemptLog(round_no, "checkcaptcha", False, last_error, extra={"answer": text})
            )
            # بعد الرفض: طول الإجابة المرفوضة معلومة مجانية تُستخدم كتلميح
            keep_expected = len(text) >= 3
            last_expected_len = len(text) if keep_expected else None

        attempts_meta = {
            "stage": "checkcaptcha",
            "attempts": attempted,
            "logs": [log.to_dict() for log in logs],
            "last_answer": last_text,
            "last_engine": last_engine,
            "last_certainty": round(last_certainty, 4),
            "max_rounds": self.max_rounds,
            "breaker": breaker.snapshot(),
            "abstentions": [v.to_dict() for v in abstained],
            "abstained_all": bool(abstained) and all(not v.send for v in abstained),
            "suggestion": _retry_suggestion(attempted, last_error),
        }
        if attempted:
            weakest = min(attempted, key=lambda item: item.get("certainty", 0.0))
            attempts_meta["weakest_ocr"] = weakest.get("ocr")
        return SolverResult(
            success=False,
            captcha_type=self.captcha_type,
            error=f"لم يُقبل الحل: {last_error}" if last_error else "لم يُقبل الحل",
            response_time_ms=int((time.time() - start) * 1000),
            metadata=attempts_meta,
        )

    def _network_failure(
        self,
        start: float,
        stage: str,
        exc: BaseException,
        logs: List[AttemptLog],
        breaker: Any,
        attempted: Optional[List[Dict[str, Any]]] = None,
    ) -> SolverResult:
        """استجابة فشل شبكي صريحة مع إرشاد قابل للتنفيذ (لا رسالة مبهمة)."""
        logs.append(AttemptLog(0, stage, False, f"{type(exc).__name__}: {exc}"))
        blocked = isinstance(exc, (TimeoutExceeded,)) or "SSL" in str(exc) or "Connect" in str(exc)
        hint = (
            "الشبكة قد تحجب نطاق hCaptcha (TLS/ConnectError). مرّر وكيلًا: "
            "NONECAP_HCAPTCHA_PROXY، أو شغّل الخادم على شبكة أخرى."
            if blocked
            else "خطأ غير متوقع في الشبكة؛ راجع التفاصيل."
        )
        return SolverResult(
            success=False,
            captcha_type=self.captcha_type,
            error=f"تعذّر الوصول إلى hCaptcha في مرحلة {stage} ({type(exc).__name__}: {exc}). {hint}",
            response_time_ms=int((time.time() - start) * 1000),
            metadata={
                "stage": stage,
                "blocked_likely": blocked,
                "hint": hint,
                "breaker": breaker.snapshot(),
                "attempts": attempted or [],
                "logs": [log.to_dict() for log in logs],
                **NETWORK.to_dict(),
            },
        )

    @staticmethod
    def _host_from_url(url: str) -> str:
        match = re.match(r"https?://([^/]+)", url or "")
        return match.group(1) if match else "accounts.hcaptcha.com"

    async def solve_async(self, *args: Any, **kwargs: Any) -> SolverResult:
        import asyncio

        return await asyncio.to_thread(self.solve, *args, **kwargs)


__all__ = [
    "HCaptchaLiveSolver",
    "Challenge",
    "parse_challenge",
    "ROUND_ORDERS",
]
