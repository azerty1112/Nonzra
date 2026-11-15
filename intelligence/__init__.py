"""طبقة الذكاء المتكاملة والذاتية لمراقبة، حل، تفاعل بشري، وتحليل الكبتشا."""

from .monitor import SolveEvent, Alert, IntelligentMonitor
from .analysis import CaptchaAnalysis, CaptchaAnalyzer
from .solver_strategy import SolveDecision, IntelligentSolverStrategy
from .human_behavior import HumanProfile, HumanBehavior
from .detector import Detection, AutoDetector
from .tuner import TuneStats, AdaptiveTuner
from .learning import ArmStats, LearningEngine
from .orchestrator import AutoResult, AutoOrchestrator
from .worker import WorkerJob, AutoWorker

__all__ = [
    "SolveEvent",
    "Alert",
    "IntelligentMonitor",
    "CaptchaAnalysis",
    "CaptchaAnalyzer",
    "SolveDecision",
    "IntelligentSolverStrategy",
    "HumanProfile",
    "HumanBehavior",
    "Detection",
    "AutoDetector",
    "TuneStats",
    "AdaptiveTuner",
    "ArmStats",
    "LearningEngine",
    "AutoResult",
    "AutoOrchestrator",
    "WorkerJob",
    "AutoWorker",
]

__version__ = "0.4.0"
