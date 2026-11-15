"""حلّال Cloudflare Turnstile."""

from typing import Any, Dict, Optional
import time

from .base import BaseSolver, CaptchaType, SolverResult


class TurnstileSolver(BaseSolver):
    captcha_type = CaptchaType.TURNSTILE

    def __init__(self, api_key: Optional[str] = None, external_api: Optional[str] = None) -> None:
        self.api_key = api_key
        self.external_api = external_api

    def solve(
        self,
        sitekey: Optional[str] = None,
        url: Optional[str] = None,
        action: Optional[str] = None,
        cdata: Optional[str] = None,
        **kwargs: Any,
    ) -> SolverResult:
        start = time.time()
        try:
            if self.external_api and self.api_key and sitekey and url:
                return self._solve_external(sitekey, url, action, cdata, start)
            return SolverResult(
                success=False,
                captcha_type=self.captcha_type,
                error="Turnstile يتطلب sitekey+url للخدمة الخارجية",
                response_time_ms=int((time.time() - start) * 1000),
            )
        except Exception as exc:  # noqa: BLE001
            return SolverResult(
                success=False,
                captcha_type=self.captcha_type,
                error=str(exc),
                response_time_ms=int((time.time() - start) * 1000),
            )

    def _solve_external(
        self,
        sitekey: str,
        url: str,
        action: Optional[str],
        cdata: Optional[str],
        start: float,
    ) -> SolverResult:
        import httpx

        payload: Dict[str, Any] = {
            "type": "turnstile",
            "sitekey": sitekey,
            "url": url,
        }
        if action:
            payload["action"] = action
        if cdata:
            payload["cdata"] = cdata
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
                    captcha_type=self.captcha_type,
                    token=data.get("token"),
                    confidence=float(data.get("confidence", 1.0)),
                    response_time_ms=elapsed,
                    metadata={"external": True},
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
