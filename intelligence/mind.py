"""«عقل» النظام: واجهة واحدة تجمع المعايرة، الكفاءة، التخطيط، والتأمّل.

كل طلب يمرّ بدورة: تخطيط → تنفيذ → تقييم → تعلّم → تأمّل.
العقل يحفظ ما تعلّمه في ``data/mind_state.json`` ويعيد تحميله عند الإقلاع،
ويعرض تقريرًا مفهومًا عن مهاراته ونقاط ضعفه وخطته القادمة.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .calibration import ConfidenceCalibrator
from .competence import CompetenceEstimator
from .decision_planner import Decision, DecisionPlanner
from .knowledge_corpus import brief_for, cards_for_type
from .reflector import SelfReflector

_DEFAULT_STATE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "mind_state.json"
)


@dataclass
class MindCycle:
    """سجل دورة تفكير واحدة."""

    captcha_type: str
    decision: Decision
    success: bool = False
    confidence: float = 0.0
    latency_ms: int = 0
    error: Optional[str] = None
    calibrated: float = 0.0
    lesson: Optional[str] = None
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "captcha_type": self.captcha_type,
            "decision": self.decision.to_dict(),
            "success": self.success,
            "confidence": round(self.confidence, 4),
            "calibrated": round(self.calibrated, 4),
            "latency_ms": self.latency_ms,
            "error": self.error,
            "lesson": self.lesson,
            "timestamp": self.timestamp,
        }


class Mind:
    """العقل الذاتي: يخطّط، يتعلّم من كل نتيجة، ويشرح حالته."""

    def __init__(
        self,
        state_path: Optional[str] = _DEFAULT_STATE_PATH,
        autosave_every: int = 10,
    ) -> None:
        self.state_path = state_path
        self.autosave_every = max(1, autosave_every)
        self.calibrator = ConfidenceCalibrator(path=self._side_path("calibration.json"))
        self.competence = CompetenceEstimator(path=self._side_path("competence.json"))
        self.reflector = SelfReflector()
        self.planner = DecisionPlanner(
            competence=self.competence, calibrator=self.calibrator
        )
        self.cycles: List[MindCycle] = []
        self.total_cycles = 0
        self._since_save = 0
        self._load()

    def _side_path(self, name: str) -> Optional[str]:
        if not self.state_path:
            return None
        base = os.path.dirname(os.path.abspath(self.state_path))
        return os.path.join(base, name)

    # ---------- دورة التفكير ----------

    def think(
        self,
        captcha_type: str,
        difficulty: float = 0.5,
        external_available: bool = False,
        prefer_speed: bool = False,
    ) -> Decision:
        """مرحلة التخطيط قبل أي محاولة حل."""
        return self.planner.plan(
            captcha_type=captcha_type,
            difficulty=difficulty,
            external_available=external_available,
            prefer_speed=prefer_speed,
        )

    def learn(
        self,
        captcha_type: str,
        success: bool,
        confidence: float,
        latency_ms: int,
        decision: Optional[Decision] = None,
        error: Optional[str] = None,
    ) -> MindCycle:
        """مرحلة التقييم والتعلّم بعد المحاولة."""
        self.competence.observe(captcha_type, success, latency_ms)
        self.calibrator.observe(confidence, success)

        lesson_text: Optional[str] = None
        if success:
            self.reflector.observe_success(captcha_type)
        else:
            lesson = self.reflector.observe_failure(captcha_type, error)
            lesson_text = f"{lesson.root_cause} → {lesson.advice}"

        cycle = MindCycle(
            captcha_type=captcha_type,
            decision=decision
            or self.planner.plan(captcha_type, external_available=False),
            success=success,
            confidence=confidence,
            latency_ms=latency_ms,
            error=error,
            calibrated=self.calibrator.calibrate(confidence),
            lesson=lesson_text,
        )
        self.cycles.append(cycle)
        if len(self.cycles) > 300:
            self.cycles = self.cycles[-150:]
        self.total_cycles += 1

        self._since_save += 1
        if self._since_save >= self.autosave_every:
            self.save()
        return cycle

    # ---------- الاستشارة ----------

    def should_accept(self, confidence: float, threshold: Optional[float] = None) -> Dict[str, Any]:
        """هل نaccept النتيجة أم نعيد المحاولة؟ (قرار بالقيمة المتوقعة)."""
        threshold = 0.7 if threshold is None else threshold
        calibrated = self.calibrator.calibrate(confidence)
        utility = self.calibrator.expected_utility(confidence)
        return {
            "confidence": round(confidence, 4),
            "calibrated": calibrated,
            "threshold": threshold,
            "accept": calibrated >= threshold,
            "utility": utility,
        }

    def explain(self, captcha_type: str) -> Dict[str, Any]:
        """شرح معمّق: قرار العقل الآن + ما يعرفه عن هذا النوع + مصائده."""
        decision = self.think(captcha_type)
        cards = cards_for_type(captcha_type)
        return {
            "captcha_type": captcha_type,
            "decision": decision.to_dict(),
            "known_insights": brief_for(captcha_type, limit=3),
            "pitfalls": [p for card in cards[:2] for p in card.pitfalls][:5],
            "difficulty_prior": cards[0].difficulty if cards else 0.5,
            "advice": self.reflector.advice_for(captcha_type),
            "current_success": round(self.competence.expected_success(captcha_type), 4),
        }

    def next_experiment(self) -> Optional[Dict[str, Any]]:
        """يقترح أهم تجربة قادمة لرفع الكفاءة (استكشاف موجّه ذاتيًا)."""
        weak = self.competence.weaknesses(limit=1)
        target = weak[0] if weak else None
        if target is None:
            unknown = [
                name
                for name, comp in self.competence.types.items()
                if comp.attempts == 0
            ]
            target = unknown[0] if unknown else None
        if target is None:
            return None
        advance = self.reflector.advice_for(target)
        return {
            "target_type": target,
            "current_success": round(self.competence.expected_success(target), 4),
            "hypothesis": "تحسين المعالجة المسبقة يرفع دقة هذا النوع",
            "advice": advance[0] if advance else "جرّب معاملات بديلة (psm/threshold) وقس النتيجة",
        }

    # ---------- التقرير ----------

    def self_report(self) -> Dict[str, Any]:
        recent = self.cycles[-20:]
        recent_rate = (
            sum(1 for c in recent if c.success) / len(recent) if recent else 0.0
        )
        last = self.cycles[-1].to_dict() if self.cycles else None
        return {
            "identity": "عقل Nonzra الذاتي",
            "cycles": self.total_cycles,
            "self_rating": self.competence.self_rating(),
            "recent_success_rate": round(recent_rate, 4),
            "skills": self.competence.snapshot(),
            "calibration": {
                "observations": self.calibrator.total_observations,
                "brier_score": self.calibrator.brier_score(),
                "learned": self.calibrator.total_observations
                >= self.calibrator.min_observations,
            },
            "reflection": self.reflector.snapshot(),
            "planning": self.planner.snapshot(),
            "next_experiment": self.next_experiment(),
            "last_cycle": last,
            "notes": self.notes(),
            "knowledge_cards": len(cards_for_type("image")) + len(cards_for_type("hcaptcha")),
            "mood": self._mood(),
        }

    def _mood(self) -> str:
        """وصف مختصر للحالة الذاتية (للوحة والـ API)."""
        rate = self.competence.self_rating()
        if self.total_cycles == 0:
            return "في طور التعلّم الأولي"
        if rate >= 0.8:
            return "واثق ومرتاح — معدلات النجاح عالية"
        if rate >= 0.6:
            return "متوازن — يتعلّم ويحسّن مساراته"
        return "متواضع — يراجع نقاط ضعفه ويجرّب مسارات جديدة"

    def notes(self) -> List[str]:
        """ملاحظات قصيرة بصيغة «تعلّمت أن...» تصلح للعرض في اللوحة."""
        out: List[str] = []
        for lesson in self.reflector.top_lessons(limit=3):
            out.append(
                f"تعلّمت أن {lesson['root_cause']} في «{lesson['captcha_type']}» "
                f"يُعالج بـ: {lesson['advice']} (تكرّرت {lesson['occurrences']} مرة)"
            )
        for item in self.competence.strengths(limit=2):
            rate = self.competence.expected_success(item)
            out.append(f"أنا قوي في «{item}» بنسبة نجاح ~{rate:.0%}")
        for item in self.competence.weaknesses(limit=2):
            rate = self.competence.expected_success(item)
            out.append(f"أحتاج تحسين «{item}» (نجاح ~{rate:.0%})")
        if not out:
            out.append("لم أجرّب بما يكفي بعد — أرسل أول كبتشا لأبدأ التعلّم")
        return out

    # ---------- الحفظ والتحميل ----------

    def save(self) -> None:
        self.calibrator.save()
        self.competence.save()
        if not self.state_path:
            return
        data = {
            "total_cycles": self.total_cycles,
            "cycles": [c.to_dict() for c in self.cycles[-50:]],
        }
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.state_path)), exist_ok=True)
            with open(self.state_path, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            self._since_save = 0
        except OSError:
            pass

    def _load(self) -> None:
        if not self.state_path or not os.path.exists(self.state_path):
            return
        try:
            with open(self.state_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            return
        self.total_cycles = int(data.get("total_cycles", 0))


__all__ = ["Mind", "MindCycle"]
