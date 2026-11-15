"""طبقة الذكاء المتكاملة والذاتية لمراقبة، حل، تفاعل بشري، وتحليل الكبتشا."""

from .knowledge_base import CaptchaPattern, KnowledgeBase, KNOWLEDGE_FILE
from .monitor import SolveEvent, Alert, IntelligentMonitor
from .analysis import CaptchaAnalysis, CaptchaAnalyzer
from .solver_strategy import SolveDecision, IntelligentSolverStrategy
from .human_behavior import HumanProfile, HumanBehavior
from .detector import Detection, AutoDetector
from .tuner import TuneStats, AdaptiveTuner
from .learning import ArmStats, LearningEngine
from .orchestrator import AutoResult, AutoOrchestrator
from .worker import WorkerJob, AutoWorker
from .experience_engine import ExperienceProfile, ExperienceEngine

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
    "CaptchaPattern",
    "KnowledgeBase",
    "KNOWLEDGE_FILE",
    "ExperienceProfile",
    "ExperienceEngine",
]

__version__ = "0.6.0"
