"""الضبط التلقائي لمعاملات المعالجة المسبقة بناءً على النتائج السابقة (تعلّم تكيفي)."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import json
import random


@dataclass
class TuneStats:
    attempts: int = 0
    successes: int = 0
    total_confidence: float = 0.0
    total_latency_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        return self.successes / self.attempts if self.attempts else 0.0

    @property
    def avg_confidence(self) -> float:
        return self.total_confidence / self.attempts if self.attempts else 0.0

    def score(self) -> float:
        # مكافأة مركبة: النجاح أولاً، ثم الثقة، ثم السرعة
        speed_bonus = 0.0
        if self.attempts:
            avg_ms = self.total_latency_ms / self.attempts
            speed_bonus = max(0.0, 1.0 - avg_ms / 5000.0) * 0.1
        return self.success_rate * 0.7 + self.avg_confidence * 0.2 + speed_bonus


class AdaptiveTuner:
    """يختار أفضل معاملات (psm/threshold/denoise) تلقائيًا لكل سياق ويحسّنها تعلّمياً."""

    def __init__(self, epsilon: float = 0.15, seed: Optional[int] = None) -> None:
        self.epsilon = epsilon
        self._rng = random.Random(seed)
        self.stats: Dict[str, Dict[str, TuneStats]] = {}

    def candidates(self) -> List[Dict[str, Any]]:
        combos: List[Dict[str, Any]] = []
        for psm in (7, 8, 13):
            for threshold in ("otsu", "adaptive", "none"):
                for denoise in (True, False):
                    combos.append({"psm": psm, "threshold": threshold, "denoise": denoise})
        return combos

    @staticmethod
    def _key(params: Dict[str, Any]) -> str:
        return json.dumps(params, sort_keys=True)

    def _context(self, captcha_type: str) -> str:
        return captcha_type

    def choose(self, captcha_type: str, explore: bool = True) -> Dict[str, Any]:
        cands = self.candidates()
        ctx = self._context(captcha_type)
        bucket = self.stats.get(ctx, {})

        if explore and self._rng.random() < self.epsilon:
            return dict(self._rng.choice(cands))

        # استغلال: اختر الأفضل حسب السجل؛ غير المجرّب يُعطى أولوية استكشاف
        best: Optional[Dict[str, Any]] = None
        best_score = -1.0
        untried: List[Dict[str, Any]] = []
        for params in cands:
            st = bucket.get(self._key(params))
            if st is None or st.attempts == 0:
                untried.append(params)
                continue
            sc = st.score()
            if sc > best_score:
                best_score = sc
                best = params
        if untried:
            return dict(self._rng.choice(untried))
        if best is not None:
            return dict(best)
        return dict(self._rng.choice(cands))

    def record(
        self,
        captcha_type: str,
        params: Dict[str, Any],
        success: bool,
        confidence: float,
        latency_ms: int,
    ) -> None:
        ctx = self._context(captcha_type)
        bucket = self.stats.setdefault(ctx, {})
        key = self._key(params)
        st = bucket.setdefault(key, TuneStats())
        st.attempts += 1
        if success:
            st.successes += 1
        st.total_confidence += confidence
        st.total_latency_ms += latency_ms

    def best(self, captcha_type: str) -> Dict[str, Any]:
        ctx = self._context(captcha_type)
        bucket = self.stats.get(ctx, {})
        best_params: Optional[Dict[str, Any]] = None
        best_score = -1.0
        for key, st in bucket.items():
            if st.attempts == 0:
                continue
            sc = st.score()
            if sc > best_score:
                best_score = sc
                best_params = json.loads(key)
        if best_params is not None:
            return best_params
        return {"psm": 7, "threshold": "otsu", "denoise": True}

    def snapshot(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for ctx, bucket in self.stats.items():
            out[ctx] = {
                k: {
                    "attempts": v.attempts,
                    "success_rate": round(v.success_rate, 3),
                    "avg_confidence": round(v.avg_confidence, 3),
                    "score": round(v.score(), 3),
                }
                for k, v in bucket.items()
            }
        return out


__all__ = ["TuneStats", "AdaptiveTuner"]
