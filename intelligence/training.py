"""مجموعة بيانات الحل التلقائي والتدريب الذاتي من النتائج المؤكدة."""

import json
import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "training_data.json")


@dataclass
class CaptchaSample:
    id: str
    captcha_type: str
    image_b64: Optional[str] = None
    text: Optional[str] = None
    token: Optional[str] = None
    confidence: float = 0.0
    confirmed: bool = False
    source: str = "auto"
    created_at: str = field(default_factory=lambda: __import__("datetime", fromlist=["datetime"]).datetime.now(__import__("datetime", fromlist=["timezone"]).timezone.utc).isoformat())


class CaptchaDataset:
    """تُخزّن عينات الكبتشا المحلولة وتسمح بالتأكيد عليها للتدريب الذاتي."""

    def __init__(self, path: str = DATA_FILE) -> None:
        self.path = path
        self.samples: List[CaptchaSample] = []
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.samples = [CaptchaSample(**s) for s in data]
        except Exception:  # noqa: BLE001
            self.samples = []

    def _save(self) -> None:
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump([asdict(s) for s in self.samples], f, ensure_ascii=False, indent=2)
        except Exception:  # noqa: BLE001
            pass

    def add(
        self,
        captcha_type: str,
        image_b64: Optional[str] = None,
        text: Optional[str] = None,
        token: Optional[str] = None,
        confidence: float = 0.0,
        source: str = "auto",
        confirmed: bool = False,
    ) -> str:
        sample_id = __import__("uuid", fromlist=["uuid"]).uuid4().hex
        sample = CaptchaSample(
            id=sample_id,
            captcha_type=captcha_type,
            image_b64=image_b64,
            text=text,
            token=token,
            confidence=confidence,
            confirmed=confirmed,
            source=source,
        )
        self.samples.append(sample)
        self._save()
        return sample_id

    def confirm(self, sample_id: str, text: Optional[str] = None) -> bool:
        for s in self.samples:
            if s.id == sample_id:
                s.confirmed = True
                if text:
                    s.text = text
                self._save()
                return True
        return False

    def get_confirmed(self, captcha_type: Optional[str] = None) -> List[CaptchaSample]:
        out = [s for s in self.samples if s.confirmed]
        if captcha_type:
            out = [s for s in out if s.captcha_type == captcha_type]
        return out

    def stats(self) -> Dict[str, Any]:
        total = len(self.samples)
        confirmed = sum(1 for s in self.samples if s.confirmed)
        by_type: Dict[str, int] = {}
        for s in self.samples:
            by_type[s.captcha_type] = by_type.get(s.captcha_type, 0) + 1
        return {
            "total": total,
            "confirmed": confirmed,
            "confirmation_rate": round((confirmed / total * 100) if total else 0.0, 2),
            "by_type": by_type,
        }

    def new_since_retrain(self, marker: str = "retrain_marker") -> int:
        # عدد العينات المؤكدة المضافة منذ آخر إعادة تدريب (تُخزّن كعينة موجّهة)
        count = 0
        for s in self.samples:
            if s.confirmed and s.source == marker:
                count += 1
        return count

    def mark_retrained(self) -> None:
        self.add(
            captcha_type="_retrain",
            text="retrain_marker",
            source="retrain_marker",
            confirmed=True,
        )


__all__ = ["CaptchaSample", "CaptchaDataset", "DATA_FILE"]
