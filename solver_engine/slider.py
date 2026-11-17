"""حلّال Slider captchas: تحديد موضع الفجوة تلقائيًا بالحواف أو بالقالب."""

import time
from typing import Any, Optional

import cv2
import numpy as np

from .base import BaseSolver, CaptchaType, SolverResult
from .preprocess import load_image, load_image_bytes

# أدنى درجة تطابق قالب مقبولة كحل احتياطي (أقل من ذلك = فشل صريح أفضل من إجابة خاطئة)
_TEMPLATE_MIN_FALLBACK = 0.30


def _match_template_best(
    image_gray: "np.ndarray", template_gray: "np.ndarray"
) -> "tuple[float, tuple[int, int], str]":
    """يطابق القالب بالشدّة وبالحواف ويُعيد أفضل نتيجة.

    المطابقة بالحواف (Canny) أكثر مقاومة لاختلاف الإضاءة بين قطعة اللغز
    والفجوة المظللة، وهي الحالة الشائعة في كبتشا السلايدر.
    """
    res = cv2.matchTemplate(image_gray, template_gray, cv2.TM_CCOEFF_NORMED)
    _, intensity_score, _, intensity_loc = cv2.minMaxLoc(res)

    edges_img = cv2.Canny(image_gray, 60, 180)
    edges_tmpl = cv2.Canny(template_gray, 60, 180)
    if edges_tmpl.any() and edges_img.any():
        res_edges = cv2.matchTemplate(edges_img, edges_tmpl, cv2.TM_CCOEFF_NORMED)
        _, edge_score, _, edge_loc = cv2.minMaxLoc(res_edges)
    else:
        edge_score, edge_loc = -1.0, intensity_loc

    if edge_score > intensity_score:
        return float(edge_score), (int(edge_loc[0]), int(edge_loc[1])), "edges"
    return float(intensity_score), (int(intensity_loc[0]), int(intensity_loc[1])), "intensity"


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
            # يُحفظ أفضل تطابق قالب للاستخدام الاحتياطي إذا فشل كشف الحواف
            template_fallback: Optional[dict] = None
            if tmpl is not None and tmpl.shape[0] <= img.shape[0] and tmpl.shape[1] <= img.shape[1]:
                img_gray = (
                    cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    if img.ndim == 3
                    else img
                )
                tmpl_gray = (
                    cv2.cvtColor(tmpl, cv2.COLOR_BGR2GRAY)
                    if tmpl.ndim == 3
                    else tmpl
                )
                # قالب شبه موحّد لا يحمل تفاصيل كافية للمطابقة الموثوقة (CCOEFF_NORMED)
                if float(tmpl_gray.std()) < 3.0:
                    return SolverResult(
                        success=False,
                        captcha_type=self.captcha_type,
                        error="القالب منخفض التفاصيل (تباين ضعيف)؛ تعذّر تحديد الفجوة بثقة",
                        confidence=0.0,
                        response_time_ms=int((time.time() - start) * 1000),
                        metadata={"template_std": float(tmpl_gray.std())},
                    )
                max_val, max_loc, match_mode = _match_template_best(img_gray, tmpl_gray)
                template_fallback = {
                    "x": int(max_loc[0] + tmpl.shape[1] / 2),
                    "y": int(max_loc[1] + tmpl.shape[0] / 2),
                    "w": int(tmpl.shape[1]),
                    "h": int(tmpl.shape[0]),
                    "match": float(max_val),
                    "match_mode": match_mode,
                }
                if max_val < _TEMPLATE_MIN_FALLBACK:
                    template_fallback = None
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
                            "match_mode": match_mode,
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
                if template_fallback is not None:
                    return SolverResult(
                        success=True,
                        captcha_type=self.captcha_type,
                        text=str(template_fallback["x"]),
                        confidence=max(0.3, template_fallback["match"]),
                        response_time_ms=int((time.time() - start) * 1000),
                        metadata={**template_fallback, "method": "template_low_confidence"},
                    )
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
                if template_fallback is not None:
                    return SolverResult(
                        success=True,
                        captcha_type=self.captcha_type,
                        text=str(template_fallback["x"]),
                        confidence=max(template_fallback["match"], confidence),
                        response_time_ms=int((time.time() - start) * 1000),
                        metadata={**template_fallback, "method": "template_low_confidence"},
                    )
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
