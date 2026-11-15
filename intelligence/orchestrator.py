"""المنسّق الذاتي: خط أنابيب حل كامل يعمل بذكاء ودون تدخل بشري."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time

import numpy as np
import cv2

from solver_engine.base import CaptchaType, SolverResult
from solver_engine.registry import SolverRegistry
from solver_engine.image import ImageSolveConfig

from .analysis import CaptchaAnalyzer
from .detector import AutoDetector, Detection
from .learning import LearningEngine
from .monitor import IntelligentMonitor, SolveEvent
from .solver_strategy import IntelligentSolverStrategy
from .tuner import AdaptiveTuner


@dataclass
class AutoResult:
    """نتيجة الحل الذاتي الشاملة مع أثر القرارات."""
    result: SolverResult
    detected_type: str
    detection_confidence: float
    strategy_used: str
    params_used: Dict[str, Any]
    escalations: int
    trace: List[str] = field(default_factory=list)
    alerts: List[Dict[str, Any]] = field(default_factory=list)
    total_time_ms: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "result": self.result.to_dict(),
            "detected_type": self.detected_type,
            "detection_confidence": self.detection_confidence,
            "strategy_used": self.strategy_used,
            "params_used": self.params_used,
            "escalations": self.escalations,
            "trace": self.trace,
            "alerts": self.alerts,
            "total_time_ms": self.total_time_ms,
        }


class AutoOrchestrator:
    """ينفّذ الحل الذاتي الكامل: كشف، تحليل، ضبط، قرار، حل، تقييم، تصعيد، تعلّم، مراقبة."""

    def __init__(
        self,
        registry: SolverRegistry,
        monitor: Optional[IntelligentMonitor] = None,
        analyzer: Optional[CaptchaAnalyzer] = None,
        strategy: Optional[IntelligentSolverStrategy] = None,
        tuner: Optional[AdaptiveTuner] = None,
        learner: Optional[LearningEngine] = None,
        detector: Optional[AutoDetector] = None,
        external_available: bool = False,
    ) -> None:
        self.registry = registry
        self.monitor = monitor or IntelligentMonitor()
        self.analyzer = analyzer or CaptchaAnalyzer()
        self.strategy = strategy or IntelligentSolverStrategy()
        self.tuner = tuner or AdaptiveTuner()
        self.learner = learner or LearningEngine()
        self.detector = detector or AutoDetector()
        self.external_available = external_available

    def _decode(self, image_bytes: Optional[bytes]) -> Optional[Any]:
        if not image_bytes:
            return None
        nparr = np.frombuffer(image_bytes, np.uint8)
        return cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    def solve(
        self,
        captcha_type: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        sitekey: Optional[str] = None,
        url: Optional[str] = None,
        action: Optional[str] = None,
        cdata: Optional[str] = None,
        template_bytes: Optional[bytes] = None,
        max_escalations: int = 2,
        human_like: bool = False,
        **extra: Any,
    ) -> AutoResult:
        start = time.time()
        trace: List[str] = []
        escalated = 0

        image = self._decode(image_bytes)

        # 1) الكشف التلقائي للنوع
        detection: Optional[Detection] = None
        if (captcha_type is None or captcha_type in ("auto", "")) and image is not None:
            detection = self.detector.detect(image)
            ctype_str = detection.captcha_type
            trace.append(
                f"كشف تلقائي: النوع={ctype_str} بثقة {detection.confidence}"
            )
        else:
            ctype_str = captcha_type or "image"
            trace.append(f"نوع محدد يدويًا: {ctype_str}")

        # 2) التحليل
        analysis = None
        if image is not None:
            analysis = self.analyzer.analyze_image(image)
            trace.append(
                f"تحليل: صعوبة={analysis.difficulty_score}, نجاح متوقع={analysis.estimated_success_rate}"
            )
        elif ctype_str in ("hcaptcha", "hcaptcha_enterprise") and sitekey and url:
            analysis = self.analyzer.analyze_hcaptcha(sitekey, url)
            trace.append(f"تحليل hCaptcha: صعوبة={analysis.difficulty_score}")

        try:
            ctype = CaptchaType(ctype_str)
        except ValueError:
            ctype = CaptchaType.IMAGE
            trace.append(f"نوع غير معروف '{ctype_str}' → افتراض image")

        # 3) قرار الاستراتيجية من محرك التعلم + الاستراتيجية التحليلية
        learned_arm = self.learner.select()
        decision = self.strategy.decide(
            ctype, image=image, sitekey=sitekey, url=url, prefer_human_like=human_like
        )
        strategy_used = learned_arm
        trace.append(f"استراتيجية متعلمة: {learned_arm} (تحليلي: {decision.strategy})")

        # 4) الضبط التلقائي للمعاملات
        tuned = self.tuner.choose(ctype.value)
        trace.append(f"معاملات مضبوطة: {tuned}")

        # 5) تنفيذ الحل مع سلسلة تصعيد
        result = self._attempt(
            ctype=ctype,
            strategy=strategy_used,
            decision_use_local=decision.use_local,
            params=tuned,
            image_bytes=image_bytes,
            sitekey=sitekey,
            url=url,
            action=action,
            cdata=cdata,
            template_bytes=template_bytes,
            human_like=human_like,
            trace=trace,
            extra=extra,
        )

        # 6) التقييم والتصعيد التلقائي
        threshold = decision.confidence_threshold
        while (
            (not result.success or result.confidence < threshold)
            and escalated < max_escalations
        ):
            escalated += 1
            trace.append(
                f"تصعيد #{escalated}: النتيجة غير كافية "
                f"(نجاح={result.success}, ثقة={result.confidence:.2f} < {threshold:.2f})"
            )
            # جرّب معاملات بديلة
            alt = self.tuner.choose(ctype.value, explore=True)
            alt_result = self._attempt(
                ctype=ctype,
                strategy=(
                    "ensemble_with_fallback"
                    if escalated == 1
                    else ("external_primary" if self.external_available else "local_primary")
                ),
                decision_use_local=escalated == 0,
                params=alt,
                image_bytes=image_bytes,
                sitekey=sitekey,
                url=url,
                action=action,
                cdata=cdata,
                template_bytes=template_bytes,
                human_like=human_like,
                trace=trace,
                extra=extra,
            )
            tuned = alt
            if alt_result.success and alt_result.confidence >= result.confidence:
                result = alt_result

        # 7) التعلّم والتسجيل
        reward = self.learner.reward_from_result(
            result.success, result.confidence, result.response_time_ms
        )
        self.learner.update(strategy_used, reward)
        self.tuner.record(
            ctype.value, tuned, result.success, result.confidence, result.response_time_ms
        )
        event = SolveEvent(
            timestamp=self._now(),
            captcha_type=ctype.value,
            success=result.success,
            response_time_ms=result.response_time_ms,
            confidence=result.confidence,
            strategy=strategy_used,
            error=result.error,
        )
        new_alerts = self.monitor.record(event)

        total_ms = int((time.time() - start) * 1000)
        trace.append(
            f"اكتمل: نجاح={result.success}, ثقة={result.confidence:.2f}, تصعيدات={escalated}, "
            f"زمن كلي={total_ms}ms"
        )

        det_type = detection.captcha_type if detection else ctype.value
        det_conf = detection.confidence if detection else 1.0

        return AutoResult(
            result=result,
            detected_type=det_type,
            detection_confidence=det_conf,
            strategy_used=strategy_used,
            params_used=tuned,
            escalations=escalated,
            trace=trace,
            alerts=[a.__dict__ for a in new_alerts],
            total_time_ms=total_ms,
        )

    def _attempt(
        self,
        ctype: CaptchaType,
        strategy: str,
        decision_use_local: bool,
        params: Dict[str, Any],
        image_bytes: Optional[bytes],
        sitekey: Optional[str],
        url: Optional[str],
        action: Optional[str],
        cdata: Optional[str],
        template_bytes: Optional[bytes],
        human_like: bool,
        trace: List[str],
        extra: Dict[str, Any],
    ) -> SolverResult:
        call_kwargs: Dict[str, Any] = dict(extra)
        if image_bytes is not None:
            call_kwargs["image_bytes"] = image_bytes
        if template_bytes is not None:
            call_kwargs["template_bytes"] = template_bytes
        if sitekey:
            call_kwargs["sitekey"] = sitekey
        if url:
            call_kwargs["url"] = url
        if action:
            call_kwargs["action"] = action
        if cdata:
            call_kwargs["cdata"] = cdata
        call_kwargs["config"] = ImageSolveConfig(
            psm=params.get("psm", 7),
            threshold=params.get("threshold", "otsu"),
            denoise=params.get("denoise", True),
        )

        try:
            if strategy == "ensemble_with_fallback":
                solvers = self.registry.get_solvers(ctype)
                result = self.strategy.ensemble_solve(solvers, ctype, **call_kwargs)
                trace.append(f"تجميع {len(solvers)} محرك → نجاح={result.success}")
                return result
            result = self.registry.solve(
                ctype, prefer_local=decision_use_local, **call_kwargs
            )
            trace.append(
                f"محاولة ({'محلي' if decision_use_local else 'خارجي'}) → "
                f"نجاح={result.success}, ثقة={result.confidence:.2f}"
            )
            return result
        except Exception as exc:  # noqa: BLE001
            trace.append(f"خطأ في المحاولة: {exc}")
            return SolverResult(
                success=False, captcha_type=ctype, error=str(exc)
            )

    @staticmethod
    def _now() -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat()


__all__ = ["AutoResult", "AutoOrchestrator"]
