"""مخطّط القرار: يختار المسار الأفضل بالقيمة المتوقعة بدل قواعد ثابتة.

عند كل طلب يجمع المخطّط:
1. احتمال نجاح كل مسار من الكفاءة المقاسة (Beta posterior).
2. معايرة الثقة لتحويل تقديرات المحرّك إلى احتمالات حقيقية.
3. تكلفة الوقت المُطبّعة، حتى لا يربح مسار بطيء لأنه دقيق فقط.
ثم يختار المسار الأعلى قيمة متوقعة ويشرح قراره بجملة واحدة مفهومة.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .calibration import ConfidenceCalibrator
from .competence import CompetenceEstimator
from .knowledge_corpus import cards_for_type


@dataclass
class Route:
    """مسار حل واحد قابل للمقارنة بالطاقة المتوقعة."""

    name: str
    prior_success: float  # قبل البيانات
    latency_ms: float
    cost: float  # تكلفة نسبية (خدمة خارجية = أعلى)

    def score(self, success_probability: float, latency_budget_ms: float) -> float:
        """القيمة المتوقعة: نجاح ناقص تكلفة وقت وتكلفة تشغيل."""
        time_penalty = min(1.0, self.latency_ms / max(1.0, latency_budget_ms))
        return success_probability - 0.45 * time_penalty - 0.25 * self.cost


@dataclass
class Decision:
    """قرار المخطّط مع تفصيل المقارنة."""

    chosen: str
    expected_value: float
    alternatives: List[Dict[str, Any]] = field(default_factory=list)
    explanation: str = ""
    confidence_target: float = 0.7
    should_retry: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "chosen": self.chosen,
            "expected_value": round(self.expected_value, 4),
            "alternatives": self.alternatives,
            "explanation": self.explanation,
            "confidence_target": round(self.confidence_target, 3),
            "should_retry": self.should_retry,
        }


# المسارات المتاحة في النظام (تُطابق أسماء الاستراتيجيات المستخدمة فعليًا)
_DEFAULT_ROUTES: List[Route] = [
    Route(name="local_primary", prior_success=0.62, latency_ms=700.0, cost=0.0),
    Route(name="ensemble_with_fallback", prior_success=0.75, latency_ms=1600.0, cost=0.15),
    Route(name="external_primary", prior_success=0.82, latency_ms=6000.0, cost=0.85),
    Route(name="nvidia_api", prior_success=0.8, latency_ms=2500.0, cost=0.6),
]


class DecisionPlanner:
    """يختار المسار الأعلى قيمة متوقعة ويشرح السبب بلغة بشرية."""

    def __init__(
        self,
        competence: Optional[CompetenceEstimator] = None,
        calibrator: Optional[ConfidenceCalibrator] = None,
        routes: Optional[List[Route]] = None,
        latency_budget_ms: float = 4000.0,
    ) -> None:
        self.competence = competence or CompetenceEstimator()
        self.calibrator = calibrator or ConfidenceCalibrator()
        self.routes = routes or list(_DEFAULT_ROUTES)
        self.latency_budget_ms = latency_budget_ms
        self.history: List[Decision] = []

    def _route_probability(self, route: Route, captcha_type: str) -> float:
        """احتمال نجاح المسار لهذا النوع."""
        base = self.competence.expected_success(captcha_type)
        if self.competence.types.get(captcha_type) and self.competence.types[captcha_type].attempts:
            # يمزج كفاءة النوع مع أولوية المسار (60/40)
            prior = self.calibrator.calibrate(route.prior_success)
            return 0.6 * base + 0.4 * prior
        return self.calibrator.calibrate(route.prior_success)

    def plan(
        self,
        captcha_type: str,
        difficulty: float = 0.5,
        external_available: bool = False,
        prefer_speed: bool = False,
        confidence_hint: Optional[float] = None,
    ) -> Decision:
        """يبني قرارًا كاملًا: المسار، حدّ الثقة، وهل نكرّر عند الشك."""
        budget = self.latency_budget_ms * (0.5 if prefer_speed else 1.0)
        scored: List[Dict[str, Any]] = []

        for route in self.routes:
            if route.name in ("external_primary", "nvidia_api") and not external_available:
                continue
            probability = self._route_probability(route, captcha_type)
            # الصعوبة تُنقص احتمال المسارات المحلية أكثر من الخارجية
            if route.cost == 0.0:
                probability *= 1.0 - 0.35 * max(0.0, difficulty - 0.35)
            value = route.score(probability, budget)
            scored.append(
                {
                    "route": route.name,
                    "success_probability": round(min(0.99, max(0.01, probability)), 4),
                    "latency_ms": route.latency_ms,
                    "cost": route.cost,
                    "expected_value": round(value, 4),
                }
            )

        # عند غياب الخبرة، تُستخدم أولوية الصعوبة من الذخيرة المعرفية
        competence_obj = self.competence.types.get(captcha_type)
        if competence_obj is None or competence_obj.attempts == 0:
            cards = cards_for_type(captcha_type)
            if cards:
                prior_difficulty = cards[0].difficulty
                for item in scored:
                    if item["cost"] == 0.0:
                        item["success_probability"] = round(
                            item["success_probability"] * (1.0 - 0.3 * prior_difficulty), 4
                        )
                        latency_ratio = min(1.0, item["latency_ms"] / max(1.0, budget))
                        size = 0.45 * latency_ratio + 0.25 * item["cost"]
                        item["expected_value"] = round(item["success_probability"] - size, 4)
                scored.sort(key=lambda i: i["expected_value"], reverse=True)

        if not scored:  # درع احتياطي
            scored = [
                {
                    "route": "local_primary",
                    "success_probability": 0.5,
                    "latency_ms": 700.0,
                    "cost": 0.0,
                    "expected_value": 0.4,
                }
            ]

        scored.sort(key=lambda item: item["expected_value"], reverse=True)
        best = scored[0]

        # حدّ الثقة: أعلى عندما تكون البيانات أقل أو النوع أضعف
        competence = self.competence.types.get(captcha_type)
        attempts = competence.attempts if competence else 0
        weakness = 1.0 - self.competence.expected_success(captcha_type)
        data_uncertainty = 1.0 / (1.0 + (attempts / 10.0))
        threshold = 0.55 + 0.25 * weakness + 0.12 * data_uncertainty
        threshold = min(0.92, max(0.5, threshold))

        should_retry = False
        if confidence_hint is not None:
            utility = self.calibrator.expected_utility(confidence_hint)
            should_retry = bool(utility["advise_retry"])

        explanation = self._explain(best, scored, captcha_type, attempts)
        decision = Decision(
            chosen=best["route"],
            expected_value=best["expected_value"],
            alternatives=scored,
            explanation=explanation,
            confidence_target=threshold,
            should_retry=should_retry,
        )
        self.history.append(decision)
        if len(self.history) > 500:
            self.history = self.history[-200:]
        return decision

    @staticmethod
    def _explain(
        best: Dict[str, Any], scored: List[Dict[str, Any]], captcha_type: str, attempts: int
    ) -> str:
        runner_up = scored[1] if len(scored) > 1 else None
        margin = best["expected_value"] - runner_up["expected_value"] if runner_up else 0.0
        base = (
            f"اخترت {best['route']} لنوع {captcha_type} "
            f"(احتمال نجاح {best['success_probability']:.0%}"
            f" وزمن ~{int(best['latency_ms'])}ms)"
        )
        if attempts == 0:
            base += " — لا خبرة سابقة بهذا النوع بعد، فالقرار مبني على الأولويات العامة"
        elif margin < 0.05 and runner_up:
            base += f" — الفارق ضيّق عن {runner_up['route']} فسأستكشف المسار الآخر لاحقًا"
        else:
            base += f" — أفضل من {runner_up['route']} بفارق {margin:.2f}" if runner_up else ""
        return base

    def snapshot(self) -> Dict[str, Any]:
        recent = [d.to_dict() for d in self.history[-10:]]
        return {
            "routes": [
                {"name": r.name, "prior_success": r.prior_success, "latency_ms": r.latency_ms}
                for r in self.routes
            ],
            "latency_budget_ms": self.latency_budget_ms,
            "decisions": len(self.history),
            "recent": recent,
        }


__all__ = ["Route", "Decision", "DecisionPlanner"]
