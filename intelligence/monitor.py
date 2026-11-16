"""طبقة الذكاء المراقب - مراقبة ذكية، اكتشاف شذوذ، تنبيهات، وتقارير أداء مع دعم ديسكورد والويب هوك."""

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone, timedelta
import statistics
import time
import asyncio

try:
    import httpx

    _HTTPX_AVAILABLE = True
except Exception:  # noqa: BLE001
    _HTTPX_AVAILABLE = False


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
    """مراقب ذكي يسجل الأحداث، يكشف الشذوذ، يُصدر تنبيهات ويرسلها عبر ديسكورد/ويب هوك."""

    def __init__(
        self,
        window_minutes: int = 60,
        discord_webhook_url: Optional[str] = None,
        alert_webhook_url: Optional[str] = None,
        alert_on_levels: Optional[List[str]] = None,
    ) -> None:
        self.window = timedelta(minutes=window_minutes)
        self.events: List[SolveEvent] = []
        self.alerts: List[Alert] = []
        self.discord_webhook_url = discord_webhook_url
        self.alert_webhook_url = alert_webhook_url
        self.alert_on_levels = alert_on_levels or ["warning", "critical"]
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
        # إرسال التنبيهات عبر الويب هوك (لا نعيق التنفيذ)
        for alert in new_alerts:
            if alert.level in self.alert_on_levels:
                try:
                    asyncio.create_task(self._send_alert_async(alert))
                except Exception:  # noqa: BLE001
                    self.send_alert_sync(alert)
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

    async def _send_alert_async(self, alert: Alert) -> None:
        """إرسال التنبيه عبر ديسكورد أو ويب هوك (غير متزامن، لا يعيق التنفيذ)."""
        if not _HTTPX_AVAILABLE:
            return
        payload = {
            "level": alert.level,
            "message": alert.message,
            "timestamp": alert.timestamp,
            "metric": alert.metric,
            "value": alert.value,
            "service": "nonecap-clone",
        }
        urls = []
        if self.discord_webhook_url:
            urls.append(("discord", self.discord_webhook_url))
        if self.alert_webhook_url:
            urls.append(("webhook", self.alert_webhook_url))

        for name, url in urls:
            try:
                async with httpx.AsyncClient(timeout=10.0) as client:
                    if name == "discord":
                        discord_payload = {
                            "content": f"🚨 **NoneCap Alert [{alert.level.upper()}]**\n{alert.message}\nالمetric: `{alert.metric}` = {alert.value}\nالوقت: {alert.timestamp}",
                        }
                        await client.post(url, json=discord_payload)
                    else:
                        await client.post(url, json=payload)
            except Exception:  # noqa: BLE001
                pass  # لا نريد أن يعيق إرسال التنبيه العمليات الرئيسية

    def send_alert_sync(self, alert: Alert) -> None:
        """إرسال تنبيه بشكل متزامن (للوظائف غير غير المتزامنة)."""
        if not _HTTPX_AVAILABLE:
            return
        import asyncio
        try:
            asyncio.run(self._send_alert_async(alert))
        except Exception:
            pass

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
                "discord_configured": bool(self.discord_webhook_url),
                "webhook_configured": bool(self.alert_webhook_url),
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
            "discord_configured": bool(self.discord_webhook_url),
            "webhook_configured": bool(self.alert_webhook_url),
        }

    def _recommendation(self, rate: float) -> str:
        if rate >= 0.9:
            return "الأداء ممتاز؛ يمكن الاعتماد على الحل المحلي."
        if rate >= 0.7:
            return "الأداء جيد؛ يُنصح بخدمة خارجية كحل احتياطي للحالات الصعبة."
        if rate >= 0.5:
            return "الأداء متوسط؛ راجع إعدادات المعالجة المسبقة وفكر في خدمة خارجية رئيسية."
        return "الأداء ضعيف؛ يُنصح بالاعتماد الكامل على خدمة خارجية وحل مشاكل المعالجة المسبقة."


__all__ = ["SolveEvent", "Alert", "IntelligentMonitor"]
