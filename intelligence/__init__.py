"""طبقة الذكاء المتكاملة والذاتية لمراقبة، حل، تفاعل بشري، وتحليل الكبتشا."""

from .analysis import CaptchaAnalysis, CaptchaAnalyzer
from .calibration import CalibrationBin, ConfidenceCalibrator
from .captcha_knowledge import (
    CAPTCHA_TYPES,
    PREPROCESS_BY_TYPE,
    SEED_TEXT_PATTERNS,
    STRATEGY_BY_TYPE,
    CaptchaTypeInfo,
    difficulty_score,
    get_preprocess,
    get_strategy,
    get_type_info,
    list_types,
    seed_knowledge_base,
)
from .competence import CompetenceEstimator, TypeCompetence
from .decision_planner import Decision, DecisionPlanner, Route
from .detector import AutoDetector, Detection
from .experience_engine import ExperienceEngine, ExperienceProfile
from .human_behavior import HumanBehavior, HumanProfile
from .knowledge_base import KNOWLEDGE_FILE, CaptchaPattern, KnowledgeBase
from .learning import ArmStats, LearningEngine
from .mind import Mind, MindCycle
from .monitor import Alert, IntelligentMonitor, SolveEvent
from .orchestrator import AutoOrchestrator, AutoResult
from .reflector import Lesson, SelfReflector, classify_error
from .solver_strategy import IntelligentSolverStrategy, SolveDecision
from .tuner import AdaptiveTuner, TuneStats
from .worker import AutoWorker, WorkerJob

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
    "CalibrationBin",
    "ConfidenceCalibrator",
    "TypeCompetence",
    "CompetenceEstimator",
    "Route",
    "Decision",
    "DecisionPlanner",
    "Lesson",
    "SelfReflector",
    "classify_error",
    "Mind",
    "MindCycle",
    "ExperienceProfile",
    "ExperienceEngine",
    "CaptchaTypeInfo",
    "CAPTCHA_TYPES",
    "SEED_TEXT_PATTERNS",
    "STRATEGY_BY_TYPE",
    "PREPROCESS_BY_TYPE",
    "get_type_info",
    "list_types",
    "get_strategy",
    "get_preprocess",
    "difficulty_score",
    "seed_knowledge_base",
]

__version__ = "0.7.0"
