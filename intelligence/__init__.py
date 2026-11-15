"""طبقة الذكاء المتكاملة والذاتية لمراقبة، حل، تفاعل بشري، وتحليل الكبتشا."""

from .captcha_knowledge import (
    CaptchaTypeInfo,
    CAPTCHA_TYPES,
    SEED_TEXT_PATTERNS,
    STRATEGY_BY_TYPE,
    PREPROCESS_BY_TYPE,
    get_type_info,
    list_types,
    get_strategy,
    get_preprocess,
    difficulty_score,
    seed_knowledge_base,
)
from .detector import Detection, AutoDetector
from .tuner import TuneStats, AdaptiveTuner
from .learning import ArmStats, LearningEngine
from .orchestrator import AutoResult, AutoOrchestrator
from .worker import WorkerJob, AutoWorker
from .experience_engine import ExperienceProfile, ExperienceEngine
from .monitor import SolveEvent, Alert, IntelligentMonitor
from .analysis import CaptchaAnalysis, CaptchaAnalyzer
from .solver_strategy import SolveDecision, IntelligentSolverStrategy
from .human_behavior import HumanProfile, HumanBehavior
from .knowledge_base import CaptchaPattern, KnowledgeBase, KNOWLEDGE_FILE

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
