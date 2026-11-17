"""المُتأمّل: يحوّل كل إخفاق إلى درس قابل للتنفيذ.

بدل الاكتفاء بتسجيل الخطأ، يصنّف السبب الجذري، ويقترح إجراءً محددًا
(تغيير معامل، تبديل مسار، رفع حدّ الثقة، أو طلب بيانات جديدة)، ويقيس
ما إذا كانت النصيحة نفعت فعلًا بعد تطبيقها.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# خرائط الأعراض → السبب الجذري → الإجراء المقترح
_ROOT_CAUSES = [
    (
        ("ثقة", "confidence", "منخفضة", "low"),
        "ثقة غير كافية في القراءة",
        "ارفع حدّ القبول أو أضف محاولة ثانية بمعاملات مختلفة",
    ),
    (
        ("مهلة", "timeout", "timed out", "زمن"),
        "تجاوز المهلة الزمنية",
        "قلّل حجم المعالجة أو استخدم مسارًا أسرع",
    ),
    (
        ("لا يوجد حلّال", "no solver", "غير مسجل", "not registered"),
        "لا يوجد محرّك مسجّل لهذا النوع",
        "سجّل محرّكًا للنوع أو استخدم خدمة خارجية",
    ),
    (
        ("قالب", "template", "تباين", "contour"),
        "صورة غير كافية للمطابقة",
        "اطلب صورة أوضح أو استخدم كشف الحواف بمعاملات أوسع",
    ),
    (
        ("مفتاح", "key", "unauthorized", "401", "403"),
        "مشكلة في المصادقة أو المفتاح",
        "تحقّق من مفتاح API وصلاحياته",
    ),
    (
        ("شبكة", "network", "connection", "dns", "connect"),
        "تعذّر الوصول للخدمة الخارجية",
        "أعد المحاولة أو انتقل إلى المسار المحلي",
    ),
    (
        ("قسمة", "تعبير", "expression", "math"),
        "تعبير غير صالح بعد القراءة",
        "حسّن المعالجة المسبقة أو غيّر نمط القراءة (psm)",
    ),
]


@dataclass
class Lesson:
    """درس مستخلص من إخفاق."""

    root_cause: str
    advice: str
    signature: str
    occurrences: int = 1
    captcha_type: str = ""
    applied: int = 0
    worked: int = 0

    @property
    def effectiveness(self) -> Optional[float]:
        if self.applied == 0:
            return None
        return self.worked / self.applied

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root_cause": self.root_cause,
            "advice": self.advice,
            "signature": self.signature,
            "occurrences": self.occurrences,
            "captcha_type": self.captcha_type,
            "effectiveness": None
            if self.effectiveness is None
            else round(self.effectiveness, 3),
            "applied": self.applied,
        }


def classify_error(error: Optional[str]) -> tuple[str, str]:
    """يصنّف رسالة الخطأ إلى (سبب جذري, نصيحة)."""
    if not error:
        return "فشل غير معروف", "أعد المحاولة مع سياق إضافي أو راجع السجل"
    text = error.lower()
    for needles, cause, advice in _ROOT_CAUSES:
        if any(needle.lower() in text for needle in needles):
            return cause, advice
    return "فشل غير مصنّف", "سجّل الحالة كاملة لتحسين التصنيف مستقبلًا"


class SelfReflector:
    """يجمع الدروس ويقيس فعّاليتها، ويصدر خلاصة «ما تعلّمته»."""

    def __init__(self) -> None:
        self.lessons: Dict[str, Lesson] = {}
        self.failures = 0
        self.successes_after_advice = 0
        self._advice_pending: List[str] = []

    @staticmethod
    def _signature(captcha_type: str, root_cause: str) -> str:
        raw = f"{captcha_type}:{root_cause}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:12]

    def observe_failure(self, captcha_type: str, error: Optional[str]) -> Lesson:
        cause, advice = classify_error(error)
        signature = self._signature(captcha_type, cause)
        lesson = self.lessons.get(signature)
        if lesson is None:
            lesson = Lesson(
                root_cause=cause,
                advice=advice,
                signature=signature,
                captcha_type=captcha_type,
            )
            self.lessons[signature] = lesson
        else:
            lesson.occurrences += 1
        self.failures += 1
        self._advice_pending.append(signature)
        return lesson

    def observe_success(self, captcha_type: str) -> None:
        """نجاح بعد إخفاق = دليل على أن الإجراء الذي بُني على الدرس نفع."""
        if not self._advice_pending:
            return
        for signature in self._advice_pending:
            lesson = self.lessons.get(signature)
            if lesson is not None:
                lesson.applied += 1
                if lesson.captcha_type == captcha_type or not captcha_type:
                    lesson.worked += 1
                    self.successes_after_advice += 1
        self._advice_pending.clear()

    def advice_for(self, captcha_type: str) -> List[str]:
        """نصائح مرتّبة حسب تكرار المشكلة لنوع معيّن."""
        relevant = [
            lesson
            for lesson in self.lessons.values()
            if lesson.captcha_type == captcha_type
        ]
        relevant.sort(key=lambda lesson: lesson.occurrences, reverse=True)
        return [lesson.advice for lesson in relevant[:3]]

    def top_lessons(self, limit: int = 5) -> List[Dict[str, Any]]:
        ordered = sorted(
            self.lessons.values(), key=lambda lesson: lesson.occurrences, reverse=True
        )
        return [lesson.to_dict() for lesson in ordered[:limit]]

    def snapshot(self) -> Dict[str, Any]:
        effective = [
            lesson for lesson in self.lessons.values() if lesson.effectiveness is not None
        ]
        avg_effectiveness = (
            round(sum(lesson.effectiveness or 0 for lesson in effective) / len(effective), 3)
            if effective
            else None
        )
        return {
            "failures_seen": self.failures,
            "distinct_lessons": len(self.lessons),
            "successes_after_advice": self.successes_after_advice,
            "advice_effectiveness": avg_effectiveness,
            "top_lessons": self.top_lessons(),
        }


__all__ = ["Lesson", "SelfReflector", "classify_error"]
