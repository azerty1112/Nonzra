"""محرك تعلّم ذاتي لاختيار الاستراتيجية (epsilon-greedy multi-armed bandit)."""

import random
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class ArmStats:
    pulls: int = 0
    reward_sum: float = 0.0

    @property
    def average(self) -> float:
        return self.reward_sum / self.pulls if self.pulls else 0.0


class LearningEngine:
    """يتعلم أي استراتيجية حل تعمل أفضل ويعززها تلقائيًا مع الحفاظ على الاستكشاف."""

    def __init__(
        self,
        arms: Optional[List[str]] = None,
        epsilon: float = 0.12,
        decay: float = 0.999,
        min_epsilon: float = 0.02,
        seed: Optional[int] = None,
    ) -> None:
        self.arms: List[str] = arms or [
            "local_primary",
            "ensemble_with_fallback",
            "external_primary",
        ]
        self.epsilon = epsilon
        self.decay = decay
        self.min_epsilon = min_epsilon
        self._rng = random.Random(seed)
        self.stats: Dict[str, ArmStats] = {a: ArmStats() for a in self.arms}

    def select(self) -> str:
        if self._rng.random() < self.epsilon:
            return self._rng.choice(self.arms)
        best_arm = self.arms[0]
        best_value = -1.0
        for arm in self.arms:
            st = self.stats[arm]
            # UCB-like: متوسط المكافأة + حد استكشاف للمجرّب قليلاً
            value = st.average + (0.2 / (st.pulls + 1) ** 0.5)
            if value > best_value:
                best_value = value
                best_arm = arm
        return best_arm

    def update(self, arm: str, reward: float) -> None:
        if arm not in self.stats:
            self.stats[arm] = ArmStats()
            self.arms.append(arm)
        st = self.stats[arm]
        st.pulls += 1
        st.reward_sum += max(0.0, min(1.0, reward))
        self.epsilon = max(self.min_epsilon, self.epsilon * self.decay)

    def reward_from_result(self, success: bool, confidence: float, latency_ms: int) -> float:
        if not success:
            return 0.05
        speed = max(0.0, 1.0 - latency_ms / 10000.0)
        return min(1.0, 0.55 + confidence * 0.35 + speed * 0.1)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "epsilon": round(self.epsilon, 4),
            "arms": {
                arm: {
                    "pulls": st.pulls,
                    "average_reward": round(st.average, 3),
                }
                for arm, st in self.stats.items()
            },
            "best": self.best_arm(),
        }

    def best_arm(self) -> str:
        return max(self.stats, key=lambda a: self.stats[a].average) if self.stats else self.arms[0]


__all__ = ["ArmStats", "LearningEngine"]
