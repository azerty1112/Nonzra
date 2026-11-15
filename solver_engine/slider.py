"""حلّال Slider captchas: تحديد موضع الفجوة تلقائيًا بالحواف أو بالقالب."""

from typing import Any, Optional
import time
import cv2
import numpy as np

from .base import BaseSolver, CaptchaType, SolverResult
from .preprocess import load_image, load_image_bytes


class SliderSolver(BaseSolver):
    captcha_type = CaptchaType.SLIDER

    def solve(
        self,
        image_path: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        template_path: Optional[str] = None,
        template_bytes: Optional[bytes] = None,
        min_confidence: float = 0.35,
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
                    error="يجب توفير صورة خلفية السلايدر",
                    response_time_ms=int((time.time() - start) * 1000),
                )

            h, w = img.shape[:2]

            # 1) مع قالب: تطابق مباشر يعطي أعلى دقة
            if tmpl is not None:
                res = cv2.matchTemplate(
                    cv2.cvtColor(img, cv2.COLOR_BGR2GRAY),
                    cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY),
                    cv2.TM_CCOEFF_NORMED,
                )
                _, max_val, _, max_loc = cv2.minMaxLoc(res)
                if max_val >= 0.55:
                    x = int(max_loc[0] + tmpl.shape[1] / 2)
                    y = int(max_loc[1] + tmpl.shape[0] / 2)
                    return SolverResult(
                        success=True,
                        captcha_type=self.captcha_type,
                        text=str(x),
                        confidence=float(max_val),
                        response_time_ms=int((time.time() - start) * 1000),
                        metadata={
                            "x": x,
                            "y": y,
                            "w": int(tmpl.shape[1]),
                            "h": int(tmpl.shape[0]),
                            "match": float(max_val),
                            "method": "template",
                        },
                    )

            # 2) بلا قالب: حواف عمودية قوية = حدود الفجوة
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            grad_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
            col_scores = np.abs(grad_x).sum(axis=0)
            kernel = np.ones(9) / 9.0
            col_smooth = np.convolve(col_scores, kernel, mode="same")
            margin = max(8, w // 12)
            col_smooth[:margin] = 0.0
            col_smooth[-margin:] = 0.0
            if float(col_smooth.max()) <= 0.0:
                return SolverResult(
                    success=False,
                    captcha_type=self.captcha_type,
                    error="لم يُعثر على حواف فجوة",
                    response_time_ms=int((time.time() - start) * 1000),
                )
            x_peak = int(np.argmax(col_smooth))
            base = float(col_smooth.mean()) + 1e-6
            confidence = min(1.0, float(col_smooth[x_peak]) / (base * 8.0))
            if confidence < min_confidence:
                return SolverResult(
                    success=False,
                    captcha_type=self.captcha_type,
                    error="ثقة كشف الفجوة منخفضة",
                    confidence=confidence,
                    response_time_ms=int((time.time() - start) * 1000),
                )

            # تقدير y: مركز كتلة التدرج الرأسي حول العمود المكتشف
            band = gray[:, max(0, x_peak - 4): x_peak + 5]
            grad_y = np.abs(cv2.Sobel(band, cv2.CV_32F, 0, 1, ksize=3)).sum(axis=1)
            if float(grad_y.sum()) > 0:
                ys = np.arange(h, dtype=np.float64)
                y = int((ys * (grad_y / grad_y.sum())).sum())
            else:
                y = h // 2

            return SolverResult(
                success=True,
                captcha_type=self.captcha_type,
                text=str(x_peak),
                confidence=confidence,
                response_time_ms=int((time.time() - start) * 1000),
                metadata={"x": x_peak, "y": y, "method": "gradient"},
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


__all__ = ["SliderSolver"]
