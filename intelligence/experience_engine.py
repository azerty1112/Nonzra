"""محرك الخبرة: يُقيّم مستوى ذكاء النظام ويستخدم الأنماط المتراكمة لتحسين قرارات الحل."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import time

from .knowledge_base import KnowledgeBase, CaptchaPattern


@dataclass
class ExperienceProfile:
    """ملف تجربة النظام."""
    total_solved: int = 0
    total_attempts: int = 0
    total_auto_confirmed: int = 0
    experience_level: int = 1
    wisdom_score: float = 0.0
    knowledge_patterns: int = 0
    last_updated: str = field(default_factory=lambda: __import__("datetime", fromlist=["datetime"]).datetime.now(__import__("datetime", fromlist=["timezone"]).timezone.utc).isoformat())

    @property
    def success_rate(self) -> float:
        return self.total_solved / self.total_attempts if self.total_attempts else 0.0


class ExperienceEngine:
    """يُدير مستوى خبرة النظام ويوجّه القرارات بناءً على ما تعلّمه من التجارب السابقة."""

    LEVEL_THRESHOLDS = [10, 50, 150, 400, 1000, 2500, 5000, 10000]

    def __init__(self, knowledge_base: Optional[KnowledgeBase] = None) -> None:
        self.kb = knowledge_base or KnowledgeBase()
        self.profile = ExperienceProfile()

    def record_solution(
        self,
        captcha_type: str,
        success: bool,
        confidence: float,
        features: Optional[Dict[str, Any]] = None,
        text: Optional[str] = None,
        token: Optional[str] = None,
    ) -> Dict[str, Any]:
        """تُسجّل نتيجة حل وتُحدّث مستوى الخبرة."""
        self.profile.total_attempts += 1
        if success:
            self.profile.total_solved += 1

        # إذا كانت النتيجة ناجحة ومؤكدة، تُضاف لقاعدة المعرفة
        if success and confidence >= 0.85 and features is not None:
            feat_dict = {k: float(v) for k, v in features.items()}
            self.kb.record_success(
                captcha_type=captcha_type,
                features=feat_dict,
                text=text,
                token=token,
                confidence=confidence,
            )
            self.profile.total_auto_confirmed += 1
        elif features is not None:
            feat_dict = {k: float(v) for k, v in features.items()}
            self.kb.record_attempt(captcha_type=captcha_type, features=feat_dict, success=success)

        self._recalculate_level()
        self.profile.last_updated = __import__("datetime", fromlist=["datetime"]).datetime.now(__import__("datetime", fromlist=["timezone"]).timezone.utc).isoformat()
        return self.status()

    def find_known_solution(
        self,
        captcha_type: str,
        features: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """يبحث عن حل معروف لنمط مشابه، ويُعيده إذا وُجد."""
        feat_dict = {k: float(v) for k, v in features.items()}
        similar = self.kb.find_similar(captcha_type=captcha_type, features=feat_dict, min_success_rate=0.75)
        if not similar:
            return None
        best = similar[0]
        return {
            "pattern_id": best.pattern_id,
            "text": best.text,
            "token": best.token,
            "confidence": min(best.confidence + 0.05, 0.99),  # مكافأة التشابه
            "success_rate": best.success_rate,
            "source": "knowledge_base",
            "matches": len(similar),
        }

    def _recalculate_level(self) -> None:
        solved = self.profile.total_solved
        level = 1
        for threshold in self.LEVEL_THRESHOLDS:
            if solved >= threshold:
                level += 1
            else:
                break
        self.profile.experience_level = level
        # الحكمة = معدل النجاح × عدد الأنماط × مستوى الخبرة (مُقيّد)
        kb_stats = self.kb.stats()
        self.profile.knowledge_patterns = kb_stats.get("total_patterns", 0)
        sr = self.profile.success_rate
        self.profile.wisdom_score = round(
            min(1.0, sr) * min(1.0, self.profile.knowledge_patterns / 100.0) * min(1.0, level / 10.0),
            4,
        )

    def status(self) -> Dict[str, Any]:
        return {
            "experience_level": self.profile.experience_level,
            "wisdom_score": self.profile.wisdom_score,
            "total_solved": self.profile.total_solved,
            "total_attempts": self.profile.total_attempts,
            "success_rate": round(self.profile.success_rate, 3),
            "auto_confirmed": self.profile.total_auto_confirmed,
            "knowledge_patterns": self.profile.knowledge_patterns,
            "kb_stats": self.kb.stats(),
            "last_updated": self.profile.last_updated,
        }


__all__ = ["ExperienceProfile", "ExperienceEngine"]
