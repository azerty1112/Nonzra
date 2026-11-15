"""طبقة الذكاء التفاعلي - محاكاة السلوك البشري (حركات ماوس، كتابة، تأخيرات)."""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional
import math
import random
import time


@dataclass
class HumanProfile:
    """ملف سلوك بشري قابل للتخصيص."""
    min_delay_ms: int = 300
    max_delay_ms: int = 1200
    typing_wpm: int = 45  # الكلمات في الدقيقة
    mouse_speed_px_per_sec: int = 450
    jitter_factor: float = 0.15  # نسبة الاهتزاز الطبيعي
    hesitation_chance: float = 0.08  # فرصة التردد قبل الإجراء
    error_chance: float = 0.02  # فرصة كتابة حرف خاطئ ثم تصحيحه


class HumanBehavior:
    """محاكي للتفاعل البشري الطبيعي لتجنب الكشف الآلي."""

    def __init__(self, profile: Optional[HumanProfile] = None, seed: Optional[int] = None) -> None:
        self.profile = profile or HumanProfile()
        self._rng = random.Random(seed)

    def delay(self, kind: str = "interaction") -> float:
        """تأخير بشري随وخي بالنوع."""
        base = self.profile.min_delay_ms
        top = self.profile.max_delay_ms
        if kind == "typing_char":
            # تأخير بين الحروف بناءً على سرعة الكتابة
            ms_per_char = 60_000 / (self.profile.typing_wpm * 5)
            base = int(ms_per_char * 0.7)
            top = int(ms_per_char * 1.6)
        elif kind == "mouse_move":
            base = 50
            top = 250
        elif kind == "click":
            base = 100
            top = 350
        elif kind == "hesitation":
            base = 800
            top = 2500
        jitter = self._rng.uniform(-self.profile.jitter_factor, self.profile.jitter_factor)
        ms = self._rng.uniform(base, top) * (1 + jitter)
        return max(50, ms) / 1000.0

    def should_hesitate(self) -> bool:
        return self._rng.random() < self.profile.hesitation_chance

    def should_make_error(self) -> bool:
        return self._rng.random() < self.profile.error_chance

    def bezier_curve(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
        steps: int = 20,
        curvature: Optional[float] = None,
    ) -> List[Tuple[float, float]]:
        """منحنى بييزيير تربيعي لحركة ماوس بشرية غير خطية."""
        if curvature is None:
            curvature = self._rng.uniform(0.2, 0.6)
        x0, y0 = start
        x1, y1 = end
        # نقطة تحكم وسطية مع إزاحة عشوائية عمودية على الخط
        mx = (x0 + x1) / 2
        my = (y0 + y1) / 2
        dx = x1 - x0
        dy = y1 - y0
        length = math.hypot(dx, dy) or 1.0
        nx = -dy / length
        ny = dx / length
        offset = self._rng.uniform(-curvature * length, curvature * length)
        cx = mx + nx * offset
        cy = my + ny * offset
        points: List[Tuple[float, float]] = []
        for i in range(steps + 1):
            t = i / steps
            # توزيع غير خطي (تسريع ثم إبطاء) يشبه حركة يد بشرية
            t_eased = self._ease_in_out(t)
            xt = (1 - t_eased) ** 2 * x0 + 2 * (1 - t_eased) * t_eased * cx + t_eased ** 2 * x1
            yt = (1 - t_eased) ** 2 * y0 + 2 * (1 - t_eased) * t_eased * cy + t_eased ** 2 * y1
            # إضافة اهتزاز بسيط
            xt += self._rng.gauss(0, self.profile.jitter_factor * 2)
            yt += self._rng.gauss(0, self.profile.jitter_factor * 2)
            points.append((xt, yt))
        return points

    @staticmethod
    def _ease_in_out(t: float) -> float:
        return t * t * (3 - 2 * t)

    def human_typing_sequence(self, text: str) -> List[Tuple[str, float]]:
        """تسلسل كتابة بشرية: (حرف، تأخير قبله) مع احتمالية تصحيح أخطاء."""
        events: List[Tuple[str, float]] = []
        i = 0
        while i < len(text):
            ch = text[i]
            events.append((ch, self.delay("typing_char")))
            if self.should_make_error() and ch.isalpha():
                wrong = self._rng.choice("abcdefghijklmnopqrstuvwxyz")
                events.append((wrong, self.delay("typing_char")))
                events.append(("\b", self.delay("click")))
                events.append((ch, self.delay("typing_char")))
            i += 1
        return events

    def human_mouse_path(
        self,
        start: Tuple[float, float],
        end: Tuple[float, float],
    ) -> List[Tuple[float, float, float]]:
        """مسار ماوس كامل مع أزمنة بالثواني: [(x, y, delay_before_sec), ...]."""
        points = self.bezier_curve(start, end, steps=self._rng.randint(12, 30))
        path: List[Tuple[float, float, float]] = []
        total = len(points)
        for idx, (x, y) in enumerate(points):
            # تأخير متغير حسب المسافة المتبقية (بالمللي ثانية ثم تحويل إلى ثواني)
            remaining = total - idx
            base_ms = max(8, 80 / remaining)
            delay_sec = self._rng.uniform(base_ms, base_ms * 2.5) / 1000.0
            path.append((x, y, delay_sec))
        return path


__all__ = ["HumanProfile", "HumanBehavior"]
