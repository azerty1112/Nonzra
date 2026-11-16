"""حلّال hCaptcha (محلي مع خيار خدمة خارجية包括 nindiad)."""

from typing import Any, Dict, Optional
import base64
import time

from .base import BaseSolver, CaptchaType, SolverResult


class HCaptchaSolver(BaseSolver):
    captcha_type = CaptchaType.HCAPTCHA

    def __init__(
        self,
        api_key: Optional[str] = None,
        external_api: Optional[str] = None,
        external_api_type: str = "nonecap",
        max_retries: int = 5,
        retry_delay: float = 3.0,
    ) -> None:
        self.api_key = api_key
        self.external_api = external_api
        self.external_api_type = external_api_type  # "nonecap" أو "nindiad"
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    def solve(
        self,
        sitekey: Optional[str] = None,
        url: Optional[str] = None,
        image_b64: Optional[str] = None,
        **kwargs: Any,
    ) -> SolverResult:
        start = time.time()
        try:
            # إذا وُجدت خدمة خارجية، جرّبها مع إعادة المحاولة حتى النجاح
            if self.external_api and self.api_key and sitekey and url:
                return self._solve_external_with_retry(sitekey, url, start)

            # حل محلي للصورة المستخلصة من التحدي (إذا توفّرت)
            if image_b64:
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

    def _solve_external_with_retry(self, sitekey: str, url: str, start: float) -> SolverResult:
        """الحل عبر خدمة خارجية مع إعادة المحاولة التلقائية حتى النجاح أو نفاد المحاولات."""
        import httpx

        last_error = ""
        for attempt in range(1, self.max_retries + 1):
            try:
                elapsed = int((time.time() - start) * 1000)
                result = self._call_external_once(sitekey, url)
                if result.success:
                    result.response_time_ms = int((time.time() - start) * 1000)
                    result.metadata = {
                        **result.metadata,
                        "external": True,
                        "attempt": attempt,
                        "api_type": self.external_api_type,
                    }
                    return result

                last_error = result.error or "فشل غير معلوم"
                # انتظر قبل المحاولة التالية (باستثناء المحاولة الأخيرة)
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)

        return SolverResult(
            success=False,
            captcha_type=self.captcha_type,
            error=f"فشل حل hCaptcha بعد {self.max_retries} محاولة: {last_error}",
            response_time_ms=int((time.time() - start) * 1000),
            metadata={"external": True, "attempt": self.max_retries, "api_type": self.external_api_type},
        )

    def _call_external_once(self, sitekey: str, url: str) -> SolverResult:
        """استدعاء خدمة خارجية مرة واحدة."""
        import httpx

        if self.external_api_type == "nindiad":
            return self._call_nindiad(sitekey, url)
        return self._call_nonecap(sitekey, url)

    def _call_nonecap(self, sitekey: str, url: str) -> SolverResult:
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
                return SolverResult(
                    success=bool(data.get("token")),
                    captcha_type=self.captcha_type,
                    token=data.get("token"),
                    confidence=float(data.get("confidence", 1.0)),
                    metadata={"external": True, "resp_key": data.get("resp_key")},
                )
        except Exception as exc:  # noqa: BLE001
            return SolverResult(
                success=False,
                captcha_type=self.captcha_type,
                error=f"الخدمة الخارجية فشلت: {exc}",
            )

    def _call_nindiad(self, sitekey: str, url: str) -> SolverResult:
        """استدعاء خدمة nindiad لحل hCaptcha."""
        import httpx

        try:
            with httpx.Client(timeout=60.0) as client:
                resp = client.post(
                    (self.external_api or "").rstrip("/") + "/solve",
                    json={
                        "type": "hcaptcha",
                        "sitekey": sitekey,
                        "url": url,
                        "api_key": self.api_key,
                    },
                    headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
                # nindiad قد ترجع الحقل token أو captchaKey أو gRecaptchaResponse
                token = data.get("token") or data.get("captchaKey") or data.get("gRecaptchaResponse")
                return SolverResult(
                    success=bool(token),
                    captcha_type=self.captcha_type,
                    token=token,
                    confidence=float(data.get("confidence", 1.0)),
                    metadata={"external": True, "api_type": "nindiad", "raw": data},
                )
        except Exception as exc:  # noqa: BLE001
            return SolverResult(
                success=False,
                captcha_type=self.captcha_type,
                error=f"نindiad فشل: {exc}",
            )

    async def solve_async(self, *args: Any, **kwargs: Any) -> SolverResult:
        import asyncio

        return await asyncio.to_thread(self.solve, *args, **kwargs)


__all__ = ["HCaptchaSolver"]
