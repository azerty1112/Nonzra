"""تقدير الكفاءة الذاتية: كم أنا جيّد في كل نوع كبتشا، وبأي سرعة؟

يستخدم توزيع Beta (بايزي) لتقدير احتمال النجاح مع أخذ قلة البيانات في الحسبان،
وEWMA لاكتشاف التراجع أو التحسّن بدل الاعتماد على متوسط جامد.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class TypeCompetence:
    """كفاءة النظام في نوع واحد من الكبتشا."""

    captcha_type: str
    alpha: float = 1.0  # نجاحات مقدرة (مع الأولوية)
    beta: float = 1.0  # إخفاقات مقدرة (مع الأولوية)
    attempts: int = 0
    successes: int = 0
    latency_ewma_ms: float = 0.0
    rate_ewma: float = 0.0
    streak_failures: int = 0

    @property
    def posterior_mean(self) -> float:
        return self.alpha / (self.alpha + self.beta)

    @property
    def confidence_interval(self) -> float:
        """عرض تقريبي لفاصل الثقة 95% لبيتا."""
        n = self.alpha + self.beta
        variance = (self.alpha * self.beta) / (n * n * (n + 1))
        return round(2 * 1.96 * (variance**0.5), 4)

    @property
    def raw_rate(self) -> float:
        return self.successes / self.attempts if self.attempts else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "captcha_type": self.captcha_type,
            "attempts": self.attempts,
            "successes": self.successes,
            "raw_rate": round(self.raw_rate, 4),
            "posterior_mean": round(self.posterior_mean, 4),
            "interval": self.confidence_interval,
            "latency_ewma_ms": round(self.latency_ewma_ms, 1),
            "trend_ewma": round(self.rate_ewma, 4),
            "streak_failures": self.streak_failures,
            "verdict": self.verdict,
        }

    @property
    def verdict(self) -> str:
        mean = self.posterior_mean
        if self.attempts < 5:
            return "غير معروف بعد"
        if mean >= 0.8:
            return "قوي"
        if mean >= 0.55:
            return "متوسط"
        return "ضعيف"


class CompetenceEstimator:
    """يتتبّع كفاءة النظام لكل نوع ويقارنها ببعضها لاتخاذ قرار «من يفعل ماذا»."""

    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path
        self.types: Dict[str, TypeCompetence] = {}
        if path:
            self._load()

    def _get(self, captcha_type: str) -> TypeCompetence:
        if captcha_type not in self.types:
            self.types[captcha_type] = TypeCompetence(captcha_type=captcha_type)
        return self.types[captcha_type]

    def observe(self, captcha_type: str, success: bool, latency_ms: int = 0) -> None:
        comp = self._get(captcha_type)
        comp.attempts += 1
        if success:
            comp.successes += 1
            comp.alpha += 1.0
            comp.streak_failures = 0
        else:
            comp.beta += 1.0
            comp.streak_failures += 1
        # EWMA للحالة اللحظية (0.25 وزن للحدث الجديد)
        alpha_w = 0.25
        comp.rate_ewma = alpha_w * (1.0 if success else 0.0) + (1 - alpha_w) * comp.rate_ewma
        comp.latency_ewma_ms = (
            alpha_w * float(latency_ms) + (1 - alpha_w) * comp.latency_ewma_ms
        )

    def expected_success(self, captcha_type: str) -> float:
        return self._get(captcha_type).posterior_mean

    def expected_latency(self, captcha_type: str) -> float:
        comp = self._get(captcha_type)
        return comp.latency_ewma_ms or 800.0

    def is_failing(self, captcha_type: str, threshold: float = 0.45) -> bool:
        comp = self._get(captcha_type)
        return comp.attempts >= 3 and comp.posterior_mean < threshold

    def ranking(self) -> List[Dict[str, Any]]:
        return [
            comp.to_dict()
            for comp in sorted(
                self.types.values(), key=lambda c: c.posterior_mean, reverse=True
            )
            if comp.attempts > 0
        ]

    def strengths(self, limit: int = 3) -> List[str]:
        ranked = self.ranking()
        return [c["captcha_type"] for c in ranked[:limit] if c["posterior_mean"] >= 0.6]

    def weaknesses(self, limit: int = 3) -> List[str]:
        ranked = [c for c in self.ranking() if c["attempts"] >= 3]
        weak = [c for c in ranked if c["posterior_mean"] < 0.6]
        return [c["captcha_type"] for c in weak[-limit:]][::-1]

    def self_rating(self) -> float:
        """تقييم عام 0.0-1.0 لكفاءة النظام عبر الأنواع التي جرّبها."""
        ranked = [c for c in self.types.values() if c.attempts > 0]
        if not ranked:
            return 0.5
        weight_sum = 0.0
        score = 0.0
        for comp in ranked:
            # الأنواع الأكثر تجربة تحصل على وزن أعلى (بيانات أوثق)
            weight = 1.0 + (comp.attempts**0.5)
            score += comp.posterior_mean * weight
            weight_sum += weight
        return round(score / weight_sum, 4)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "types": {name: comp.to_dict() for name, comp in self.types.items()},
            "ranking": self.ranking(),
            "strengths": self.strengths(),
            "weaknesses": self.weaknesses(),
            "self_rating": self.self_rating(),
        }

    def save(self) -> None:
        if not self.path:
            return
        data = {
            name: {
                "alpha": comp.alpha,
                "beta": comp.beta,
                "attempts": comp.attempts,
                "successes": comp.successes,
                "latency_ewma_ms": comp.latency_ewma_ms,
                "rate_ewma": comp.rate_ewma,
                "streak_failures": comp.streak_failures,
            }
            for name, comp in self.types.items()
        }
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
        except OSError:
            pass

    def _load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        for name, raw in data.items():
            self.types[name] = TypeCompetence(
                captcha_type=name,
                alpha=float(raw.get("alpha", 1.0)),
                beta=float(raw.get("beta", 1.0)),
                attempts=int(raw.get("attempts", 0)),
                successes=int(raw.get("successes", 0)),
                latency_ewma_ms=float(raw.get("latency_ewma_ms", 0.0)),
                rate_ewma=float(raw.get("rate_ewma", 0.0)),
                streak_failures=int(raw.get("streak_failures", 0)),
            )


__all__ = ["TypeCompetence", "CompetenceEstimator"]
