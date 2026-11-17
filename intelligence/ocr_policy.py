"""سياسة قراءة تتعلّم: أي طريقة عرض تنجح على أي نوع صورة، وكيف تُعاير الثقة.

ثلاث طبقات، كلها تعمل بلا بيانات خارجية وتتعلّم من الاستخدام الفعلي:

1. **تصنيف نوع الصورة** من إحصاءات بسيطة (تباين، نسبة حبر، حجم، تباين قطبي)
   ⇒ «سياق». مثال: صورة داكنة مزدحمة تُقرأ بقصّ + تكبير، وصورة فاتحة بسيطة
   تكفيها قراءة واحدة.
2. **اختيار طريقة العرض** بسياسة epsilon-greedy على سجل النجاح لكل (سياق، طريقة).
   تبدأ بالطريقة الرخيصة، وتتعلّم متى تصعد إلى الأغلى.
3. **معايرة الثقة** عبر ``ConfidenceCalibrator`` الموجود: كل إجابة تُقبل أو تُرفض
   من الخدمة الحقيقية تصبح مشاهدة تعلّم، فتتحول الثقة الخام إلى احتمال نجاح.

كل السجلات تُحفظ على القرص (JSON) وتُحمَّل عند الإقلاع — تعلّم يتراكم بين
التشغيلات، ويبقى شفافًا: ``snapshot()`` يعرض كل ما تعلّمناه.
"""

from __future__ import annotations

import json
import os
import random
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .calibration import ConfidenceCalibrator

# طرق العرض المتاحة (يجب أن تبقى متوافقة مع ocr_plus.variants)
STRATEGIES: List[str] = [
    "padded",
    "padded_cropped",
    "padded_8",
    "upscaled",
    "clahe",
    "deskewed",
    "lines_removed",
]

# أزواج (طريقة, سياق) تُعطى انحيازًا أوليًا معقولًا قبل وجود بيانات
_PRIOR_BIAS: Dict[tuple, float] = {
    ("upscaled", "dense"): 0.35,
    ("padded_cropped", "dense"): 0.30,
    ("lines_removed", "noisy"): 0.25,
    ("clahe", "low_contrast"): 0.25,
    ("padded", "clean"): 0.30,
}


def _safe_div(a: float, b: float) -> float:
    return a / b if b else 0.0


@dataclass
class StrategyStats:
    """سجل طريقة عرض واحدة داخل سياق واحد."""

    attempts: int = 0
    exact: int = 0
    chars: int = 0
    char_total: int = 0
    last_used: float = 0.0

    @property
    def exact_rate(self) -> float:
        return _safe_div(self.exact, self.attempts)

    @property
    def char_rate(self) -> float:
        return _safe_div(self.chars, self.char_total)

    def score(self) -> float:
        """مكافأة مركبة تعطي وزنًا أكبر لدقة الحروف عند قلة العيّنات."""
        if not self.attempts:
            return 0.0
        exact = self.exact_rate
        chars = self.char_rate
        shrink = self.attempts / (self.attempts + 3.0)  # انكماش نحو الصفر عند قلة البيانات
        return (0.6 * exact + 0.4 * chars) * shrink

    def to_dict(self) -> Dict[str, Any]:
        return {
            "attempts": self.attempts,
            "exact": self.exact,
            "exact_rate": round(self.exact_rate, 4),
            "char_rate": round(self.char_rate, 4),
            "score": round(self.score(), 4),
        }


@dataclass
class Decision:
    """قرار السياسة: ما الطرق التي سنقرأ بها هذه الصورة، وبأي ترتيب."""

    context: str
    strategies: List[str] = field(default_factory=list)
    reason: str = "explore"
    expected_difficulty: float = 0.5

    def to_dict(self) -> Dict[str, Any]:
        return {
            "context": self.context,
            "strategies": list(self.strategies),
            "reason": self.reason,
            "expected_difficulty": round(self.expected_difficulty, 3),
        }


