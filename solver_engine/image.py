"""حلّال صور الكبتشا النصية باستخدام OCR ومعالجة الصور مع حل احتياطي."""

from dataclasses import dataclass
from typing import Any, List, Optional
import numpy as np
import pytesseract
from PIL import Image

from .base import SolverResult, CaptchaType, BaseSolver
from .preprocess import (
    load_image,
    load_image_bytes,
    preprocess_pipeline,
    to_pil,
    enhance_for_ocr,
    segment_characters,
)


@dataclass
class ImageSolveConfig:
    psm: int = 7  # treat image as single text line
    oem: int = 3  # default OCR engine
    whitelist: Optional[str] = None
    preprocess: bool = True
    resize_width: int = 400
    resize_height: int = 0
    threshold: str = "otsu"
    denoise: bool = True
    segment: bool = False


# ---------------------- قوالب الأحرف الاحتياطية (بدون Tesseract) ----------------------

_FALLBACK_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def _build_fallback_templates() -> dict:
    """يBuild قوالب بسيطة للأحرف والأرقام باستخدام OpenCV."""
    import cv2
    import numpy as np

    templates: dict = {}
    for ch in _FALLBACK_CHARS:
        img = np.zeros((40, 20), dtype=np.uint8)
        cv2.putText(
            img, ch, (2, 32), cv2.FONT_HERSHEY_SIMPLEX, 0.9, 255, 2
        )
        templates[ch] = img
    return templates


_FALLBACK_TEMPLATES = _build_fallback_templates()


def _fallback_ocr(image: np.ndarray) -> tuple[str, float]:
    """يحاول قراءة النص باستخدام تطابق القالب البسيط (بدون Tesseract)."""
    import cv2
    import numpy as np

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = [cv2.boundingRect(c) for c in contours]
    boxes = [b for b in boxes if b[2] >= 5 and b[3] >= 10]
    boxes.sort(key=lambda b: b[0])

    if not boxes:
        return "", 0.0

    result_chars: list[str] = []
    confidences: list[float] = []

    for x, y, w, h in boxes:
        char_img = binary[y : y + h, x : x + w]
        char_img = cv2.resize(char_img, (20, 40), interpolation=cv2.INTER_AREA)

        best_ch = ""
        best_score = -1.0
        for ch, tmpl in _FALLBACK_TEMPLATES.items():
            tmpl_resized = cv2.resize(tmpl, (20, 40), interpolation=cv2.INTER_AREA)
            # تطابق بسيط باستخدام الارتباط المتقاطع
            res = cv2.matchTemplate(char_img, tmpl_resized, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)
            if max_val > best_score:
                best_score = float(max_val)
                best_ch = ch

        result_chars.append(best_ch)
        confidences.append(max(0.0, best_score))

    text = "".join(result_chars)
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    return text, avg_conf


class ImageCaptchaSolver(BaseSolver):
    captcha_type = CaptchaType.IMAGE

    def __init__(self, config: Optional[ImageSolveConfig] = None) -> None:
        self.config = config or ImageSolveConfig()

    def solve(
        self,
        image_path: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        config: Optional[ImageSolveConfig] = None,
    ) -> SolverResult:
        import time

        start = time.time()
        cfg = config or self.config
        try:
            if image_bytes is not None:
                image = load_image_bytes(image_bytes)
            elif image_path is not None:
                image = load_image(image_path)
            else:
                return SolverResult(
                    success=False,
                    captcha_type=self.captcha_type,
                    error="يجب提供 image_path أو image_bytes",
                )

            if cfg.preprocess:
                processed = preprocess_pipeline(
                    image,
                    grayscale=True,
                    denoise=cfg.denoise,
                    threshold=cfg.threshold,
                    resize_width=cfg.resize_width,
                    resize_height=cfg.resize_height,
                )
                pil_image = to_pil(processed)
                pil_image = enhance_for_ocr(pil_image)
            else:
                pil_image = to_pil(image)

            # --------- المحاولة الأولى: Tesseract إن توفّر ----------
            text = ""
            try:
                custom_config = f"--psm {cfg.psm} --oem {cfg.oem}"
                if cfg.whitelist:
                    custom_config += f" -c tessedit_char_whitelist={cfg.whitelist}"
                text = pytesseract.image_to_string(pil_image, config=custom_config).strip()
                text = "".join(ch for ch in text if ch.isalnum())
            except Exception:
                text = ""

            # --------- الحل الاحتياطي إذا فشل Tesseract ----------
            method = "tesseract"
            confidence = 0.7 if text else 0.0
            if (cfg.segment and not text) or (not text and cfg.segment is False):
                try:
                    fb_text, fb_conf = _fallback_ocr(image)
                    if fb_text:
                        text = fb_text
                        confidence = fb_conf
                        method = "fallback_template"
                except Exception:
                    pass

            elapsed = int((time.time() - start) * 1000)
            return SolverResult(
                success=bool(text),
                captcha_type=self.captcha_type,
                text=text or None,
                confidence=confidence,
                response_time_ms=elapsed,
                metadata={"chars": len(text), "method": method},
            )
        except Exception as exc:  # noqa: BLE001
            elapsed = int((time.time() - start) * 1000)
            return SolverResult(
                success=False,
                captcha_type=self.captcha_type,
                error=str(exc),
                response_time_ms=elapsed,
            )

    async def solve_async(self, *args: Any, **kwargs: Any) -> SolverResult:
        import asyncio

        return await asyncio.to_thread(self.solve, *args, **kwargs)
