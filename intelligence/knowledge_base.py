"""قاعدة معرفة الأنماط الناجحة: تخزن خصائص الكبتشا والحلول الناجحة للاستفادة منها لاحقاً."""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
import hashlib
import json
import os
import time


KNOWLEDGE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "knowledge_base.json")


@dataclass
class CaptchaPattern:
    """نمط كبتشا تم حلّه بنجاح مسبقاً."""
    pattern_id: str
    captcha_type: str
    feature_hash: str  # بصمة خصائص الصورة
    text: Optional[str] = None
    token: Optional[str] = None
    confidence: float = 0.0
    success_count: int = 1
    total_attempts: int = 1
    last_seen: str = field(default_factory=lambda: __import__("datetime", fromlist=["datetime"]).datetime.now(__import__("datetime", fromlist=["timezone"]).timezone.utc).isoformat())
    features: Dict[str, float] = field(default_factory=dict)

    @property
    def success_rate(self) -> float:
        return self.success_count / self.total_attempts if self.total_attempts else 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CaptchaPattern":
        return cls(**data)


class KnowledgeBase:
    """قاعدة معرفة الأنماط الناجحة للاقتراب من الحلول بناءً على التشابه."""

    def __init__(self, path: str = KNOWLEDGE_FILE) -> None:
        self.path = path
        self.patterns: Dict[str, CaptchaPattern] = {}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.patterns = {k: CaptchaPattern.from_dict(v) for k, v in data.items()}
        except Exception:  # noqa: BLE001
            self.patterns = {}

    def _save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({k: v.to_dict() for k, v in self.patterns.items()}, f, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _hash_features(features: Dict[str, float]) -> str:
        raw = json.dumps(features, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

    def record_success(
        self,
        captcha_type: str,
        features: Dict[str, float],
        text: Optional[str] = None,
        token: Optional[str] = None,
        confidence: float = 0.0,
    ) -> str:
        """تُسجّل حلاً ناجحاً وتعيد معرف النمط."""
        feature_hash = self._hash_features(features)
        key = f"{captcha_type}:{feature_hash}"
        now = __import__("datetime", fromlist=["datetime"]).datetime.now(__import__("datetime", fromlist=["timezone"]).timezone.utc).isoformat()
        if key in self.patterns:
            p = self.patterns[key]
            p.success_count += 1
            p.total_attempts += 1
            p.last_seen = now
            p.confidence = max(p.confidence, confidence)
            if text and not p.text:
                p.text = text
            if token and not p.token:
                p.token = token
            p.features.update(features)
        else:
            self.patterns[key] = CaptchaPattern(
                pattern_id=key,
                captcha_type=captcha_type,
                feature_hash=feature_hash,
                text=text,
                token=token,
                confidence=confidence,
                features=dict(features),
            )
        self._save()
        return key

    def record_attempt(self, captcha_type: str, features: Dict[str, float], success: bool) -> None:
        """تُسجّل محاولة (نجاح أو فشل) لتحديث معدل النجاح للنمط."""
        feature_hash = self._hash_features(features)
        key = f"{captcha_type}:{feature_hash}"
        now = __import__("datetime", fromlist=["datetime"]).datetime.now(__import__("datetime", fromlist=["timezone"]).timezone.utc).isoformat()
        if key in self.patterns:
            p = self.patterns[key]
            p.total_attempts += 1
            if success:
                p.success_count += 1
            p.last_seen = now
        else:
            self.patterns[key] = CaptchaPattern(
                pattern_id=key,
                captcha_type=captcha_type,
                feature_hash=feature_hash,
                confidence=0.0,
                features=dict(features),
                success_count=1 if success else 0,
                total_attempts=1,
            )
        self._save()

    def suggest_params(
        self,
        captcha_type: str,
        features: Dict[str, float],
    ) -> Optional[Dict[str, Any]]:
        """يقترح معاملات واستراتيجية بناءً على أنماط ناجحة مشابهة."""
        similar = self.find_similar(captcha_type=captcha_type, features=features, min_success_rate=0.7, max_results=3)
        if not similar:
            return None
        best = similar[0]
        # استخلص أفضل المعاملات من أنماط ناجحة
        params: Dict[str, Any] = {}
        # ابحث عن النمط الأكثر نجاحاً واقترح استراتيجيته/معاملاته إذا وُجدت في السجل
        strategy = "local_primary"
        confidence = best.success_rate
        # إذا كان النمط لديه نص معروف، نستخدمه مباشرة
        if best.text:
            strategy = "knowledge_direct"
            confidence = min(best.confidence + 0.1, 0.99)
        return {
            "params": params,
            "strategy": strategy,
            "confidence": confidence,
            "pattern_id": best.pattern_id,
            "known_text": best.text,
            "known_token": best.token,
        }

    def find_similar(
        self,
        captcha_type: str,
        features: Dict[str, float],
        min_success_rate: float = 0.7,
        max_results: int = 5,
    ) -> List[CaptchaPattern]:
        """يجد أنماطاً مشابهة وناجحة بناءً علىotyp similarity."""
        candidates: List[tuple[float, CaptchaPattern]] = []
        for p in self.patterns.values():
            if p.captcha_type != captcha_type:
                continue
            if p.success_rate < min_success_rate:
                continue
            similarity = self._similarity(features, p.features)
            if similarity > 0.6:
                candidates.append((similarity, p))
        candidates.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in candidates[:max_results]]

    @staticmethod
    def _similarity(f1: Dict[str, float], f2: Dict[str, float]) -> float:
        keys = set(f1.keys()) | set(f2.keys())
        if not keys:
            return 0.0
        diff = sum(abs(f1.get(k, 0.0) - f2.get(k, 0.0)) for k in keys)
        return max(0.0, 1.0 - diff / len(keys))

    def stats(self) -> Dict[str, Any]:
        total = len(self.patterns)
        if total == 0:
            return {"total_patterns": 0, "avg_success_rate": 0.0, "by_type": {}}
        avg_sr = sum(p.success_rate for p in self.patterns.values()) / total
        by_type: Dict[str, int] = {}
        for p in self.patterns.values():
            by_type[p.captcha_type] = by_type.get(p.captcha_type, 0) + 1
        return {
            "total_patterns": total,
            "avg_success_rate": round(avg_sr, 3),
            "by_type": by_type,
        }


__all__ = ["CaptchaPattern", "KnowledgeBase", "KNOWLEDGE_FILE"]
