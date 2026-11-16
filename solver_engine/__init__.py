"""محرك حل الكبتشا المحلي - جميع المحركات والسجل المركزي."""

from .registry import SolverRegistry, registry, configure_hcaptcha_external, get_hcaptcha_service_stats
from .base import CaptchaType, SolverResult, BaseSolver
from .image import ImageCaptchaSolver, ImageSolveConfig
from .hcaptcha import HCaptchaSolver, ExternalService
from .recaptcha import ReCaptchaSolver
from .turnstile import TurnstileSolver
from .drag import DragSolver
from .point import PointSolver
from .cnn import CNNSolver, CNNConfig
from .db import Database

__all__ = [
    "SolverRegistry",
    "registry",
    "configure_hcaptcha_external",
    "get_hcaptcha_service_stats",
    "CaptchaType",
    "SolverResult",
    "BaseSolver",
    "ImageCaptchaSolver",
    "ImageSolveConfig",
    "HCaptchaSolver",
    "ExternalService",
    "ReCaptchaSolver",
    "TurnstileSolver",
    "DragSolver",
    "PointSolver",
    "CNNSolver",
    "CNNConfig",
    "Database",
]

__version__ = "0.2.0"
