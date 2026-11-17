"""سياسة التشغيل: حدود الطلبات، المصادقة، والاحتفاظ بالذاكرة.

الهدف: خادم «مجاني بلا حدود» افتراضيًا — لكن مع إمكانية تضييق القيود
عند النشر العام عبر متغيرات بيئة واضحة. كل شيء يُقرأ من البيئة مرة واحدة
عند الإقلاع حتى لا يتغيّر السلوك وسط التشغيل.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "y")


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(float(raw))
    except ValueError:
        return default


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    return default if raw is None or raw.strip() == "" else raw.strip()


@dataclass(frozen=True)
class RuntimePolicy:
    """لقطة ثابتة من إعدادات السياسة."""

    unlimited: bool
    require_api_key: bool
    per_ip_per_minute: int
    per_key_per_minute: int
    ip_block_seconds: int
    job_ttl_seconds: int
    max_jobs_retained: int
    max_batch_items: int
    concurrency: int
    max_concurrency: int
    #: أقصى حجم لصورة واحدة بعد فك ترميز base64 (بايت). 0 = بلا حد.
    max_image_bytes: int
    #: أقصى حجم لجسم الطلب كاملًا (بايت). 0 = بلا حد.
    max_body_bytes: int
    #: هل نصدّق ترويسة X-Forwarded-For؟ صحيح فقط خلف وكيل عكسي موثوق.
    trust_forwarded_for: bool

    @property
    def rate_limited(self) -> bool:
        return not self.unlimited and self.per_ip_per_minute > 0

    def to_dict(self) -> Dict[str, object]:
        return {
            "unlimited": self.unlimited,
            "require_api_key": self.require_api_key,
            "per_ip_per_minute": 0 if self.unlimited else self.per_ip_per_minute,
            "per_key_per_minute": 0 if self.unlimited else self.per_key_per_minute,
            "ip_block_seconds": 0 if self.unlimited else self.ip_block_seconds,
            "job_ttl_seconds": self.job_ttl_seconds,
            "max_jobs_retained": self.max_jobs_retained,
            "max_batch_items": self.max_batch_items,
            "concurrency": self.concurrency,
            "max_concurrency": self.max_concurrency,
            "max_image_bytes": self.max_image_bytes,
            "max_body_bytes": self.max_body_bytes,
            "trust_forwarded_for": self.trust_forwarded_for,
            "mode": "unlimited" if self.unlimited else "guarded",
        }


def load_policy() -> RuntimePolicy:
    """يبني السياسة من متغيرات البيئة.

    | المتغير | الافتراضي | المعنى |
    |---------|-----------|--------|
    | ``NONECAP_UNLIMITED`` | ``1`` | ``1`` = بلا حدود وبلا مفتاح إلزامي |
    | ``NONECAP_REQUIRE_API_KEY`` | ``0`` | إلزام مفتاح API لكل الطلبات |
    | ``NONECAP_RATE_LIMIT_PER_MINUTE`` | ``0`` | حد لكل IP (0 = بلا حد) |
    | ``NONECAP_KEY_RATE_LIMIT_PER_MINUTE`` | ``0`` | حد لكل مفتاح |
    | ``NONECAP_IP_BLOCK_SECONDS`` | ``0`` | مدة الحظر بعد التجاوز |
    | ``NONECAP_JOB_TTL_SECONDS`` | ``3600`` | حذف المهام المنتهية تلقائيًا |
    | ``NONECAP_MAX_JOBS`` | ``5000`` | سقف المهام المحفوظة في الذاكرة |
    | ``NONECAP_MAX_BATCH`` | ``200`` | سقف عناصر الطلب الجماعي |
    | ``NONECAP_CONCURRENCY`` | ``4`` | عمال الحل بالتوازي |
    | ``NONECAP_MAX_CONCURRENCY`` | ``16`` | سقف التوسّع التلقائي |
    | ``NONECAP_MAX_IMAGE_BYTES`` | ``8388608`` (8 ميغا) | أقصى صورة بعد فك الترميز |
    | ``NONECAP_MAX_BODY_BYTES`` | ``12582912`` (12 ميغا) | أقصى جسم طلب كامل |
    | ``NONECAP_TRUST_FORWARDED_FOR`` | ``false`` | تصديق X-Forwarded-For (للوكيل العكسي فقط) |
    """
    unlimited = _env_bool("NONECAP_UNLIMITED", True)
    require_key = _env_bool("NONECAP_REQUIRE_API_KEY", False)

    per_ip = _env_int("NONECAP_RATE_LIMIT_PER_MINUTE", 0)
    per_key = _env_int("NONECAP_KEY_RATE_LIMIT_PER_MINUTE", 0)
    block = _env_int("NONECAP_IP_BLOCK_SECONDS", 0)
    if unlimited:
        per_ip = 0
        per_key = 0
        block = 0
        require_key = False

    return RuntimePolicy(
        unlimited=unlimited,
        require_api_key=require_key,
        per_ip_per_minute=max(0, per_ip),
        per_key_per_minute=max(0, per_key),
        ip_block_seconds=max(0, block),
        job_ttl_seconds=max(60, _env_int("NONECAP_JOB_TTL_SECONDS", 3600)),
        max_jobs_retained=max(100, _env_int("NONECAP_MAX_JOBS", 5000)),
        max_batch_items=max(1, _env_int("NONECAP_MAX_BATCH", 200)),
        concurrency=max(1, _env_int("NONECAP_CONCURRENCY", 4)),
        max_concurrency=max(1, _env_int("NONECAP_MAX_CONCURRENCY", 16)),
        max_image_bytes=max(0, _env_int("NONECAP_MAX_IMAGE_BYTES", 8 * 1024 * 1024)),
        max_body_bytes=max(0, _env_int("NONECAP_MAX_BODY_BYTES", 12 * 1024 * 1024)),
        # افتراضيًا لا نصدّق الترويسة: أي عميل يمكنه تزويرها وتجاوز الحظر
        # وتحديد المعدل. خلف وكيل عكسي تُفعَّل صراحةً.
        trust_forwarded_for=_env_bool("NONECAP_TRUST_FORWARDED_FOR", False),
    )


POLICY = load_policy()

__all__ = ["RuntimePolicy", "POLICY", "load_policy"]
