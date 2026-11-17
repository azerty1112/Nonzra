"""مجموعة بيانات الحل التلقائي والتدريب الذاتي من النتائج المؤكدة.

**الخصوصية أولًا.** هذا الملف يحفظ صور المستخدمين، فلا يجوز أن يكون سلوكه
الافتراضي «خزّن كل شيء دائمًا». الضوابط:

1. **معطّل افتراضيًا**: لا تُحفظ أي عينة إلا إذا فعّل المشغّل التخزين صراحةً
   عبر ``NONECAP_STORE_SAMPLES=true`` (أو ``CaptchaDataset(store_images=True)``).
   الوضع الافتراضي يحفظ **أرقامًا فقط** (نوع، ثقة، هل تؤكدت) لتحسين التعلّم
   بلا تخزين صور.
2. **حد صريح للتخزين**: سقف عدد العينات وأقدم عمر (``NONECAP_SAMPLES_MAX``،
   ``NONECAP_SAMPLES_TTL_HOURS``) مع حذف تلقائي — لا نمو بلا حد.
3. **حق الحذف**: ``DELETE /training/samples`` و``purge()`` يمحوان كل شيء
   (أو ما يخص نوعًا/مصدرًا) ويعيدان عدد المحذوف.
4. **كتابة مؤجّلة (batched)**: لا كتابة متزامنة لكل عينة (كانت O(n) لكل طلب).
   تُجمَّع الكتابات وتُنفَّذ عند بلوغ عتبة أو عند ``flush()``/الإيقاف.
5. **كتابة ذرّية**: ملف مؤقت ثم ``os.replace`` حتى لا يتلف الملف عند الانقطاع.
"""

import json
import os
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

DATA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "training_data.json")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "نعم")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


