"""معايرة الثقة: تحويل ثقة المحرّك الخامّة إلى احتمال نجاح حقيقي مُقاس.

المحرّكات تُرجع أرقامًا مثل ``0.7`` لا تعني بالضرورة أن النجاح يحدث في 70%
من الحالات. هنا نتعلم العلاقة الحقيقية بين الثقة والنجاح من السجل الفعلي
(isotonic regression عبر PAVA) ونستخدمها لاحقًا في قرارات القبول والتكلفة.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class CalibrationBin:
    """حاوية (bin) لمدى من الثقة مع عدد المشاهدات والنجاحات."""

    lo: float
    hi: float
    observations: int = 0
    successes: int = 0

    @property
    def empirical_rate(self) -> Optional[float]:
        if self.observations == 0:
            return None
        return self.successes / self.observations

    def to_dict(self) -> Dict[str, Any]:
        return {
            "lo": round(self.lo, 3),
            "hi": round(self.hi, 3),
            "observations": self.observations,
            "successes": self.successes,
            "empirical_rate": None
            if self.empirical_rate is None
            else round(self.empirical_rate, 4),
        }


def _pava(points: List[Tuple[float, float]]) -> List[Tuple[float, float]]:
    """Pool Adjacent Violators: يفرض رتابة (غير تناقصية) على المنحنى.

    النتيجة منحنى معايرة رتيب منطقيًا: ثقة أعلى لا تعني احتمال نجاح أقل.
    """
    if not points:
        return []
    blocks: List[List[float]] = []  # [weight, weighted_sum, count]
    for weight, value in points:
        blocks.append([weight, weight * value, 1])
        while len(blocks) > 1 and blocks[-2][1] / max(blocks[-2][0], 1e-9) > (
            blocks[-1][1] / max(blocks[-1][0], 1e-9)
        ):
            w1, s1, c1 = blocks[-2]
            w2, s2, c2 = blocks[-1]
            blocks[-2] = [w1 + w2, s1 + s2, c1 + c2]
            blocks.pop()

    curve: List[Tuple[float, float]] = []
    for weight, weighted_sum, count in blocks:
        value = weighted_sum / max(weight, 1e-9)
        curve.append((float(count), float(value)))
    return curve


class ConfidenceCalibrator:
    """يتعلّم من النتائج الفعلية كيف تُترجم الثقة إلى احتمال نجاح.

    - قبل وجود بيانات كافية: يبقى قريبًا من الثقة الخام (مع انكماش نحو المعدل العام).
    - بعد تراكم المشاهدات: يتبع المنحنى التجريبي المُقاس.
    """

    def __init__(
        self,
        bins: int = 10,
        prior_successes: float = 1.0,
        prior_failures: float = 1.0,
        path: Optional[str] = None,
        min_observations: int = 30,
    ) -> None:
        self.bins_count = max(2, int(bins))
        self.prior_successes = prior_successes
        self.prior_failures = prior_failures
        self.min_observations = min_observations
        self.path = path
        self.bins: List[CalibrationBin] = [
            CalibrationBin(i / self.bins_count, (i + 1) / self.bins_count)
            for i in range(self.bins_count)
        ]
        self.total_observations = 0
        self.total_successes = 0
        self._brier_sum = 0.0
        self._brier_count = 0
        self._curve: Optional[List[Tuple[float, float]]] = None
        if path:
            self._load()

    # ---------- التعلّم ----------

    def _bin_index(self, confidence: float) -> int:
        c = min(max(confidence, 0.0), 0.999999)
        return min(self.bins_count - 1, int(c * self.bins_count))

    def observe(self, confidence: float, success: bool) -> None:
        """يسجّل مشاهدة واحدة (ثقة المحرّك + هل نجح فعلًا)."""
        predicted = self.calibrate(confidence)
        self._brier_sum += (predicted - (1.0 if success else 0.0)) ** 2
        self._brier_count += 1

        bin_ = self.bins[self._bin_index(confidence)]
        bin_.observations += 1
        bin_.successes += 1 if success else 0
        self.total_observations += 1
        self.total_successes += 1 if success else 0
        self._curve = None

    # ---------- المعايرة ----------

    @property
    def base_rate(self) -> float:
        return (self.total_successes + self.prior_successes) / (
            self.total_observations + self.prior_successes + self.prior_failures
        )

    def _fallback(self, confidence: float) -> float:
        """قبل كفاية البيانات: انكماش نحو المعدل الأساسي لتجنّب الثقة الزائفة."""
        weight = self.total_observations / max(1.0, float(self.min_observations))
        weight = min(1.0, weight)
        blended = confidence * weight + self.base_rate * (1.0 - weight)
        return min(0.99, max(0.01, blended))

    def _build_curve(self) -> List[Tuple[float, float]]:
        if self._curve is not None:
            return self._curve
        points: List[Tuple[float, float]] = []
        for bin_ in self.bins:
            rate = bin_.empirical_rate
            # تنعيم بايزي داخل الحاوية لتجنّب تطرف العينات الصغيرة
            smoothed = (bin_.successes + self.prior_successes) / (
                bin_.observations + self.prior_successes + self.prior_failures
            )
            points.append((float(max(bin_.observations, 1)), smoothed))
            del rate
        pooled = _pava(points)
        # كل كتلة تمثل حاويات متتالية؛ نوزّع قيمتها على مداها
        curve: List[Tuple[float, float]] = []
        index = 0
        for count, value in pooled:
            span = int(round(count))
            for _ in range(max(1, span)):
                if index >= self.bins_count:
                    break
                lo = self.bins[index].lo
                hi = self.bins[index].hi
                curve.append(((lo + hi) / 2.0, value))
                index += 1
        while len(curve) < self.bins_count:
            lo = self.bins[index].lo
            hi = self.bins[index].hi
            curve.append(((lo + hi) / 2.0, self.base_rate))
            index += 1
        self._curve = curve
        return curve

    def calibrate(self, confidence: float) -> float:
        """يُعيد احتمال النجاح المتوقع لثقة خامّة (0.0-1.0)."""
        confidence = min(max(float(confidence), 0.0), 1.0)
        if self.total_observations < self.min_observations:
            return self._fallback(confidence)

        curve = self._build_curve()
        # أقرب نقطتين + استيفاء خطي
        if len(curve) == 1:
            return curve[0][1]
        for i in range(len(curve) - 1):
            x0, y0 = curve[i]
            x1, y1 = curve[i + 1]
            if confidence <= x1 or i == len(curve) - 2:
                span = max(1e-9, x1 - x0)
                ratio = min(1.0, max(0.0, (confidence - x0) / span))
                value = y0 + (y1 - y0) * ratio
                # مزج خفيف مع الثقة الخام يمنع الجمود عند القيم القصوى
                fused = 0.85 * value + 0.15 * confidence
                return round(min(0.995, max(0.005, fused)), 4)
        return round(self._fallback(confidence), 4)

    # ---------- قرار القبول بالقيمة المتوقعة ----------

    def expected_utility(
        self,
        confidence: float,
        value: float = 1.0,
        retry_cost: float = 0.15,
        retry_success_gain: float = 0.2,
    ) -> Dict[str, float]:
        """مقارنة قبول النتيجة الآن مقابل محاولة أخرى.

        يُعيد طاقة متوقعة لكل خيار مع التوصية، ما يجعل "متى نتوقف؟" قرارًا
        مبنيًا على بيانات لا على عتبة ثابتة.
        """
        p = self.calibrate(confidence)
        accept = p * value
        retry_p = min(0.98, p + retry_success_gain * (1.0 - p))
        retry = retry_p * value - retry_cost
        return {
            "calibrated_success": round(p, 4),
            "accept_utility": round(accept, 4),
            "retry_utility": round(retry, 4),
            "advise_retry": 1.0 if retry > accept else 0.0,
        }

    # ---------- التقارير ----------

    def reliability_curve(self) -> List[Dict[str, Any]]:
        return [b.to_dict() for b in self.bins]

    def brier_score(self) -> Optional[float]:
        """مقياس دقة المعايرة (أقل = أفضل)."""
        if not self._brier_count:
            return None
        return round(self._brier_sum / self._brier_count, 4)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "observations": self.total_observations,
            "successes": self.total_successes,
            "base_rate": round(self.base_rate, 4),
            "brier_score": self.brier_score(),
            "is_learned": self.total_observations >= self.min_observations,
            "curve": [
                {"confidence": round(x, 3), "success_probability": round(y, 4)}
                for x, y in self._build_curve()
            ],
            "reliability": self.reliability_curve(),
        }

    # ---------- الحفظ ----------

    def save(self) -> None:
        if not self.path:
            return
        data = {
            "bins": [
                {
                    "lo": b.lo,
                    "hi": b.hi,
                    "observations": b.observations,
                    "successes": b.successes,
                }
                for b in self.bins
            ],
            "total_observations": self.total_observations,
            "total_successes": self.total_successes,
            "brier_sum": self._brier_sum,
            "brier_count": self._brier_count,
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
        bins = data.get("bins") or []
        if len(bins) == self.bins_count:
            for bin_, raw in zip(self.bins, bins):
                bin_.observations = int(raw.get("observations", 0))
                bin_.successes = int(raw.get("successes", 0))
        self.total_observations = int(data.get("total_observations", 0))
        self.total_successes = int(data.get("total_successes", 0))
        self._brier_sum = float(data.get("brier_sum", 0.0))
        self._brier_count = int(data.get("brier_count", 0))
        self._curve = None


__all__ = ["CalibrationBin", "ConfidenceCalibrator"]