class OcrPolicy:
    """سياسة قراءة تتعلّم عبر التشغيلات وتحفظ نفسها على القرص."""

    def __init__(
        self,
        path: Optional[str] = None,
        epsilon: float = 0.12,
        seed: Optional[int] = None,
        min_attempts: int = 3,
    ) -> None:
        self.path = path
        self.epsilon = epsilon
        self.min_attempts = min_attempts
        self._rng = random.Random(seed)
        self._lock = threading.Lock()
        self.stats: Dict[str, Dict[str, StrategyStats]] = {}
        self.calibrator = ConfidenceCalibrator(path=None)
        self.decisions = 0
        self._dirty = False
        if path:
            self._load()

    # ---------------- تصنيف الصورة ⇒ سياق ----------------

    @staticmethod
    def context_of(image: Any) -> str:
        """سياق الصورة من إحصاءات بسيطة — سريع ولا يعتمد على أي نموذج."""
        import numpy as np

        from solver_engine.ocr_plus import ink_mask, is_dark_background, as_gray, glyph_boxes

        gray = as_gray(image)
        height, width = gray.shape[:2]
        contrast = float(np.std(gray))
        ink = ink_mask(gray)
        ink_ratio = float(ink.mean())
        glyphs = len(glyph_boxes(gray))
        dark = is_dark_background(gray)

        if contrast < 38:
            return "low_contrast"
        if ink_ratio > 0.16:
            return "dense"
        if glyphs >= 5 and width < 260:
            return "dense"
        if ink_ratio < 0.04:
            return "sparse"
        if dark:
            return "dark"
        if height < 44:
            return "small"
        return "clean"

    # ---------------- اختيار الطرق ----------------

    def _bucket(self, context: str) -> Dict[str, StrategyStats]:
        return self.stats.setdefault(context, {})

    def _ranked(self, context: str) -> List[tuple]:
        bucket = self._bucket(context)
        scored = []
        for strategy in STRATEGIES:
            stat = bucket.get(strategy, StrategyStats())
            prior = _PRIOR_BIAS.get((strategy, context), 0.0)
            # الطرق غير المجرّبة تُمنح أولوية استكشافية معقولة
            exploration = 0.5 / (1.0 + stat.attempts) if stat.attempts < self.min_attempts else 0.0
            scored.append((stat.score() + prior + exploration, strategy, stat.attempts))
        scored.sort(reverse=True)
        return scored

    def decide(self, image: Any, budget: Optional[int] = None) -> Decision:
        """يختار طرائق القراءة لهذه الصورة (مع استكشاف محدود)."""
        context = self.context_of(image)
        ranked = self._ranked(context)
        self.decisions += 1

        untried = [name for score, name, attempts in ranked if attempts == 0]
        explore = self._rng.random() < self.epsilon and len(untried) > 0
        if explore:
            choice = self._rng.choice(untried[:3])
            first, reason = choice, "explore"
        else:
            first, reason = ranked[0][1], "exploit"

        # نضيف طريقتين احتياطيتين مرتّبتين حسب السجل (تصويت أدق عند الشك)
        ordered = [first] + [
            name for _, name, _ in ranked if name != first
        ]
        limit = budget or (2 if context in ("clean", "small") else 3)
        chosen = ordered[: max(1, limit)]

        confidence = _safe_div(
            self._bucket(context).get(first, StrategyStats()).exact, 
            max(1, self._bucket(context).get(first, StrategyStats()).attempts),
        )
        difficulty = float(min(1.0, max(0.0, 1.0 - confidence - 0.15)))
        return Decision(
            context=context,
            strategies=chosen,
            reason=reason,
            expected_difficulty=difficulty,
        )

    # ---------------- التعلّم من النتائج ----------------

    def record(
        self,
        context: str,
        strategy: str,
        expected: Optional[str],
        got: Optional[str],
        accepted: Optional[bool] = None,
    ) -> None:
        """يسجّل نتيجة قراءة. ``accepted`` (من الخدمة الحقيقية) يسبق المقارنة النصية.

        الأفضلية دائمًا لما تقوله الخدمة الفعلية: قبول hCaptcha دليل قاطع،
        ورفضها دليل قاطع على الخطأ. عند غياب ذلك نستخدم مقارنة بالنص الصحيح
        إن توفّر (وضع القياس).
        """
        if not expected and accepted is None:
            return
        with self._lock:
            stat = self._bucket(context).setdefault(strategy, StrategyStats())
            stat.attempts += 1
            stat.last_used = time.time()
            if expected:
                stat.char_total += len(expected)
                stat.chars += sum(1 for a, b in zip(expected, got or "") if a == b)
            if accepted is True or (accepted is None and expected and got == expected):
                stat.exact += 1
            self._dirty = True

    def observe_confidence(self, confidence: float, success: bool) -> None:
        """يغذّي معايرة الثقة بنتيجة حقيقية (قبول/رفض الخدمة)."""
        with self._lock:
            self.calibrator.observe(confidence, success)
            self._dirty = True

    def calibrated(self, confidence: float) -> float:
        """يحوّل الثقة الخام إلى احتمال نجاح مُقاس."""
        return self.calibrator.calibrate(confidence)

    def should_retry(self, confidence: float, threshold: float = 0.55) -> bool:
        """هل نعيد المحاولة بطريقة عرض أخرى؟ قرار مبني على الاحتمال المُعاير."""
        return self.calibrated(confidence) < threshold

    # ---------------- الحفظ والتحميل ----------------

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "contexts": {
                    context: {
                        strategy: stat.to_dict() for strategy, stat in bucket.items()
                    }
                    for context, bucket in self.stats.items()
                },
                "decision_count": self.decisions,
                "calibration": {
                    **self.calibrator.snapshot(),
                    "bins": [
                        {
                            "lo": item.lo,
                            "hi": item.hi,
                            "observations": item.observations,
                            "successes": item.successes,
                        }
                        for item in self.calibrator.bins
                    ],
                },
                "epsilon": self.epsilon,
            }

    def save(self) -> bool:
        if not self.path or not self._dirty:
            return False
        with self._lock:
            payload = {
                "version": 1,
                "saved_at": time.time(),
                "stats": {
                    context: {
                        strategy: {
                            "attempts": stat.attempts,
                            "exact": stat.exact,
                            "chars": stat.chars,
                            "char_total": stat.char_total,
                            "last_used": stat.last_used,
                        }
                        for strategy, stat in bucket.items()
                    }
                    for context, bucket in self.stats.items()
                },
                "calibration": {
                    **self.calibrator.snapshot(),
                    "bins": [
                        {
                            "lo": item.lo,
                            "hi": item.hi,
                            "observations": item.observations,
                            "successes": item.successes,
                        }
                        for item in self.calibrator.bins
                    ],
                },
                "decisions": self.decisions,
            }
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
            self._dirty = False
        return True

    def _load(self) -> None:
        if not self.path or not os.path.exists(self.path):
            return
        try:
            with open(self.path, encoding="utf-8") as handle:
                payload = json.load(handle)
        except Exception:  # noqa: BLE001 - ملف تالف لا يجب أن يمنع الإقلاع
            return
        for context, bucket in (payload.get("stats") or {}).items():
            for strategy, raw in bucket.items():
                self.stats.setdefault(context, {})[strategy] = StrategyStats(
                    attempts=int(raw.get("attempts", 0)),
                    exact=int(raw.get("exact", 0)),
                    chars=int(raw.get("chars", 0)),
                    char_total=int(raw.get("char_total", 0)),
                    last_used=float(raw.get("last_used", 0.0)),
                )
        self.decisions = int(payload.get("decisions", 0))
        calibration = payload.get("calibration") or {}
        for bin_raw in calibration.get("bins", []):
            observations = int(bin_raw.get("observations", 0))
            successes = int(bin_raw.get("successes", 0))
            if not observations:
                continue
            # نُعيد بناء الحاويات مباشرة كما حُفظت (نفس بـ«bins» عند الطرفين)
            lo = float(bin_raw.get("lo", 0.0))
            hi = float(bin_raw.get("hi", min(1.0, lo + 0.1)))
            target = next(
                (
                    item
                    for item in self.calibrator.bins
                    if abs(item.lo - lo) < 1e-6 and abs(item.hi - hi) < 1e-6
                ),
                None,
            )
            if target is None:
                continue
            target.observations += observations
            target.successes += successes
            self.calibrator.total_observations += observations
            self.calibrator.total_successes += successes
        self.calibrator._curve = None  # يُعاد بناؤه عند أول استعلام


_DEFAULT_PATH = os.environ.get(
    "NONECAP_OCR_POLICY_PATH", os.path.join("data", "ocr_policy.json")
)
_POLICY: Optional[OcrPolicy] = None
_POLICY_LOCK = threading.Lock()


def get_policy() -> OcrPolicy:
    """السياسة المشتركة (تُنشأ مرة واحدة وتُحمّل تعلّمها السابق)."""
    global _POLICY
    if _POLICY is None:
        with _POLICY_LOCK:
            if _POLICY is None:
                _POLICY = OcrPolicy(path=_DEFAULT_PATH)
    return _POLICY


def reset_policy(path: Optional[str] = None) -> OcrPolicy:
    """يعيد السياسة لحالة جديدة (للاختبارات أو لإعادة التعلّم من الصفر)."""
    global _POLICY
    with _POLICY_LOCK:
        _POLICY = OcrPolicy(path=path)
    return _POLICY


__all__ = [
    "Decision",
    "OcrPolicy",
    "STRATEGIES",
    "StrategyStats",
    "get_policy",
    "reset_policy",
]
