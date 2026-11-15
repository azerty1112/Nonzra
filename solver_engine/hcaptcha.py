"""حلّال hCaptcha (محلي مع خيار خدمة خارجية)."""

from typing import Any, Dict, Optional
import base64
import time

from .base import BaseSolver, CaptchaType, SolverResult


class HCaptchaSolver(BaseSolver):
    captcha_type = CaptchaType.HCAPTCHA

    def __init__(self, api_key: Optional[str] = None, external_api: Optional[str] = None) -> None:
        self.api_key = api_key
        self.external_api = external_api

    def solve(
        self,
        sitekey: Optional[str] = None,
        url: Optional[str] = None,
        image_b64: Optional[str] = None,
        **kwargs: Any,
    ) -> SolverResult:
        start = time.time()
        try:
            if self.external_api and self.api_key and sitekey and url:
                return self._solve_external(sitekey, url, start)

            if image_b64:
                # حل محلي للصورة المستخلصة من التحدي
                from .image import ImageCaptchaSolver, ImageSolveConfig
                data = base64.b64decode(image_b64)
                local = ImageCaptchaSolver(ImageSolveConfig(psm=7))
                result = local.solve(image_bytes=data)
                result.captcha_type = CaptchaType.HCAPTCHA
                result.response_time_ms = int((time.time() - start) * 1000)
                return result

            return SolverResult(
                success=False,
                captcha_type=self.captcha_type,
                error="يتطلب hCaptcha sitekey+url لخدمة خارجية أو image_b64 للحل المحلي",
                response_time_ms=int((time.time() - start) * 1000),
            )
        except Exception as exc:  # noqa: BLE001
            return SolverResult(
                success=False,
                captcha_type=self.captcha_type,
                error=str(exc),
                response_time_ms=int((time.time() - start) * 1000),
            )

    def _solve_external(self, sitekey: str, url: str, start: float) -> SolverResult:
        #構造 للاتصال بخدمة خارجية (مثل nonecap أو أي solve-service)
        import httpx

        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    self.external_api or "https://api.nonecap.com/v1/solve",
                    json={"type": "hcaptcha", "sitekey": sitekey, "url": url},
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                resp.raise_for_status()
                data = resp.json()
                elapsed = int((time.time() - start) * 1000)
                return SolverResult(
                    success=bool(data.get("token")),
                    captcha_type=self.captcha_type,
                    token=data.get("token"),
                    confidence=float(data.get("confidence", 1.0)),
                    response_time_ms=elapsed,
                    metadata={"external": True, "resp_key": data.get("resp_key")},
                )
        except Exception as exc:  # noqa: BLE001
            elapsed = int((time.time() - start) * 1000)
            return SolverResult(
                success=False,
                captcha_type=self.captcha_type,
                error=f"الخدمة الخارجية فشلت: {exc}",
                response_time_ms=elapsed,
            )

    async def solve_async(self, *args: Any, **kwargs: Any) -> SolverResult:
        import asyncio

        return await asyncio.to_thread(self.solve, *args, **kwargs)
