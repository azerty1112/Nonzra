"""سجل المحركات: إدارة جميع حلّالات الكبتشا واختيار الأنسب لكل نوع."""

from typing import Any, Dict, List, Optional
import time

from .base import BaseSolver, CaptchaType, SolverResult
from .cnn import CNNSolver, CNNModelConfig, _TORCH_AVAILABLE
from .image import ImageCaptchaSolver, ImageSolveConfig
from .hcaptcha import HCaptchaSolver, ExternalService
from .recaptcha import ReCaptchaSolver
from .turnstile import TurnstileSolver
from .drag import DragSolver
from .point import PointSolver
from .slider import SliderSolver
from .rotate import RotateSolver
from .math import MathSolver
from .text import TextSolver


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
registry.register(SliderSolver())
registry.register(RotateSolver())
registry.register(MathSolver())
registry.register(TextSolver())


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


def configure_cnn_solver(
    model_path: Optional[str] = None,
    config: Optional[CNNModelConfig] = None,
) -> CNNSolver:
    """ضبط نموذج CNN للتعلم الذاتي."""
    cnn_config = config or CNNModelConfig()
    if model_path:
        cnn_config.model_path = model_path
    cnn_solver = CNNSolver(cnn_config)
    registry._solvers[CaptchaType.IMAGE] = [
        s for s in registry._solvers.get(CaptchaType.IMAGE, [])
        if not isinstance(s, CNNSolver)
    ] + [cnn_solver]
    return cnn_solver


def get_cnn_stats() -> Dict[str, Any]:
    """إرجاع إحصائيات نموذج CNN."""
    solvers = registry.get_solvers(CaptchaType.IMAGE)
    for s in solvers:
        if isinstance(s, CNNSolver):
            return {
                "available": s.is_model_available(),
                "trained": s.is_trained,
                "torch_available": _TORCH_AVAILABLE,
            }
    return {"available": False, "trained": False, "torch_available": _TORCH_AVAILABLE}


def get_capabilities() -> Dict[str, Any]:
    """يُعيد قائمة أنواع الكبتشا المدعومة وعدد المحركات المسجّلة لكل نوع."""
    types = {}
    for ctype, solvers in registry._solvers.items():
        types[ctype.value] = {
            "solvers": [type(s).__name__ for s in solvers],
            "count": len(solvers),
        }
    missing = sorted(
        t.value for t in CaptchaType if t.value not in types
    )
    return {
        "supported_types": sorted(types.keys()),
        "types": types,
        "unsupported_types": missing,
        "total_solvers": sum(v["count"] for v in types.values()),
    }


__all__ = [
    "SolverRegistry",
    "registry",
    "get_capabilities",
    "configure_hcaptcha_external",
    "get_hcaptcha_service_stats",
    "configure_cnn_solver",
    "get_cnn_stats",
]
