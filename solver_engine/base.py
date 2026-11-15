"""أنواع الكبتشا، نتيجة الحل، وفئة الأساس للحلّال."""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Optional


class CaptchaType(str, Enum):
    IMAGE = "image"
    HCAPTCHA = "hcaptcha"
    HCAPTCHA_ENTERPRISE = "hcaptcha_enterprise"
    RECAPTCHA_V2 = "recaptcha_v2"
    RECAPTCHA_V2_INVISIBLE = "recaptcha_v2_invisible"
    RECAPTCHA_V3 = "recaptcha_v3"
    TURNSTILE = "turnstile"
    DRAG = "drag"
    POINT = "point"
    SLIDER = "slider"
    ROTATE = "rotate"
    FUNCAPTCHA = "funcaptcha"
    GEE_TEST = "geetest"
    TEXT = "text"
    MATH = "math"


@dataclass
class SolverResult:
    success: bool
    captcha_type: CaptchaType
    text: Optional[str] = None
    token: Optional[str] = None
    confidence: float = 0.0
    response_time_ms: int = 0
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "captcha_type": self.captcha_type.value,
            "text": self.text,
            "token": self.token,
            "confidence": self.confidence,
            "response_time_ms": self.response_time_ms,
            "error": self.error,
            "metadata": self.metadata,
        }


class BaseSolver:
    """فئة الأساس لكل حلّال كبتشا."""

    captcha_type: CaptchaType

    def solve(self, *args: Any, **kwargs: Any) -> SolverResult:
        raise NotImplementedError

    async def solve_async(self, *args: Any, **kwargs: Any) -> SolverResult:
        raise NotImplementedError

    def supports(self, captcha_type: CaptchaType) -> bool:
        return self.captcha_type == captcha_type
