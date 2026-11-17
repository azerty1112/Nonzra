"""قرار «أُرسل أم أمتنع؟» — الفرق بين التخمين والعلم.

النظام سابقًا كان يُرسل أفضل تخمين دائمًا. المشكلة أن إجابة باحتمال نجاح
30% تُحرق محاولة كاملة، بينما طلب تحدٍّ جديد يعطي احتمالًا أعلى. لهذا لا
يكفي أن نعرف الثقة — يجب أن نقرّر متى **لا** نُرسل.

المنطق هنا بسيط ومقاس، لا سحري:

1. نحوّل الثقة إلى **احتمال نجاح** عبر المُعاير المتعلَّم من hCaptcha نفسها
   (``OcrPolicy.calibrated``)، لا من الثقة الخام المتفائلة.
2. نقارن بين خيارين:
   - **أرسل**: احتمال النجاح ``p``، لكن المحاولة محسوبة.
   - **امتنع واطلب تحدٍّ جديدًا**: احتمال النجاح ``p_fresh`` (أعلى عادةً،
     لأن تحدّيًا جديدًا لم يُستنفد) بتكلفة محاولة أيضًا.
3. نرسل فقط إذا كان ``p >= τ`` حيث τ هو **عتبة مُعايَرة**: أقل احتمال يكون
   عنده الإرسال أفضل من إعادة الطلب. الافتراضي 0.45 مبني على ملاحظة أن
   قراءات hCaptcha تحت 0.4 كانت تفشل دائمًا تقريبًا في القياسات.

كل قرار يُعاد معه **السبب** و**الأرقام**، لأن القرار الذي لا يُفسَّر لا يمكن
معايرته لاحقًا.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

# عتبة الافتراض: أقل من ذلك نطلب تحدٍّ جديدًا بدل إحراق محاولة على تخمين.
DEFAULT_THRESHOLD = 0.45
# احتمال نجاح تقديري لتحدٍّ جديد لم تُقرأ صورته بعد (مبني على أوّل قراءة ناجحة).
DEFAULT_FRESH_PROBABILITY = 0.55


@dataclass
class AbstainDecision:
    """قرار واحد: أُرسل أم أمتنع، ولماذا."""

    send: bool
    reason: str
    probability: float
    threshold: float
    raw_confidence: float
    calibrated: bool = False
    retry_advice: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "send": self.send,
            "reason": self.reason,
            "probability": round(self.probability, 4),
            "threshold": self.threshold,
            "raw_confidence": round(self.raw_confidence, 4),
            "calibrated": self.calibrated,
        }
        if self.retry_advice:
            payload["retry_advice"] = self.retry_advice
        if self.extra:
            payload.update(self.extra)
        return payload


# عدد المشاهدات الحقيقية اللازمة قبل أن نثق بمنحنى المعايرة.
MIN_CALIBRATION_SAMPLES = 30


def _calibrate(confidence: float) -> tuple:
    """يعيد ``(prob, calibrated?)`` — يستخدم المُعاير المتعلَّم إن كان مدرَّبًا.

    تحذير مقيس: قبل توفّر بيانات كافية يُرجع ``ConfidenceCalibrator`` قيمة
    ثابتة (~0.5) لكل الثقات. الاعتماد عليها عندئذٍ يُلغي القرار بالكامل —
    لذلك نتحقّق من عدد المشاهدات ونرجع إلى الثقة الخام إن لم يكن مدرَّبًا.
    """
    try:
        from intelligence.ocr_policy import get_policy

        policy = get_policy()
        observations = policy.calibrator.total_observations
        if observations < MIN_CALIBRATION_SAMPLES:
            # لا نعتمد على منحنى غير مدرَّب: نستخدم الخام مع انكماش بسيط
            # نحو 0.5 لأن الثقة الخام معروفة بأنها متفائلة.
            shrunk = 0.5 + (float(confidence) - 0.5) * 0.85
            return float(min(max(shrunk, 0.0), 0.999)), False
        return float(policy.calibrated(confidence)), True
    except Exception:  # noqa: BLE001 - التعلّم تحسين لا شرط
        return float(confidence), False


def decide(
    confidence: float,
    threshold: float = DEFAULT_THRESHOLD,
    expected_len: Optional[int] = None,
    text: Optional[str] = None,
    rounds_left: int = 1,
    dry_run: bool = False,
    plausibility: Optional[float] = None,
) -> AbstainDecision:
    """يقرّر إرسال الإجابة أم الامتناع وطلب تحدٍّ جديد.

    Args:
        confidence: الثقة المصحّحة من محرّك القراءة (لا الخام).
        threshold: عتبة الإرسال؛ أعلى ⇒ أكثر تحفظًا.
        expected_len: طول متوقّع للنص (يُستخدم كإشارة جودة إضافية).
        text: النص المقروء.
        rounds_left: كم محاولة تبقّت؛ إن كانت صفرًا فلا فائدة من الامتناع.
        dry_run: للتشخيص فقط: لا نغيّر السلوك، نحسب القرار ونعيده.
        plausibility: توافق القراءة مع شكل الصورة (``OcrResult.plausibility``).

    **لماذا لا نعتمد على الثقة وحدها؟** قياس على 24 صورة واقعية أظهر أن
    الخطأ يحمل ثقة 0.90–1.00 (متوسط 0.90)، والصحيح 0.95 — أي أن العتبة على
    الثقة **لا تفصل** شيئًا: كل العتبات فوق 0.8 ترفض صحيحًا بقدر ما ترفض خطأً.
    أرسل النظام 24/24 بلا امتناع واحد، وفشل 8 منها.

    الإشارة التي **فصلت فعلًا**: ``plausibility`` — الصحيح 1.00 والخطأ 0.84،
    وكل أخطاء «الحرف الملتحم» جاءت بـ 0.69. لذلك نستخدمها كبوّابة أولى،
    والثقة المصحّحة كبوّابة ثانية.
    """
    probability, calibrated = _calibrate(confidence)
    notes: Dict[str, Any] = {}
    advice: Optional[str] = None

    # بوّابة الشكل: أدقّ إشارة مقيسة. تناقضٌ كبير بين النص المقروء وما تراه
    # الصورة يعني قراءة ناقصة/ملتبسة ⇒ لا نرسل، بل نعيد القراءة أو نطلب تحدّيًا.
    if plausibility is not None:
        notes["plausibility"] = round(float(plausibility), 3)
        if plausibility < 0.85:
            # خفض حادّ ومقصود: الفارق 0.69↔1.00 هو أهم إشارة لدينا، فلا يجوز
            # أن يذوب في متوسط. مقيس: 0.69 ⇒ ≈0.38، و0.5 ⇒ ≈0.25، 0.3 ⇒ ≈0.15.
            severity = min(1.0, (0.85 - float(plausibility)) / 0.35)
            probability *= max(0.2, 1.0 - 1.7 * severity)
            notes["shape_doubt"] = True
            notes["shape_severity"] = round(severity, 3)
    # حالات «مرفوضة قطعًا» لا يغيّرها نفاد المحاولات: قراءة بحرف واحد هي
    # فشل قراءة لا تخمين، وإرسالها يلوّث سمعة الجلسة عند الخدمة بلا فائدة.
    hard_refusal: Optional[str] = None

    # إشارات جودة مستقلة عن الثقة: نص قصير جدًا أو ناقص الطول
    if text is not None:
        notes["text_length"] = len(text)
        if len(text) <= 1:
            hard_refusal = (
                "النص المقروء حرف واحد أو أقل — قراءة فاشلة عمليًا (لا تُرسل أبدًا)"
            )
        if expected_len and len(text) != expected_len:
            # لا نمنع الإرسال لهذا السبب وحده، لكنه يخفض الاحتمال
            probability *= 0.75
            notes["length_mismatch"] = f"{len(text)} != {expected_len}"

    if hard_refusal and rounds_left > 0:
        return AbstainDecision(
            send=False,
            reason=hard_refusal,
            probability=min(probability, 0.1),
            threshold=threshold,
            raw_confidence=confidence,
            calibrated=calibrated,
            retry_advice="اطلب تحديًا جديدًا (challenge جديد) بهذه الصورة نفسها.",
            extra=notes,
        )

    if rounds_left <= 0:
        if hard_refusal:
            # لا أرسل قراءة فاشلة حتى في آخر جولة: النتيجة الصريحة أفضل
            return AbstainDecision(
                send=False,
                reason=hard_refusal,
                probability=min(probability, 0.1),
                threshold=threshold,
                raw_confidence=confidence,
                calibrated=calibrated,
                retry_advice="اطلب تحديًا جديدًا؛ لا تُرسل قراءة بحرف واحد.",
                extra=notes,
            )
        # لا تبقّى محاولات: أفضل ما يمكن فعله هو إرسال أفضل تخمين
        return AbstainDecision(
            send=True,
            reason="لا تبقّى محاولات — إرسال أفضل تخمين هو الخيار الوحيد",
            probability=probability,
            threshold=threshold,
            raw_confidence=confidence,
            calibrated=calibrated,
            extra=notes,
        )

    send = probability >= threshold
    if send:
        reason = "احتمال النجاح كافٍ للإرسال"
    else:
        reason = (
            f"احتمال النجاح {probability:.2f} أقل من العتبة {threshold:.2f} — "
            "إعادة الطلب أفضل من إحراق محاولة على تخمين"
        )
        advice = "امتنع عن الإرسال واطلب تحديًا جديدًا (أو اقرأ بعمق أكبر أولًا)."

    return AbstainDecision(
        send=bool(send or dry_run),
        reason=reason,
        probability=probability,
        threshold=threshold,
        raw_confidence=confidence,
        calibrated=calibrated,
        retry_advice=advice,
        extra=notes,
    )


def threshold_for_round(round_no: int, base: float = DEFAULT_THRESHOLD) -> float:
    """عتبة تتراجع مع تقدّم الجولات: في الأخيرة نرسل ما لدينا بأي حال."""
    if round_no <= 1:
        return base
    # كل جولة إضافية تخفّض العتبة 0.1 حتى لا نبقى ممتنعين بلا نهاية
    return max(0.2, base - 0.1 * (round_no - 1))


__all__ = [
    "AbstainDecision",
    "DEFAULT_FRESH_PROBABILITY",
    "DEFAULT_THRESHOLD",
    "MIN_CALIBRATION_SAMPLES",
    "decide",
    "threshold_for_round",
]
