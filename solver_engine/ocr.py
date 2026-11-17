"""محرّك قراءة نصّي موحّد: عصبي (RapidOCR) → Tesseract → قوالب احتياطية.

الترتيب مقصود: RapidOCR يعمل بلا تثبيت نظامي وبلا إنترنت (النماذج داخل
الحزمة) ودقته أعلى بكثير على كبتشا الصور من مطابقة القوالب. عند غيابه
يُستخدم Tesseract إن وُجد، ثم المطابقة البسيطة كخيار أخير.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

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

    @property
    def success(self) -> bool:
        return bool(self.text)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "confidence": round(self.confidence, 4),
            "engine": self.engine,
            "elapsed_ms": round(self.elapsed_ms, 1),
        }


def engines_status() -> Dict[str, Any]:
    """ما المحرّكات المتاحة فعلًا على هذا الجهاز؟"""
    return {
        "rapidocr": RAPIDOCR_AVAILABLE,
        "tesseract": TESSERACT_AVAILABLE,
        "template_fallback": True,
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


def read_text(
    image: np.ndarray,
    allowlist: Optional[str] = None,
    prefer: Optional[str] = None,
) -> OcrResult:
    """يقرأ النص من صورة بأفضل محرّك متاح.

    Args:
        image: صورة BGR أو رمادية.
        allowlist: الأحرف المسموحة (لتقييد المخرجات).
        prefer: ``rapidocr``/``tesseract``/``template`` لإجبار محرّك معيّن.
    """
    import time as _time

    started = _time.perf_counter()
    result = _read_text(image, allowlist=allowlist, prefer=prefer)
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


def read_text_bytes(data: bytes, allowlist: Optional[str] = None) -> OcrResult:
    """قراءة مباشرة من بايتات صورة."""
    import cv2

    if not data:
        return OcrResult("", 0.0, "none")
    image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        return OcrResult("", 0.0, "none")
    return read_text(image, allowlist=allowlist)


__all__ = [
    "OcrResult",
    "read_text",
    "read_text_bytes",
    "engines_status",
    "RAPIDOCR_AVAILABLE",
    "TESSERACT_AVAILABLE",
]
