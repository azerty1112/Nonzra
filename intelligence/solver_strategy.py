"""طبقة الذكاء الحل - استراتيجيات حل ذكية، تجميع محركات، اختيار تكيف."""

from dataclasses import dataclass, field
from typing import Any, List, Optional

from intelligence.analysis import CaptchaAnalysis, CaptchaAnalyzer
from intelligence.human_behavior import HumanBehavior
from solver_engine.base import BaseSolver, CaptchaType, SolverResult


@dataclass
class SolveDecision:
    """قرار الحل الذكي."""
    strategy: str
    captcha_type: CaptchaType
    confidence_threshold: float
    use_local: bool
    use_external: bool
    max_attempts: int
    human_profile: bool = False
    reasoning: List[str] = field(default_factory=list)


class IntelligentSolverStrategy:
    """يختار أنسب استراتيجية حل بناءً على تحليل الكبتشا والتاريخ."""

    def __init__(self) -> None:
        self.analyzer = CaptchaAnalyzer()
        self.human = HumanBehavior()
        self._recent_results: List[SolverResult] = []

    def decide(
        self,
        captcha_type: CaptchaType,
        image: Optional[Any] = None,
        sitekey: Optional[str] = None,
        url: Optional[str] = None,
        prefer_human_like: bool = False,
    ) -> SolveDecision:
        reasoning: List[str] = []
        analysis: Optional[CaptchaAnalysis] = None

        if image is not None:
            analysis = self.analyzer.analyze_image(image)
            reasoning.append(f"تحليل الصورة: صعوبة {analysis.difficulty_score}, نجاح متوقع {analysis.estimated_success_rate}")
        elif captcha_type == CaptchaType.HCAPTCHA and sitekey and url:
            analysis = self.analyzer.analyze_hcaptcha(sitekey, url)
            reasoning.append(f"تحليل hCaptcha: صعوبة {analysis.difficulty_score}")

        # استراتيجية افتراضية
        difficulty = analysis.difficulty_score if analysis else 0.5
        success_rate = analysis.estimated_success_rate if analysis else 0.7

        use_local = difficulty < 0.5
        use_external = difficulty > 0.4
        max_attempts = 3 if difficulty > 0.5 else 2
        threshold = 0.6 if difficulty < 0.4 else 0.75

        if use_local and use_external:
            strategy = "ensemble_with_fallback"
            reasoning.append("استراتيجية تجميع: محلي أولاً ثم خارجي كحل احتياطي")
        elif use_external:
            strategy = "external_primary"
            reasoning.append("صعوبة عالية → خدمة خارجية أساسية")
        else:
            strategy = "local_primary"
            reasoning.append("سهولة متوسطة → حل محلي أساسي")

        if prefer_human_like:
            reasoning.append("تفعيل السلوك البشري (تأخيرات، حركات ماوس طبيعية)")

        # مراعاة النتائج الأخيرة
        if self._recent_results:
            recent_fail = sum(1 for r in self._recent_results[-10:] if not r.success)
            if recent_fail >= 4:
                use_external = True
                strategy = "external_primary"
                reasoning.append("تعثر متكرر في المحاولات الأخيرة → 전환 للخدمة الخارجية")

        return SolveDecision(
            strategy=strategy,
            captcha_type=captcha_type,
            confidence_threshold=threshold,
            use_local=use_local,
            use_external=use_external,
            max_attempts=max_attempts,
            human_profile=prefer_human_like,
            reasoning=reasoning,
        )

    def record_result(self, result: SolverResult) -> None:
        self._recent_results.append(result)
        if len(self._recent_results) > 100:
            self._recent_results = self._recent_results[-100:]

    def ensemble_solve(
        self,
        solvers: List[BaseSolver],
        captcha_type: CaptchaType,
        *args: Any,
        **kwargs: Any,
    ) -> SolverResult:
        """يحاول محركات متعددة ويعيد أفضل نتيجة based on confidence."""
        results: List[SolverResult] = []
        for solver in solvers:
            if not solver.supports(captcha_type):
                continue
            try:
                result = solver.solve(*args, **kwargs)
                results.append(result)
                self.record_result(result)
                if result.success and result.confidence >= 0.85:
                    return result  # نتيجة موثوقة بما يكفي
            except Exception:  # noqa: BLE001
                continue

        if not results:
            return SolverResult(
                success=False,
                captcha_type=captcha_type,
                error="فشل جميع المحركات في التجميع",
            )

        # اختر الأفضل حسب الثقة ثم النجاح
        best = max(results, key=lambda r: (r.success, r.confidence))
        best.metadata["ensemble_attempts"] = len(results)
        return best


__all__ = ["SolveDecision", "IntelligentSolverStrategy"]
