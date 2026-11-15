"""طبقة الذكاء المراقب - مراقبة ذكية، اكتشاف شذوذ، تنبيهات، وتقارير أداء."""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, timedelta
import statistics
import time


@dataclass
class SolveEvent:
    """حدث حل واحد للمراقبة."""
    timestamp: str
    captcha_type: str
    success: bool
    response_time_ms: int
    confidence: float
    strategy: str
    error: Optional[str] = None


@dataclass
class Alert:
    """تنبيه ذكي."""
    level: str  # info, warning, critical
    message: str
    timestamp: str
    metric: str
    value: float


class IntelligentMonitor:
    """مراقب ذكي يسجل الأحداث، يكشف الشذوذ، ويُصدر تنبيهات."""

    def __init__(self, window_minutes: int = 60) -> None:
        self.window = timedelta(minutes=window_minutes)
        self.events: List[SolveEvent] = []
        self.alerts: List[Alert] = []
        self._thresholds = {
            "success_rate_min": 0.6,
            "avg_latency_ms_max": 8000,
            "error_spike_factor": 3.0,
        }

    def record(self, event: SolveEvent) -> List[Alert]:
        self.events.append(event)
        self._prune()
        new_alerts = self._detect_anomalies(event)
        self.alerts.extend(new_alerts)
        return new_alerts

    def _prune(self) -> None:
        cutoff = datetime.now(timezone.utc) - self.window
        self.events = [
            e for e in self.events
            if datetime.fromisoformat(e.timestamp) > cutoff
        ]

    def _detect_anomalies(self, latest: SolveEvent) -> List[Alert]:
        alerts: List[Alert] = []
        now = datetime.now(timezone.utc).isoformat()
        recent = self.events[-50:] if len(self.events) >= 10 else self.events
        if not recent:
            return alerts

        success_rate = sum(1 for e in recent if e.success) / len(recent)
        avg_latency = statistics.mean(e.response_time_ms for e in recent)
        error_count = sum(1 for e in recent if not e.success)

        if success_rate < self._thresholds["success_rate_min"]:
            alerts.append(Alert(
                level="warning",
                message=f"معدل النجاح انخفض إلى {success_rate:.1%} (أقل من العتبة {self._thresholds['success_rate_min']:.0%})",
                timestamp=now,
                metric="success_rate",
                value=success_rate,
            ))

        if avg_latency > self._thresholds["avg_latency_ms_max"]:
            alerts.append(Alert(
                level="warning",
                message=f"متوسط زمن الاستجابة مرتفع: {avg_latency:.0f} مللي ثانية",
                timestamp=now,
                metric="avg_latency_ms",
                value=avg_latency,
            ))

        if error_count >= 5 and latest.error:
            alerts.append(Alert(
                level="critical",
                message=f"تكرار أخطاء الحل ({error_count} أخطاء مؤخرًا): {latest.error}",
                timestamp=now,
                metric="error_spike",
                value=float(error_count),
            ))

        return alerts

    def report(self) -> Dict[str, Any]:
        self._prune()
        if not self.events:
            return {
                "total": 0,
                "success_rate": 0.0,
                "avg_latency_ms": 0.0,
                "by_type": {},
                "alerts": [asdict(a) for a in self.alerts[-10:]],
                "recommendation": "لا توجد بيانات كافية",
            }

        total = len(self.events)
        success = sum(1 for e in self.events if e.success)
        by_type: Dict[str, Dict[str, Any]] = {}
        for e in self.events:
            b = by_type.setdefault(e.captcha_type, {"total": 0, "success": 0, "latencies": []})
            b["total"] += 1
            if e.success:
                b["success"] += 1
            b["latencies"].append(e.response_time_ms)

        for b in by_type.values():
            b["success_rate"] = round(b["success"] / b["total"], 3)
            b["avg_latency_ms"] = round(statistics.mean(b["latencies"]), 1)
            del b["latencies"]

        return {
            "total": total,
            "success": success,
            "success_rate": round(success / total, 3),
            "avg_latency_ms": round(statistics.mean(e.response_time_ms for e in self.events), 1),
            "by_type": by_type,
            "alerts": [asdict(a) for a in self.alerts[-10:]],
            "recommendation": self._recommendation(success / total),
        }

    def _recommendation(self, rate: float) -> str:
        if rate >= 0.9:
            return "الأداء ممتاز؛ يمكن الاعتماد على الحل المحلي."
        if rate >= 0.7:
            return "الأداء جيد؛ يُنصح بخدمة خارجية كحل احتياطي للحالات الصعبة."
        if rate >= 0.5:
            return "الأداء متوسط؛ راجع إعدادات المعالجة المسبقة وفكر في خدمة خارجية رئيسية."
        return "الأداء ضعيف؛ يُنصح بالاعتماد الكامل على خدمة خارجية وحل problems preprocessing."


__all__ = ["SolveEvent", "Alert", "IntelligentMonitor"]
