"""حلّال Rotate captchas: تقدير زاوية الدوران المطلوبة للمحاذاة."""

from typing import Any, Optional
import time
import cv2
import numpy as np

from .base import BaseSolver, CaptchaType, SolverResult
from .preprocess import load_image, load_image_bytes


def _rotate(image: np.ndarray, angle: float, border: int = 255) -> np.ndarray:
    h, w = image.shape[:2]
    center = (w / 2.0, h / 2.0)
    m = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(image, m, (w, h), borderValue=(border,))


def _projection_variance(gray: np.ndarray) -> float:
    """تباين المسقط الأفقي للنص (أعلى عندما يكون النص أفقيًا)."""
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    row_sums = th.sum(axis=1).astype(np.float64)
    if row_sums.size == 0:
        return 0.0
    return float(row_sums.var())


class RotateSolver(BaseSolver):
    captcha_type = CaptchaType.ROTATE

    def solve(
        self,
        image_path: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        template_path: Optional[str] = None,
        template_bytes: Optional[bytes] = None,
        coarse_step: int = 5,
        **kwargs: Any,
    ) -> SolverResult:
        start = time.time()
        try:
            img = (
                load_image(image_path)
                if image_path
                else (load_image_bytes(image_bytes) if image_bytes else None)
            )
            tmpl = (
                load_image(template_path)
                if template_path
                else (load_image_bytes(template_bytes) if template_bytes else None)
            )
            if img is None:
                return SolverResult(
                    success=False,
                    captcha_type=self.captcha_type,
                    error="يجب توفير صورة الكبتشا",
                    response_time_ms=int((time.time() - start) * 1000),
                )

            # 1) مع قالب أصلي: بحث دوّار بتطابق القالب مع مركز الصورة
            if tmpl is not None:
                th, tw = tmpl.shape[:2]
                ih, iw = img.shape[:2]
                x0 = max(0, (iw - tw) // 2)
                y0 = max(0, (ih - th) // 2)
                crop = img[y0: y0 + th, x0: x0 + tw]
                if crop.shape[:2] == tmpl.shape[:2]:
                    crop_gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                    tmpl_gray = cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)
                    best_angle = 0.0
                    best_score = -1.0
                    for a in range(-180, 180, max(1, int(coarse_step))):
                        rotated = _rotate(tmpl_gray, float(a))
                        score = float(cv2.matchTemplate(crop_gray, rotated, cv2.TM_CCOEFF_NORMED)[0][0])
                        if score > best_score:
                            best_score = score
                            best_angle = float(a)
                    correction = (-best_angle + 180.0) % 360.0 - 180.0
                    return SolverResult(
                        success=True,
                        captcha_type=self.captcha_type,
                        text=f"{correction:.1f}",
                        confidence=min(1.0, best_score),
                        response_time_ms=int((time.time() - start) * 1000),
                        metadata={
                            "angle": best_angle,
                            "correction": correction,
                            "match": best_score,
                            "method": "template_rotation",
                        },
                    )

            # 2) بلا قالب: تباين المسقط العمودي أقصى عندما يكون النص أفقيًا
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            base_var = _projection_variance(_rotate(gray, 0.0)) + 1e-6
            best_angle_no_tmpl: float = 0.0
            best_var = -1.0
            for a in range(-90, 91, max(1, int(coarse_step))):
                var = _projection_variance(_rotate(gray, float(a)))
                if var > best_var:
                    best_var = var
                    best_angle_no_tmpl = float(a)
            # تنقيح بدقة 1 درجة
            start = int(best_angle_no_tmpl - coarse_step)
            end = int(best_angle_no_tmpl + coarse_step) + 1
            for step in range(start, end):
                angle_val = float(step)
                var = _projection_variance(_rotate(gray, angle_val))
                if var > best_var:
                    best_var = var
                    best_angle_no_tmpl = angle_val
            confidence = min(1.0, best_var / base_var)
            return SolverResult(
                success=True,
                captcha_type=self.captcha_type,
                text=f"{best_angle_no_tmpl:.1f}",
                confidence=confidence,
                response_time_ms=int((time.time() - start) * 1000),
                metadata={"angle": best_angle_no_tmpl, "variance": best_var, "method": "projection"},
            )
        except Exception as exc:  # noqa: BLE001
            return SolverResult(
                success=False,
                captcha_type=self.captcha_type,
                error=str(exc),
                response_time_ms=int((time.time() - start) * 1000),
            )

    async def solve_async(self, *args: Any, **kwargs: Any) -> SolverResult:
        import asyncio

        return await asyncio.to_thread(self.solve, *args, **kwargs)


__all__ = ["RotateSolver"]
