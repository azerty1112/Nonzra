"""حلّال Drag puzzles (المناوبة بالسحب)."""

from typing import Any, Optional
import time
import numpy as np
import cv2

from .base import BaseSolver, CaptchaType, SolverResult


class DragSolver(BaseSolver):
    captcha_type = CaptchaType.DRAG

    def solve(
        self,
        image_path: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        template_path: Optional[str] = None,
        template_bytes: Optional[bytes] = None,
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
            tmpl = (
                load_image(template_path)
                if template_path
                else (load_image_bytes(template_bytes) if template_bytes else None)
            )

            if img is None or tmpl is None:
                return SolverResult(
                    success=False,
                    captcha_type=self.captcha_type,
                    error="يجب توفير صورة اللغز وصورة القالب (template)",
                    response_time_ms=int((time.time() - start) * 1000),
                )

            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            t_gray = cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)
            res = cv2.matchTemplate(gray, t_gray, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, max_loc = cv2.minMaxLoc(res)

            elapsed = int((time.time() - start) * 1000)
            if max_val < 0.6:
                return SolverResult(
                    success=False,
                    captcha_type=self.captcha_type,
                    error="لم يتم العثور على موقع القالب بدقة كافية",
                    confidence=float(max_val),
                    response_time_ms=elapsed,
                )
            return SolverResult(
                success=True,
                captcha_type=self.captcha_type,
                text=f"{max_loc[0]},{max_loc[1]}",
                confidence=float(max_val),
                response_time_ms=elapsed,
                metadata={
                    "x": int(max_loc[0]),
                    "y": int(max_loc[1]),
                    "w": int(tmpl.shape[1]),
                    "h": int(tmpl.shape[0]),
                    "match": float(max_val),
                },
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
