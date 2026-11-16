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
from .captcha_knowledge import (
    CAPTCHA_TYPES,
    get_strategy,
    get_preprocess,
    difficulty_score,
    seed_knowledge_base,
)
from .detector import AutoDetector, Detection
from .experience_engine import ExperienceEngine
from .knowledge_base import KnowledgeBase
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
    experience: Optional[Dict[str, Any]] = None

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
            "experience": self.experience,
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
        knowledge_base: Optional[KnowledgeBase] = None,
        experience: Optional[ExperienceEngine] = None,
        external_available: bool = False,
        nvidia_api_key: Optional[str] = None,
        nvidia_api_endpoint: Optional[str] = None,
    ) -> None:
        self.registry = registry
        self.monitor = monitor or IntelligentMonitor()
        self.analyzer = analyzer or CaptchaAnalyzer()
        self.strategy = strategy or IntelligentSolverStrategy()
        self.tuner = tuner or AdaptiveTuner()
        self.learner = learner or LearningEngine()
        self.detector = detector or AutoDetector()
        self.knowledge_base = knowledge_base or KnowledgeBase()
        seed_knowledge_base(self.knowledge_base)
        self.experience = experience or ExperienceEngine(knowledge_base=self.knowledge_base)
        self.external_available = external_available
        self._nvidia_api_key = nvidia_api_key or __import__("os").environ.get("NVIDIA_API_KEY", "")
        self._nvidia_api_endpoint = nvidia_api_endpoint or __import__("os").environ.get("NVIDIA_API_ENDPOINT", "")

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

        # 2.5) التحقق من الحل المعروف في قاعدة الخبرة (تسريع وتجنب إعادة الحل)
        features_for_exp = analysis.features if analysis else {}
        known = self.experience.find_known_solution(ctype.value, features_for_exp)
        if known and known.get("text"):
            result = SolverResult(
                success=True,
                captcha_type=ctype,
                text=known["text"],
                token=known.get("token"),
                confidence=known["confidence"],
                response_time_ms=1,
                metadata={"source": "knowledge_base", "pattern_id": known.get("pattern_id")},
            )
            trace.append(f"حل معروف من الخبرة: النص={known['text']} ثقة={known['confidence']:.2f}")
            # تسجيل الحل في المراقبة والتعلّم
            reward = self.learner.reward_from_result(True, known["confidence"], 1)
            self.learner.update("knowledge_direct", reward)
            event = SolveEvent(
                timestamp=self._now(),
                captcha_type=ctype.value,
                success=True,
                response_time_ms=1,
                confidence=known["confidence"],
                strategy="knowledge_direct",
                error=None,
            )
            self.monitor.record(event)
            total_ms = int((time.time() - start) * 1000)
            return AutoResult(
                result=result,
                detected_type=detection.captcha_type if detection else ctype.value,
                detection_confidence=detection.confidence if detection else 1.0,
                strategy_used="knowledge_direct",
                params_used={},
                escalations=0,
                trace=trace,
                alerts=[],
                total_time_ms=total_ms,
                experience=self.experience.status(),
            )

        # 3) قرار الاستراتيجية من محرك التعلم + الاستراتيجية التحليلية + المعرفة الشاملة
        learned_arm = self.learner.select()
        decision = self.strategy.decide(
            ctype, image=image, sitekey=sitekey, url=url, prefer_human_like=human_like
        )
        # صعوبة النوع من قاعدة المعرفة
        diff = difficulty_score(ctype.value)
        strategy_from_kb = get_strategy(ctype.value)
        # اختر أفضل استراتيجية: المعرفة الشاملة أولوية إذا كان النوع خارجيًا مطلوبًا
        if CAPTCHA_TYPES.get(ctype.value, None) and CAPTCHA_TYPES[ctype.value].external_required:
            strategy_used = strategy_from_kb
        else:
            strategy_used = learned_arm
        trace.append(
            f"صعوبة النوع={diff:.2f}, استراتيجية معرفية={strategy_from_kb}, "
            f"استراتيجية متعلمة={learned_arm} (تحليلي: {decision.strategy})"
        )

        # 4) الضبط التلقائي للمعاملات (من قاعدة المعرفة أولًا، ثم الضبط التكيفي)
        features = analysis.features if analysis else {}
        preprocess_kb = get_preprocess(ctype.value)
        suggestion = self.knowledge_base.suggest_params(ctype.value, features)
        if suggestion:
            tuned = suggestion["params"]
            strategy_used = suggestion["strategy"]
            trace.append(
                f"معاملات من قاعدة المعرفة: {tuned} (استراتيجية {strategy_used}, "
                f"ثقة معرفية {suggestion.get('confidence', 0):.2f})"
            )
        else:
            # دمج معاملات قاعدة المعرفة مع الضبط التكيفي
            tuned = dict(preprocess_kb)
            tuned_choice = self.tuner.choose(ctype.value)
            tuned.update(tuned_choice)
            trace.append(f"معاملات مضبوطة (قاعدة معرفة + تكيفي): {tuned}")

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

        # 6.5) إعادة المحاولة التلقائية لـ hCaptcha حتى النجاح (لا تتوقف حتى تنجح)
        if ctype == CaptchaType.HCAPTCHA and not result.success:
            hcaptcha_max_retries = 10
            hcaptcha_delay = 5.0
            trace.append(
                f"بدء إعادة محاولة hCaptcha تلقائيًا حتى النجاح (أقصى {hcaptcha_max_retries} محاولة، تأخير {hcaptcha_delay}s)"
            )
            for hc_attempt in range(1, hcaptcha_max_retries + 1):
                trace.append(f"محاولة hCaptcha #{hc_attempt}/{hcaptcha_max_retries}")
                if hc_attempt > 1:
                    time.sleep(hcaptcha_delay)
                hc_result = self._attempt(
                    ctype=ctype,
                    strategy="external_primary",
                    decision_use_local=False,
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
                if hc_result.success:
                    result = hc_result
                    trace.append(f"نجح حل hCaptcha في المحاولة #{hc_attempt}")
                    break
                result = hc_result
            else:
                trace.append(f"فشل حل hCaptcha بعد {hcaptcha_max_retries} محاولة")

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

        # 8) تسجيل الحل في محرك الخبرة الذاتي
        features_for_exp = features if features else {}
        self.experience.record_solution(
            captcha_type=ctype.value,
            success=result.success,
            confidence=result.confidence,
            features=features_for_exp,
            text=result.text or result.token,
            token=result.token,
        )

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
            experience=self.experience.status(),
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

        # NVIDIA API solving
        if strategy == "nvidia_api":
            if not self._nvidia_api_key or not self._nvidia_api_endpoint:
                trace.append("NVIDIA API: key or endpoint missing, falling back to internal solver")
                strategy = "prefer_local"
            else:
                try:
                    import requests
                    payload = {
                        "captcha_type": ctype.value,
                        "sitekey": sitekey or '',
                        "url": url or '',
                        "action": action or '',
                    }
                    headers = {
                        "Authorization": f"Bearer {self._nvidia_api_key}",
                        "Content-Type": "application/json",
                    }
                    response = requests.post(
                        self._nvidia_api_endpoint,
                        headers=headers,
                        json=payload,
                        timeout=30,
                    )
                    response.raise_for_status()
                    result_data = response.json()
                    success = result_data.get("success", False)
                    solution = result_data.get("solution", "")
                    confidence = result_data.get("confidence", 0.0)
                    response_time_ms = result_data.get("response_time_ms", 0)
                    trace.append(
                        f"NVIDIA API → نجاح={success}, ثقة={confidence:.2f}, وقت={response_time_ms}ms"
                    )
                    return SolverResult(
                        success=success,
                        captcha_type=ctype,
                        response_time_ms=response_time_ms,
                        confidence=confidence,
                        error=None if success else f"NVIDIA API error: {result_data}",
                    )
                except Exception as e:
                    trace.append(f"NVIDIA API error: {e}, falling back to internal solver")
                    strategy = "prefer_local"

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
