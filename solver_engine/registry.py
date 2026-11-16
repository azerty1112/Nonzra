"""سجل المحركات: إدارة جميع حلّالات الكبتشا واختيار الأنسب لكل نوع."""

from typing import Any, Dict, List, Optional
import time

from .base import BaseSolver, CaptchaType, SolverResult
from .image import ImageCaptchaSolver, ImageSolveConfig
from .hcaptcha import HCaptchaSolver, ExternalService
from .recaptcha import ReCaptchaSolver
from .turnstile import TurnstileSolver
from .drag import DragSolver
from .point import PointSolver


class SolverRegistry:
    """السجل المركزي للمحركات مع دعم الفولباك والتسلسل."""

    def __init__(self) -> None:
        self._solvers: Dict[CaptchaType, List[BaseSolver]] = {}
        self._default_config = ImageSolveConfig()

    def register(self, solver: BaseSolver) -> None:
        self._solvers.setdefault(solver.captcha_type, []).append(solver)

    def get_solvers(self, captcha_type: CaptchaType) -> List[BaseSolver]:
        return self._solvers.get(captcha_type, [])

    def solve(
        self,
        captcha_type: CaptchaType,
        *args: Any,
        prefer_local: bool = True,
        **kwargs: Any,
    ) -> SolverResult:
        solvers = self.get_solvers(captcha_type)
        if not solvers:
            return SolverResult(
                success=False,
                captcha_type=captcha_type,
                error=f"لا يوجد حلّال مسجل للنوع {captcha_type.value}",
            )
        # sorting: المحلي أولاً إن طلب
        ordered = list(solvers)
        if prefer_local:
            ordered.sort(key=lambda s: not isinstance(s, ImageCaptchaSolver))

        last_error: Optional[str] = None
        for solver in ordered:
            try:
                result = solver.solve(*args, **kwargs)
                if result.success:
                    return result
                last_error = result.error
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
        return SolverResult(
            success=False,
            captcha_type=captcha_type,
            error=last_error or "فشل جميع المحركات",
            metadata={"attempted": len(ordered)},
        )

    async def solve_async(
        self,
        captcha_type: CaptchaType,
        *args: Any,
        prefer_local: bool = True,
        **kwargs: Any,
    ) -> SolverResult:
        import asyncio

        solvers = self.get_solvers(captcha_type)
        if not solvers:
            return SolverResult(
                success=False,
                captcha_type=captcha_type,
                error=f"لا يوجد حلّال مسجل للنوع {captcha_type.value}",
            )
        ordered = list(solvers)
        if prefer_local:
            ordered.sort(key=lambda s: not isinstance(s, ImageCaptchaSolver))

        async def _one(solver: BaseSolver) -> SolverResult:
            return await asyncio.to_thread(solver.solve, *args, **kwargs)

        last_error: Optional[str] = None
        for solver in ordered:
            try:
                result = await _one(solver)
                if result.success:
                    return result
                last_error = result.error
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
        return SolverResult(
            success=False,
            captcha_type=captcha_type,
            error=last_error or "فشل جميع المحركات",
            metadata={"attempted": len(ordered)},
        )


# مثيل افتراضي يتم استيراده في السيرفر
registry = SolverRegistry()
registry.register(ImageCaptchaSolver())
registry.register(HCaptchaSolver())
registry.register(ReCaptchaSolver())
registry.register(TurnstileSolver())
registry.register(DragSolver())
registry.register(PointSolver())


def configure_hcaptcha_external(
    api_key: Optional[str] = None,
    external_api: Optional[str] = None,
    external_api_type: str = "nonecap",
    external_services: Optional[List[Dict[str, Any]]] = None,
    max_retries: int = 10,
    retry_delay: float = 5.0,
    enable_fallback: bool = True,
) -> None:
    """ضبط حلّال hCaptcha لاستخدام خدمات خارجية مع الفولباك التلقائي وإعادة المحاولة حتى النجاح."""
    hcaptcha_solver = HCaptchaSolver(
        api_key=api_key,
        external_api=external_api,
        external_api_type=external_api_type,
        external_services=external_services,
        max_retries=max_retries,
        retry_delay=retry_delay,
        enable_fallback=enable_fallback,
    )
    registry._solvers[CaptchaType.HCAPTCHA] = [hcaptcha_solver]


def get_hcaptcha_service_stats() -> List[Dict[str, Any]]:
    """إرجاع إحصائيات خدمات hCaptcha الخارجية."""
    solvers = registry.get_solvers(CaptchaType.HCAPTCHA)
    for s in solvers:
        if isinstance(s, HCaptchaSolver):
            return s.get_service_stats()
    return []


__all__ = ["SolverRegistry", "registry", "configure_hcaptcha_external", "get_hcaptcha_service_stats"]
