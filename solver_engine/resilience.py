"""احتياطات الموثوقية: مهلة زمنية صارمة، قاطع دائرة، وتكرار ذكي.

ثلاث مشاكل حقيقية في أي نظام يعتمد على شبكة وOCR، وحلّها هنا:

1. **التعلّق (hang)**: محرّك أو شبكة قد تتوقف بلا خطأ. الحل: تنفيذ في خيط
   منفصل مع مهلة صارمة — بعدها نُرجع فشلًا صريحًا لا انتظارًا أبديًا.

2. **الفشل المتكرر (thundering herd)**: عند تعطّل الخدمة، إعادة المحاولة
   فورًا تُهدر الوقت وتزيد الضغط. الحل: قاطع دائرة (circuit breaker) بحالات
   ``closed → open → half_open``، يفتح بعد فشل متكرر ويسمح بمحاولة استكشافية
   واحدة بعد فترة تهدئة (backoff أسّي).

3. **إعادة المحاولة العمياء**: تكرار نفس القراءة يعطي نفس الخطأ. الحل: كل
   محاولة تبدأ من **طريقة عرض مختلفة** (rotation) وتتصاعد في العمق، والتكرار
   يعرف متى يتوقف (نفاد المحاولات أو الثقة كافية أو الوقت انتهى).

كل شيء هنا مستقل عن أي مكتبة خارجية، وقابل للاختبار بلا شبكة.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, TypeVar

T = TypeVar("T")


# ---------------------------------------------------------------------------
# 1) التنفيذ بمهلة صارمة
# ---------------------------------------------------------------------------


class TimeoutExceeded(Exception):
    """انتهت المهلة قبل إتمام العملية."""


def run_with_timeout(
    func: Callable[..., T],
    *args: Any,
    timeout: float = 30.0,
    name: str = "process",
    **kwargs: Any,
) -> T:
    """ينفّذ ``func`` في خيط ويُلقي :class:`TimeoutExceeded` عند تجاوز المهلة.

    ملاحظة مهمة: الخيط لا يُقتل (بايثون لا يسمح بذلك بأمان)، لكن المستدعي
    يتوقف عن الانتظار ويُبلغ بفشل صريح — وهو المطلوب عمليًا لعدم تعليق الخدمة.
    """
    if timeout <= 0:
        return func(*args, **kwargs)

    outcome: Dict[str, Any] = {}

    def worker() -> None:
        try:
            outcome["value"] = func(*args, **kwargs)
        except BaseException as exc:  # noqa: BLE001 - نُعيد الخطأ كما هو للمستدعي
            outcome["error"] = exc

    thread = threading.Thread(target=worker, name=f"timeout:{name}", daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise TimeoutExceeded(f"{name}: تجاوز المهلة ({timeout:.1f} ثانية)")
    if "error" in outcome:
        raise outcome["error"]
    return outcome.get("value")  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# 2) قاطع الدائرة
# ---------------------------------------------------------------------------


@dataclass
class BreakerState:
    """حالة قاطع الدائرة لهدف واحد (خدمة/نطاق)."""

    name: str
    state: str = "closed"  # closed | open | half_open
    failures: int = 0
    successes: int = 0
    opened_at: float = 0.0
    trips: int = 0
    last_error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state,
            "failures": self.failures,
            "successes": self.successes,
            "trips": self.trips,
            "last_error": self.last_error,
            "open_for_seconds": round(time.time() - self.opened_at, 1)
            if self.state == "open"
            else 0.0,
        }


class CircuitBreaker:
    """قاطع دائرة بسيط ومقيس: لا يفتح حتى يتكرر الفشل فعلًا.

    - ``closed``: كل شيء طبيعي.
    - ``open``: ممنوع الاستدعاء حتى تنتهي مدة التهدئة.
    - ``half_open``: تُسمح محاولة واحدة لاختبار التعافي.
    """

    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 3,
        recovery_seconds: float = 20.0,
        backoff_factor: float = 1.6,
        max_recovery_seconds: float = 300.0,
    ) -> None:
        self.state = BreakerState(name=name)
        self.failure_threshold = max(1, failure_threshold)
        self.recovery_seconds = recovery_seconds
        self.backoff_factor = backoff_factor
        self.max_recovery_seconds = max_recovery_seconds
        self._lock = threading.Lock()

    def _cooldown(self) -> float:
        """مدة التهدئة الحالية، تتضاعف مع تكرار الفتح (backoff أسّي)."""
        exponent = max(0, self.state.trips - 1)
        value = self.recovery_seconds * (self.backoff_factor**exponent)
        return min(value, self.max_recovery_seconds)

    @property
    def wait_seconds(self) -> float:
        """كم بقي حتى يُسمح بمحاولة جديدة (0 = مسموح الآن)."""
        with self._lock:
            if self.state.state != "open":
                return 0.0
            remaining = self._cooldown() - (time.time() - self.state.opened_at)
            return max(0.0, remaining)

    def allow(self) -> bool:
        """هل يُسمح باستدعاء الآن؟ (ينقل ``open`` إلى ``half_open`` عند الانتهاء)"""
        with self._lock:
            if self.state.state == "closed":
                return True
            if self.state.state == "open":
                if time.time() - self.state.opened_at >= self._cooldown():
                    self.state.state = "half_open"
                    return True
                return False
            return True  # half_open: كامتحان واحد

    def record_success(self) -> None:
        with self._lock:
            self.state.successes += 1
            self.state.failures = 0
            if self.state.state != "closed":
                self.state.state = "closed"
                self.state.trips = 0

    def record_failure(self, error: str = "") -> None:
        with self._lock:
            self.state.failures += 1
            self.state.last_error = error[:300]
            if self.state.state == "half_open":
                # فشل الاختبار ⇒ فتح فوري بفترة أطول
                self.state.state = "open"
                self.state.opened_at = time.time()
                self.state.trips += 1
                return
            if self.state.failures >= self.failure_threshold:
                self.state.state = "open"
                self.state.opened_at = time.time()
                self.state.trips += 1

    def snapshot(self) -> Dict[str, Any]:
        # ملاحظة: لا نستدعي ``self.wait_seconds`` هنا لأنه يقفل نفس القفل
        # (threading.Lock غير قابل لإعادة الدخول) ⇒ كان يسبب جمودًا.
        with self._lock:
            payload = self.state.to_dict()
            if self.state.state == "open":
                remaining = self._cooldown() - (time.time() - self.state.opened_at)
                payload["wait_seconds"] = round(max(0.0, remaining), 1)
            else:
                payload["wait_seconds"] = 0.0
            return payload

    def reset(self) -> None:
        with self._lock:
            self.state = BreakerState(name=self.state.name)


_BREAKERS: Dict[str, CircuitBreaker] = {}
_BREAKER_LOCK = threading.Lock()


def get_breaker(name: str = "hcaptcha", **kwargs: Any) -> CircuitBreaker:
    """قاطع دائرة مشترك لكل هدف (hcaptcha، ocr، …)."""
    with _BREAKER_LOCK:
        breaker = _BREAKERS.get(name)
        if breaker is None:
            breaker = CircuitBreaker(name=name, **kwargs)
            _BREAKERS[name] = breaker
        return breaker


def breakers_snapshot() -> Dict[str, Any]:
    with _BREAKER_LOCK:
        return {name: breaker.snapshot() for name, breaker in _BREAKERS.items()}


# ---------------------------------------------------------------------------
# 3) التكرار الذكي (محاولات متنوعة لا مكرّرة)
# ---------------------------------------------------------------------------


@dataclass
class AttemptLog:
    """سجل محاولة واحدة — يُعاد للمستخدم ضمن الاستجابة للتشخيص."""

    round: int
    action: str
    ok: bool
    detail: str = ""
    elapsed_ms: int = 0
    extra: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = {
            "round": self.round,
            "action": self.action,
            "ok": self.ok,
            "detail": self.detail,
            "elapsed_ms": self.elapsed_ms,
        }
        payload.update(self.extra)
        return payload


def diversify(orders: Optional[List[List[str]]], attempt: int) -> Optional[List[str]]:
    """يختار ترتيبًا مختلفًا لكل محاولة حتى لا نكرّر نفس القراءة.

    يدوّر قائمة الترتيبات المتاحة بحيث تبدأ المحاولة ``attempt`` من موضع
    مختلف — تنويع بسيط لكنه فعّال ضد «نفس الخطأ كل مرة».
    """
    if not orders:
        return None
    return orders[attempt % len(orders)]


__all__ = [
    "AttemptLog",
    "CircuitBreaker",
    "TimeoutExceeded",
    "breakers_snapshot",
    "diversify",
    "get_breaker",
    "run_with_timeout",
]
