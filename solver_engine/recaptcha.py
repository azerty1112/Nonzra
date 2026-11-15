"""حلّال reCAPTCHA v2 و v3."""

from typing import Any, Dict, Optional
import base64
import time

from .base import BaseSolver, CaptchaType, SolverResult


class ReCaptchaSolver(BaseSolver):
    captcha_type = CaptchaType.RECAPTCHA_V2

    def __init__(self, api_key: Optional[str] = None, external_api: Optional[str] = None) -> None:
        self.api_key = api_key
        self.external_api = external_api

    def _supports(self, captcha_type: CaptchaType) -> bool:
        return captcha_type in (
            CaptchaType.RECAPTCHA_V2,
            CaptchaType.RECAPTCHA_V2_INVISIBLE,
            CaptchaType.RECAPTCHA_V3,
        )

    def solve(
        self,
        sitekey: Optional[str] = None,
        url: Optional[str] = None,
        action: Optional[str] = None,
        image_b64: Optional[str] = None,
        captcha_type: CaptchaType = CaptchaType.RECAPTCHA_V2,
        **kwargs: Any,
    ) -> SolverResult:
        start = time.time()
        try:
            if not self._supports(captcha_type):
                return SolverResult(
                    success=False,
                    captcha_type=captcha_type,
                    error=f"النوع {captcha_type.value} غير مدعوم من هذا المحرّك",
                    response_time_ms=int((time.time() - start) * 1000),
                )

            if self.external_api and self.api_key and sitekey and url:
                return self._solve_external(sitekey, url, action, captcha_type, start)

            if image_b64:
                from .image import ImageCaptchaSolver, ImageSolveConfig
                data = base64.b64decode(image_b64)
                local = ImageCaptchaSolver(ImageSolveConfig(psm=7))
                result = local.solve(image_bytes=data)
                result.captcha_type = captcha_type
                result.response_time_ms = int((time.time() - start) * 1000)
                return result

            return SolverResult(
                success=False,
                captcha_type=captcha_type,
                error="يتطلب reCAPTCHA sitekey+url للخدمة الخارجية أو image_b64 للحل المحلي",
                response_time_ms=int((time.time() - start) * 1000),
            )
        except Exception as exc:  # noqa: BLE001
            return SolverResult(
                success=False,
                captcha_type=captcha_type,
                error=str(exc),
                response_time_ms=int((time.time() - start) * 1000),
            )

    def _solve_external(
        self,
        sitekey: str,
        url: str,
        action: Optional[str],
        captcha_type: CaptchaType,
        start: float,
    ) -> SolverResult:
        import httpx

        payload: Dict[str, Any] = {
            "type": captcha_type.value,
            "sitekey": sitekey,
            "url": url,
        }
        if action:
            payload["action"] = action
        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    self.external_api or "https://api.nonecap.com/v1/solve",
                    json=payload,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                )
                resp.raise_for_status()
                data = resp.json()
                elapsed = int((time.time() - start) * 1000)
                return SolverResult(
                    success=bool(data.get("token")),
                    captcha_type=captcha_type,
                    token=data.get("token"),
                    confidence=float(data.get("confidence", 1.0)),
                    response_time_ms=elapsed,
                    metadata={"external": True, "action": action},
                )
        except Exception as exc:  # noqa: BLE001
            elapsed = int((time.time() - start) * 1000)
            return SolverResult(
                success=False,
                captcha_type=captcha_type,
                error=f"الخدمة الخارجية فشلت: {exc}",
                response_time_ms=elapsed,
            )

    async def solve_async(self, *args: Any, **kwargs: Any) -> SolverResult:
        import asyncio

        return await asyncio.to_thread(self.solve, *args, **kwargs)
