"""حلّال Point-on-image (النقر على نقطة محددة)."""

from typing import Any, Optional
import time
import numpy as np
import cv2

from .base import BaseSolver, CaptchaType, SolverResult


class PointSolver(BaseSolver):
    captcha_type = CaptchaType.POINT

    def solve(
        self,
        image_path: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        target_color: Optional[str] = None,
        min_area: int = 20,
        **kwargs: Any,
    ) -> SolverResult:
        start = time.time()
        try:
            from .preprocess import load_image, load_image_bytes

            if image_path:
                img = load_image(image_path)
            elif image_bytes is not None:
                img = load_image_bytes(image_bytes)
            else:
                img = None
            if img is None:
                return SolverResult(
                    success=False,
                    captcha_type=self.captcha_type,
                    error="يجب توفير صورة",
                    response_time_ms=int((time.time() - start) * 1000),
                )

            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            mask = None
            if target_color:
                # دعم ألوان بسيطة: red, green, blue, yellow
                color_map = {
                    "red": ([0, 100, 100], [10, 255, 255]),
                    "green": ([40, 100, 100], [80, 255, 255]),
                    "blue": ([100, 100, 100], [130, 255, 255]),
                    "yellow": ([20, 100, 100], [30, 255, 255]),
                }
                lo, hi = color_map.get(target_color.lower(), ([0, 0, 0], [180, 255, 255]))
                mask = cv2.inRange(hsv, np.array(lo), np.array(hi))
            else:
                mask = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                _, mask = cv2.threshold(mask, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

            contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            best = None
            best_area: float = 0.0
            for cnt in contours:
                area = cv2.contourArea(cnt)
                if area >= min_area and area > best_area:
                    best_area = area
                    best = cnt

            elapsed = int((time.time() - start) * 1000)
            if best is None:
                return SolverResult(
                    success=False,
                    captcha_type=self.captcha_type,
                    error="لم يتم العثور على هدف",
                    response_time_ms=elapsed,
                )

            x, y, w, h = cv2.boundingRect(best)
            cx = x + w // 2
            cy = y + h // 2
            return SolverResult(
                success=True,
                captcha_type=self.captcha_type,
                text=f"{cx},{cy}",
                confidence=0.8,
                response_time_ms=elapsed,
                metadata={"x": cx, "y": cy, "w": w, "h": h, "area": float(best_area)},
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