#: هل يحق تخزين صور المستخدمين؟ معطّل افتراضيًا — قرار صريح من المشغّل.
STORE_SAMPLES = _env_bool("NONECAP_STORE_SAMPLES", False)
#: سقف عدد العينات المحفوظة.
MAX_SAMPLES = max(0, _env_int("NONECAP_SAMPLES_MAX", 500))
#: أقدم عمر مسموح للعينة بالساعات (0 = بلا حد).
SAMPLES_TTL_HOURS = max(0, _env_int("NONECAP_SAMPLES_TTL_HOURS", 72))


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
    """تُخزّن عينات الكبتشا المحلولة وتسمح بالتأكيد عليها للتدريب الذاتي.

    آمن افتراضيًا: لا صور على القرص إلا بتفعيل صريح، مع سقف وعمر أقصى وحذف.
    """

    def __init__(
        self,
        path: str = DATA_FILE,
        store_images: Optional[bool] = None,
        max_samples: Optional[int] = None,
        ttl_hours: Optional[int] = None,
        flush_every: int = 10,
    ) -> None:
        self.path = path
        # القرار: صريح للمستدعي، وإلا متغيّر البيئة، وإلا لا تخزين
        self.store_images = STORE_SAMPLES if store_images is None else bool(store_images)
        self.max_samples = MAX_SAMPLES if max_samples is None else max(0, int(max_samples))
        self.ttl_hours = SAMPLES_TTL_HOURS if ttl_hours is None else max(0, int(ttl_hours))
        self.flush_every = max(1, int(flush_every))
        self.samples: List[CaptchaSample] = []
        self.dropped = 0  # كم عينة رُفضت/حُذفت بسبب السياسة
        self._lock = threading.RLock()
        self._dirty = False
        self._since_flush = 0
        self._load()

    # ---------- التحميل والحفظ ----------

    def _load(self) -> None:
        if not os.path.exists(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.samples = [CaptchaSample(**s) for s in data]
        except Exception:  # noqa: BLE001 - ملف تالف لا يمنع الإقلاع
            self.samples = []
        # ترقية آمنة: ملف قديم قد يحمل صورًا بلا إذن ⇒ نمحوها فورًا
        if not self.store_images and any(s.image_b64 for s in self.samples):
            for s in self.samples:
                s.image_b64 = None
            self._dirty = True
            self._save()
        # تطبيق السياسة على ما وُجد (قد يكون من إصدار أقدم يحفظ بلا حدود)
        self._enforce_limits()

    def _save(self) -> None:
        """كتابة ذرّية: ملف مؤقت ثم استبدال — لا ملف نصف مكتوب."""
        try:
            directory = os.path.dirname(os.path.abspath(self.path)) or "."
            os.makedirs(directory, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=directory, delete=False, suffix=".tmp"
            )
            try:
                json.dump([asdict(s) for s in self.samples], handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            finally:
                handle.close()
            os.replace(handle.name, self.path)
            self._dirty = False
            self._since_flush = 0
        except Exception:  # noqa: BLE001 - فشل الحفظ لا يعطّل الحل
            pass

    def flush(self, force: bool = False) -> bool:
        """ينفّذ الكتابة المؤجّلة إن وجدت تغييرات (يُستدعى عند الإيقاف)."""
        with self._lock:
            if not self._dirty:
                return False
            self._save()
            return True

    # ---------- السياسة ----------

    def _enforce_limits(self) -> None:
        """يطبّق سقف العدد والعمر، ويحذف الأقدم أولًا."""
        with self._lock:
            before = len(self.samples)
            if self.ttl_hours:
                cutoff = time.time() - self.ttl_hours * 3600
                kept = []
                for sample in self.samples:
                    try:
                        stamp = __import__("datetime", fromlist=["datetime"]).datetime.fromisoformat(
                            sample.created_at
                        ).timestamp()
                    except Exception:  # noqa: BLE001
                        stamp = time.time()
                    if stamp >= cutoff:
                        kept.append(sample)
                self.samples = kept
            if self.max_samples and len(self.samples) > self.max_samples:
                # الأحدث يبقى، الأقدم يُحذف
                self.samples = self.samples[-self.max_samples :]
            removed = before - len(self.samples)
            if removed:
                self.dropped += removed
                self._dirty = True
            if not self.store_images:
                # وضع «بلا صور»: نزيل أي صور محفوظة سابقًا (ترقية آمنة)
                stripped = 0
                for sample in self.samples:
                    if sample.image_b64:
                        sample.image_b64 = None
                        stripped += 1
                if stripped:
                    self.dropped += stripped
                    self._dirty = True

    # ---------- الإضافة ----------

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
        """يضيف عينة. يحفظ الصورة فقط إذا كان التخزين مفعّلًا صراحةً."""
        with self._lock:
            if not self.store_images:
                image_b64 = None  # الخصوصية: لا صور على القرص افتراضيًا
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
            self._enforce_limits()
            self._dirty = True
            self._since_flush += 1
            # كتابة مؤجّلة: لا نكتب الملف كاملًا في كل طلب
            if self._since_flush >= self.flush_every:
                self._save()
            return sample_id

    # ---------- التأكيد والحذف ----------

    def confirm(self, sample_id: str, text: Optional[str] = None) -> bool:
        with self._lock:
            for s in self.samples:
                if s.id == sample_id:
                    s.confirmed = True
                    if text:
                        s.text = text
                    self._dirty = True
                    self._save()
                    return True
            return False

    def purge(self, captcha_type: Optional[str] = None) -> int:
        """يحذف العينات (كلها أو لنوع محدّد) ويعيد عدد المحذوف. حق الحذف."""
        with self._lock:
            before = len(self.samples)
            if captcha_type:
                self.samples = [s for s in self.samples if s.captcha_type != captcha_type]
            else:
                self.samples = []
            removed = before - len(self.samples)
            self._dirty = True
            self._save()
            return removed

    def count_by_source(self, marker: str) -> int:
        """عدد العينات المؤكدة القادمة من مصدر معيّن (يُستخدم لعدّ ما بعد التدريب)."""
        with self._lock:
            return sum(1 for s in self.samples if s.confirmed and s.source == marker)

    def mark_retrained(self) -> None:
        """يضع علامة «تمّ التدريب» حتى لا تُحسب نفس العينات الجديدة مرتين."""
        self.add(
            captcha_type="_retrain",
            text="retrain_marker",
            source="retrain_marker",
            confirmed=True,
        )

    def stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "total": len(self.samples),
                "confirmed": sum(1 for s in self.samples if s.confirmed),
                "with_images": sum(1 for s in self.samples if s.image_b64),
                "store_images": self.store_images,
                "max_samples": self.max_samples,
                "ttl_hours": self.ttl_hours,
                "dropped": self.dropped,
                "privacy": (
                    "الصور تُحفظ محليًا لأن NONECAP_STORE_SAMPLES=true"
                    if self.store_images
                    else "لا تُحفظ صور (الوضع الافتراضي)"
                ),
            }


__all__ = ["CaptchaSample", "CaptchaDataset", "DATA_FILE"]
