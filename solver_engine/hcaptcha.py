"""حلّال hCaptcha مع سلسلة خدمات خارجية متعددة وإعادة محاولة تلقائية حتى النجاح."""

from typing import Any, Dict, List, Optional
import base64
import time

from .base import BaseSolver, CaptchaType, SolverResult


class ExternalService:
    """تمثيل خدمة خارجية واحدة مع إعداداتها وحالتها."""

    def __init__(
        self,
        name: str,
        api_url: str,
        api_key: str,
        api_type: str = "nonecap",
        enabled: bool = True,
        max_retries: int = 3,
        retry_delay: float = 5.0,
        timeout: float = 60.0,
    ) -> None:
        self.name = name
        self.api_url = api_url
        self.api_key = api_key
        self.api_type = api_type
        self.enabled = enabled
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.timeout = timeout
        self.success_count = 0
        self.fail_count = 0
        self.last_success: Optional[float] = None
        self.last_fail: Optional[float] = None
        self.avg_response_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        total = self.success_count + self.fail_count
        return self.success_count / total if total else 0.0

    @property
    def is_healthy(self) -> bool:
        return self.enabled and self.success_rate >= 0.3


class HCaptchaSolver(BaseSolver):
    captcha_type = CaptchaType.HCAPTCHA

    def __init__(
        self,
        api_key: Optional[str] = None,
        external_api: Optional[str] = None,
        external_api_type: str = "nonecap",
        external_services: Optional[List[Dict[str, Any]]] = None,
        max_retries: int = 5,
        retry_delay: float = 3.0,
        enable_fallback: bool = True,
    ) -> None:
        self.api_key = api_key
        self.external_api = external_api
        self.external_api_type = external_api_type
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        self.enable_fallback = enable_fallback
        self.services: List[ExternalService] = []

        # الخدمة الأساسية من الإعدادات المباشرة
        if external_api and api_key:
            self.services.append(
                ExternalService(
                    name="primary",
                    api_url=external_api,
                    api_key=api_key,
                    api_type=external_api_type,
                    max_retries=max_retries,
                    retry_delay=retry_delay,
                )
            )

        # خدمات احتياطية إضافية
        if external_services:
            for svc in external_services:
                self.services.append(
                    ExternalService(
                        name=svc.get("name", f"fallback_{len(self.services)}"),
                        api_url=svc.get("api_url", ""),
                        api_key=svc.get("api_key", ""),
                        api_type=svc.get("api_type", "nonecap"),
                        enabled=svc.get("enabled", True),
                        max_retries=svc.get("max_retries", max_retries),
                        retry_delay=svc.get("retry_delay", retry_delay),
                        timeout=svc.get("timeout", 60.0),
                    )
                )

    def solve(
        self,
        sitekey: Optional[str] = None,
        url: Optional[str] = None,
        image_b64: Optional[str] = None,
        **kwargs: Any,
    ) -> SolverResult:
        start = time.time()
        try:
            # إذا وُجدت خدمات خارجية، جرّبها مع الفولباك التلقائي
            if self.services and sitekey and url:
                return self._solve_external_chain(sitekey, url, start)

            # حل محلي للصورة المستخلصة من التحدي
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

    def _solve_external_chain(self, sitekey: str, url: str, start: float) -> SolverResult:
        """تجربة الخدمات الخارجية بالتتابع مع الفولباك التلقائي حتى النجاح."""
        import httpx

        # ترتيب الخدمات حسب healthier أولاً (معدل نجاح أعلى)
        sorted_services = sorted(self.services, key=lambda s: s.success_rate, reverse=True)
        healthy_services = [s for s in sorted_services if s.is_healthy]
        fallback_services = [s for s in sorted_services if not s.is_healthy and s.enabled]

        candidates = healthy_services + fallback_services

        if not candidates:
            return SolverResult(
                success=False,
                captcha_type=self.captcha_type,
                error="لا توجد خدمات خارجية متاحة",
                response_time_ms=int((time.time() - start) * 1000),
            )

        last_error = ""
        for service in candidates:
            for attempt in range(1, service.max_retries + 1):
                try:
                    svc_start = time.time()
                    result = self._call_service_once(service, sitekey, url)
                    svc_elapsed = int((time.time() - svc_start) * 1000)

                    if result.success:
                        service.success_count += 1
                        service.last_success = time.time()
                        # تحديث متوسط الاستجابة
                        service.avg_response_ms = (
                            service.avg_response_ms * 0.7 + svc_elapsed * 0.3
                        )
                        result.response_time_ms = int((time.time() - start) * 1000)
                        result.metadata = {
                            **result.metadata,
                            "external": True,
                            "service": service.name,
                            "service_type": service.api_type,
                            "attempt": attempt,
                            "services_tried": [s.name for s in candidates[: sorted_services.index(service) + 1]],
                        }
                        return result

                    last_error = result.error or "فشل غير معلوم"
                    service.fail_count += 1
                    service.last_fail = time.time()

                    if attempt < service.max_retries:
                        time.sleep(service.retry_delay)

                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
                    service.fail_count += 1
                    service.last_fail = time.time()
                    if attempt < service.max_retries:
                        time.sleep(service.retry_delay)

        return SolverResult(
            success=False,
            captcha_type=self.captcha_type,
            error=f"فشل جميع خدمات hCaptcha الخارجية ({len(candidates)} خدمة): {last_error}",
            response_time_ms=int((time.time() - start) * 1000),
            metadata={
                "external": True,
                "services_tried": [s.name for s in candidates],
                "all_failed": True,
            },
        )

    def _call_service_once(self, service: ExternalService, sitekey: str, url: str) -> SolverResult:
        """استدعاء خدمة خارجية واحدة مرة واحدة."""
        import httpx

        if service.api_type == "nindiad":
            return self._call_nindiad(service, sitekey, url)
        return self._call_nonecap(service, sitekey, url)

    def _call_nonecap(self, service: ExternalService, sitekey: str, url: str) -> SolverResult:
        import httpx

        try:
            with httpx.Client(timeout=service.timeout) as client:
                resp = client.post(
                    service.api_url.rstrip("/") + "/v1/solve",
                    json={"type": "hcaptcha", "sitekey": sitekey, "url": url},
                    headers={"Authorization": f"Bearer {service.api_key}"},
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
                error=f"الخدمة الخارجية ({service.name}) فشلت: {exc}",
            )

    def _call_nindiad(self, service: ExternalService, sitekey: str, url: str) -> SolverResult:
        """استدعاء خدمة nindiad لحل hCaptcha."""
        import httpx

        try:
            with httpx.Client(timeout=service.timeout) as client:
                resp = client.post(
                    service.api_url.rstrip("/") + "/solve",
                    json={
                        "type": "hcaptcha",
                        "sitekey": sitekey,
                        "url": url,
                        "api_key": service.api_key,
                    },
                    headers={"Authorization": f"Bearer {service.api_key}", "Content-Type": "application/json"},
                )
                resp.raise_for_status()
                data = resp.json()
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
                error=f"نindiad ({service.name}) فشل: {exc}",
            )

    def get_service_stats(self) -> List[Dict[str, Any]]:
        """إرجاع إحصائيات جميع الخدمات المسجلة."""
        return [
            {
                "name": s.name,
                "api_type": s.api_type,
                "enabled": s.enabled,
                "success_rate": round(s.success_rate, 3),
                "success_count": s.success_count,
                "fail_count": s.fail_count,
                "avg_response_ms": round(s.avg_response_ms, 1),
                "is_healthy": s.is_healthy,
                "last_success": s.last_success,
                "last_fail": s.last_fail,
            }
            for s in self.services
        ]

    async def solve_async(self, *args: Any, **kwargs: Any) -> SolverResult:
        import asyncio

        return await asyncio.to_thread(self.solve, *args, **kwargs)


__all__ = ["HCaptchaSolver", "ExternalService"]
