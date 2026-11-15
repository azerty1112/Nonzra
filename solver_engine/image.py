"""حلّال صور الكبتشا النصية باستخدام OCR ومعالجة الصور."""

from dataclasses import dataclass
from typing import Any, List, Optional
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

            custom_config = f"--psm {cfg.psm} --oem {cfg.oem}"
            if cfg.whitelist:
                custom_config += f" -c tessedit_char_whitelist={cfg.whitelist}"

            text = pytesseract.image_to_string(pil_image, config=custom_config).strip()
            text = "".join(ch for ch in text if ch.isalnum())

            if cfg.segment and not text:
                boxes = segment_characters(
                    preprocess_pipeline(
                        image,
                        grayscale=True,
                        denoise=cfg.denoise,
                        threshold=cfg.threshold,
                    )
                )
                parts = []
                for x, y, w, h in boxes:
                    char_img = pil_image.crop((x, y, x + w, y + h))
                    char_text = pytesseract.image_to_string(
                        char_img, config=f"--psm 10 --oem {cfg.oem}"
                    ).strip()
                    parts.append(char_text)
                text = "".join(parts)

            elapsed = int((time.time() - start) * 1000)
            return SolverResult(
                success=bool(text),
                captcha_type=self.captcha_type,
                text=text or None,
                confidence=0.7 if text else 0.0,
                response_time_ms=elapsed,
                metadata={"chars": len(text), "method": "tesseract"},
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
