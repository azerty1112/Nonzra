"""محرك حل الكبتشا المحلي - جميع المحركات والسجل المركزي."""

from .registry import (
    SolverRegistry,
    registry,
    configure_hcaptcha_external,
    get_hcaptcha_service_stats,
    configure_cnn_solver,
    get_cnn_stats,
    get_capabilities,
)
from .base import CaptchaType, SolverResult, BaseSolver
from .image import ImageCaptchaSolver, ImageSolveConfig
from .hcaptcha import HCaptchaSolver, ExternalService
from .recaptcha import ReCaptchaSolver
from .turnstile import TurnstileSolver
from .drag import DragSolver
from .point import PointSolver
from .slider import SliderSolver
from .rotate import RotateSolver
from .math import MathSolver, evaluate_expression, normalize_expression
from .text import TextSolver, NumericSolver
from .cnn import CNNSolver, CNNModelConfig, CaptchaCNN, CNNTrainer, CaptchaCharPrediction
from .db import Database

__all__ = [
    "SolverRegistry",
    "registry",
    "configure_hcaptcha_external",
    "get_hcaptcha_service_stats",
    "configure_cnn_solver",
    "get_cnn_stats",
    "get_capabilities",
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
    "SliderSolver",
    "RotateSolver",
    "MathSolver",
    "evaluate_expression",
    "normalize_expression",
    "TextSolver",
    "NumericSolver",
    "CNNSolver",
    "CNNModelConfig",
    "CaptchaCNN",
    "CNNTrainer",
    "CaptchaCharPrediction",
    "Database",
]

__version__ = "0.7.0"
