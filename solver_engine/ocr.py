"""محرّك قراءة نصّي موحّد: عصبي (RapidOCR) → Tesseract → قوالب احتياطية.

الترتيب مقصود: RapidOCR يعمل بلا تثبيت نظامي وبلا إنترنت (النماذج داخل
الحزمة) ودقته أعلى بكثير على كبتشا الصور من مطابقة القوالب. عند غيابه
يُستخدم Tesseract إن وُجد، ثم المطابقة البسيطة كخيار أخير.

فوق ذلك طبقة ``ocr_plus``: تطبيع القطبية، حشو الصورة (يمنع إهمال حروف
الحافة)، تصويت بين عدّة طرق عرض، وتصحيح ثقة مبني على تحليل الصورة نفسه.
التصعيد تكيّفي: الحالة السهلة تُقرأ مرة واحدة، والصعبة تُقرأ بعدّة طرق.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

RAPIDOCR_AVAILABLE = False
TESSERACT_AVAILABLE = False

try:  # pragma: no cover - يعتمد على البيئة
    from rapidocr_onnxruntime import RapidOCR  # type: ignore

    RAPIDOCR_AVAILABLE = True
except Exception:  # noqa: BLE001
    RapidOCR = None  # type: ignore[assignment]

try:  # pragma: no cover
    import pytesseract

    pytesseract.get_tesseract_version()
    TESSERACT_AVAILABLE = True
except Exception:  # noqa: BLE001
    pytesseract = None  # type: ignore[assignment]

_READER_LOCK = threading.Lock()
_READER: Any = None


def _reader() -> Any:
    """يُهيّئ RapidOCR مرة واحدة (التهيئة ~0.4s)."""
    global _READER
    if _READER is None and RAPIDOCR_AVAILABLE:
        with _READER_LOCK:
            if _READER is None:
                _READER = RapidOCR()
    return _READER


@dataclass
class OcrResult:
    """نتيجة قراءة واحدة."""

    text: str
    confidence: float
    engine: str
    elapsed_ms: float = 0.0
    raw_engine_confidence: float = 0.0
    plausibility: float = 1.0
    variants_tried: int = 1
    notes: List[str] = field(default_factory=list)
    context: str = "unknown"
    strategy: str = "none"

    @property
    def success(self) -> bool:
        return bool(self.text)

    @property
    def confidence_gap(self) -> float:
        """كم خفّضنا ثقة المحرّك الخام بعد تدقيق تحليل الصورة."""
        return round(self.raw_engine_confidence - self.confidence, 4)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "confidence": round(self.confidence, 4),
            "raw_engine_confidence": round(self.raw_engine_confidence, 4),
            "plausibility": round(self.plausibility, 4),
            "variants_tried": self.variants_tried,
            "engine": self.engine,
            "notes": list(self.notes),
            "elapsed_ms": round(self.elapsed_ms, 1),
            "context": self.context,
            "strategy": self.strategy,
        }


def engines_status() -> Dict[str, Any]:
    """ما المحرّكات المتاحة فعلًا على هذا الجهاز؟"""
    return {
        "rapidocr": RAPIDOCR_AVAILABLE,
        "tesseract": TESSERACT_AVAILABLE,
        "template_fallback": True,
        "ensemble": True,
        "glyph_analysis": True,
        "preferred": "rapidocr"
        if RAPIDOCR_AVAILABLE
        else ("tesseract" if TESSERACT_AVAILABLE else "template"),
    }


def _clean_text(text: str, allowlist: Optional[str]) -> str:
    text = (text or "").strip()
    # التصحيحات الشائعة لأخطاء القراءة
    for src, dst in ((" ", ""), ("\n", ""), ("|", "1"), ("l", "1"), ("O", "0")):
        if src in text and (allowlist is None or dst in allowlist):
            text = text.replace(src, dst)
    if allowlist:
        text = "".join(ch for ch in text if ch in allowlist)
    return text


def _plan(image: np.ndarray, level: str) -> Any:
    """يطلب خطة القراءة من سياسة التعلّم (تفشل بهدوء إن لم تتوفر)."""
    try:
        from intelligence.ocr_policy import get_policy

        return get_policy().decide(image)
    except Exception:  # noqa: BLE001 - التعلّم تحسين لا شرط
        return None


def _learn_from_plan(plan: Any, outcome: Any, expected_len: Optional[int]) -> None:
    """يسجّل نتيجة القراءة لتعليم السياسة (بلا نص صحيح لا نعلّم «صحته»).

    نعلّم فقط ما نعرفه: طريقة العرض التي فازت + هل تجاوز النص الحدّ الأدنى
    من الاتساق البصري. القبول/الرفض الحقيقي يُغذّى من طبقة hCaptcha.
    """
    if plan is None or not outcome.votes:
        return
    try:
        from intelligence.ocr_policy import get_policy

        policy = get_policy()
        best = max(outcome.votes, key=lambda vote: vote.confidence)
        trusted = outcome.plausibility >= 0.99 and bool(outcome.text)
        for vote in outcome.votes:
            policy.record(
                plan.context,
                vote.source,
                expected=outcome.text if trusted else None,
                got=vote.text,
                accepted=True if (trusted and vote.text == outcome.text) else None,
            )
    except Exception:  # noqa: BLE001
        return


def read_text_single(image: np.ndarray, allowlist: Optional[str] = None) -> Optional[Tuple[str, float]]:
    """قراءة واحدة سريعة بصيغة ``(نص، ثقة)`` — تُستخدم داخل التجميع."""
    result = _read_text(image, allowlist=allowlist)
    if not result.text:
        return None
    return result.text, result.confidence


def read_text(
    image: np.ndarray,
    allowlist: Optional[str] = None,
    prefer: Optional[str] = None,
    ensemble: Optional[bool] = None,
    expected_len: Optional[int] = None,
    level: str = "balanced",
    order: Optional[Sequence[str]] = None,
) -> OcrResult:
    """يقرأ النص من صورة بأفضل محرّك متاح، مع تجميع تكيّفي عند الحاجة.

    Args:
        image: صورة BGR أو رمادية.
        allowlist: الأحرف المسموحة (لتقييد المخرجات). تُستخدم أيضًا كمجموعة
            تصحيح للمتشابهات البصرية (``O``→``0``…).
        prefer: ``rapidocr``/``tesseract``/``template`` لإجبار محرّك معيّن
            (يُعطّل التجميع لأنه يخصّ محرّكًا واحدًا).
        ensemble: ``True`` يفرض التجميع، ``False`` يمنعه، ``None`` يقرّر آليًا
            (تجميع فقط إذا كانت القراءة الواحدة ضعيفة أو مشكوكة الطول).
        expected_len: طول النص المتوقّع إن عُرف (يرفع دقة التجميع).
        level: عمق التجميع ``fast``/``balanced``/``max``.
        order: ترتيب طرق عرض مفروض (يستخدمه التكرار الذكي: كل محاولة تبدأ
            من طريقة مختلفة حتى لا نكرّر نفس القراءة).
    """
    import time as _time
    from . import ocr_plus

    started = _time.perf_counter()
    charset = allowlist or ocr_plus.DEFAULT_CHARSET
    use_ensemble = ensemble if ensemble is not None else prefer is None

    if not use_ensemble:
        result = _read_text(image, allowlist=allowlist, prefer=prefer)
        result.elapsed_ms = (_time.perf_counter() - started) * 1000.0
        return result

    reader = lambda variant: read_text_single(variant, allowlist=allowlist)  # noqa: E731
    plan = _plan(image, level)
    preferred = order if order else (plan.strategies if plan else None)
    outcome = ocr_plus.ensemble_read(
        image,
        reader,
        charset=charset,
        expected_len=expected_len,
        level=level,
        order=preferred,
    )
    _learn_from_plan(plan, outcome, expected_len)
    if not outcome.text:
        # لا قراءة من أي طريقة عرض ⇒ آخر محاولة بالمحرّك المفضّل على الصورة كما هي
        result = _read_text(image, allowlist=allowlist, prefer=prefer)
        result.elapsed_ms = (_time.perf_counter() - started) * 1000.0
        return result

    result = OcrResult(
        text=outcome.text,
        confidence=outcome.confidence,
        engine=f"ensemble:{outcome.strategy.split(':')[-1]}"
        if outcome.variants_tried > 1
        else (outcome.votes[0].source if outcome.votes else "ensemble"),
    )
    result.raw_engine_confidence = outcome.raw_engine_confidence
    result.plausibility = outcome.plausibility
    result.variants_tried = outcome.variants_tried
    result.notes = list(outcome.notes)
    result.context = plan.context if plan else "unknown"
    best_vote = max(outcome.votes, key=lambda vote: vote.confidence) if outcome.votes else None
    result.strategy = best_vote.source if best_vote else "none"
    result.elapsed_ms = (_time.perf_counter() - started) * 1000.0
    return result


def _read_text(
    image: np.ndarray,
    allowlist: Optional[str] = None,
    prefer: Optional[str] = None,
) -> OcrResult:
    """التنفيذ الفعلي لـ :func:`read_text` بلا قياس زمني."""
    if image is None or getattr(image, "size", 0) == 0:
        return OcrResult("", 0.0, "none")

    order: List[str] = ["rapidocr", "tesseract", "template"]
    if prefer in order:
        order = [prefer] + [e for e in order if e != prefer]

    for engine in order:
        if engine == "rapidocr" and RAPIDOCR_AVAILABLE:
            try:
                reader = _reader()
                output, _elapse = reader(image)
                if not output:
                    continue
                # أفضل صندوق بالثقة، ثم دمج صناديق السطر نفسه
                boxes = sorted(output, key=lambda item: float(item[2]), reverse=True)
                best_text = str(boxes[0][1])
                confidence = float(boxes[0][2])
                if len(boxes) > 1:
                    # جمع كل النصوص مرتّبة أفقياً (كبتشا قد تُقرأ على أجزاء)
                    ordered = sorted(
                        output, key=lambda item: min(p[0] for p in item[0])
                    )
                    joined = "".join(str(item[1]) for item in ordered)
                    if len(joined) >= len(best_text):
                        best_text = joined
                        confidence = float(
                            sum(float(item[2]) for item in ordered) / len(ordered)
                        )
                text = _clean_text(best_text, allowlist)
                if text:
                    return OcrResult(text, min(1.0, confidence), "rapidocr")
            except Exception:  # noqa: BLE001
                continue

        if engine == "tesseract" and TESSERACT_AVAILABLE:
            try:
                from PIL import Image as _Image

                if len(image.shape) == 3:
                    pil = _Image.fromarray(image[:, :, ::-1])
                else:
                    pil = _Image.fromarray(image)
                config = "--psm 7"
                if allowlist:
                    config += f" -c tessedit_char_whitelist={allowlist}"
                raw = pytesseract.image_to_string(pil, config=config)
                text = _clean_text(raw, allowlist)
                if text:
                    return OcrResult(text, 0.7, "tesseract")
            except Exception:  # noqa: BLE001
                continue

        if engine == "template":
            try:
                from .image import _fallback_ocr

                text, confidence = _fallback_ocr(image)
                text = _clean_text(text, allowlist)
                if text:
                    return OcrResult(text, float(confidence), "template")
            except Exception:  # noqa: BLE001
                continue

    return OcrResult("", 0.0, "none")


def read_text_bytes(
    data: bytes,
    allowlist: Optional[str] = None,
    expected_len: Optional[int] = None,
    ensemble: Optional[bool] = None,
    level: str = "balanced",
    order: Optional[Sequence[str]] = None,
) -> OcrResult:
    """قراءة مباشرة من بايتات صورة."""
    import cv2

    if not data:
        return OcrResult("", 0.0, "none")
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return OcrResult("", 0.0, "none")
    return read_text(
        image,
        allowlist=allowlist,
        expected_len=expected_len,
        ensemble=ensemble,
        level=level,
        order=order,
    )


__all__ = [
    "OcrResult",
    "read_text",
    "read_text_single",
    "read_text_bytes",
    "engines_status",
    "RAPIDOCR_AVAILABLE",
    "TESSERACT_AVAILABLE",
]
