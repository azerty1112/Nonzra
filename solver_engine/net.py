"""إعداد الشبكة الموحّد: وكيل (proxy)، مهلة، ورؤوس، لطلبات الخدمات الخارجية.

سبب الوجود: بعض البيئات تحجب نطاق hCaptcha على مستوى TLS. تمرير الطلبات
عبر وكيل/نفق يعمل (بيت مستقل، 4G، VPS مجاني) هو الحل المجاني الوحيد.

الاستخدام:
    export NONECAP_PROXY=http://127.0.0.1:8080       # أو socks5://127.0.0.1:1080
    export NONECAP_HCAPTCHA_PROXY=http://127.0.0.1:8080   # خاص بـ hCaptcha
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

_PLACEHOLDER_MARKERS = ("PASTE_", "your_tunnel", "xxxx", "example.com", "change-me")


def _clean(value: Optional[str]) -> str:
    value = (value or "").strip().strip('"').strip("'")
    if not value:
        return ""
    lowered = value.lower()
    if any(marker.lower() in lowered for marker in _PLACEHOLDER_MARKERS):
        return ""
    if not (
        lowered.startswith("http://")
        or lowered.startswith("https://")
        or lowered.startswith("socks")
    ):
        return ""
    return value


@dataclass
class NetworkConfig:
    """لقطة إعدادات الشبكة الخارجية."""

    proxy: Optional[str] = None
    timeout_seconds: float = 60.0
    user_agent: str = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
    tunnel_header: Optional[Tuple[str, str]] = None

    @property
    def has_proxy(self) -> bool:
        return bool(self.proxy)

    def client_kwargs(self) -> Dict[str, Any]:
        """وسائط تُمرَّر إلى ``httpx.Client``."""
        kwargs: Dict[str, Any] = {
            "timeout": self.timeout_seconds,
            "follow_redirects": True,
        }
        if self.proxy:
            try:
                import httpx

                version = tuple(int(p) for p in httpx.__version__.split(".")[:2])
                if version >= (0, 26):
                    kwargs["proxy"] = self.proxy
                else:  # pragma: no cover - توافق مع إصدارات قديمة
                    kwargs["proxies"] = self.proxy
            except Exception:  # noqa: BLE001
                kwargs["proxy"] = self.proxy
        return kwargs

    def headers(self, extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Accept-Language": "en-US,en;q=0.9,ar;q=0.8",
        }
        if self.tunnel_header:
            headers[self.tunnel_header[0]] = self.tunnel_header[1]
        if extra:
            headers.update(extra)
        return headers

    def to_dict(self) -> Dict[str, Any]:
        """بدون كشف بيانات الوكيل كاملة في الواجهات العامة."""
        masked = None
        if self.proxy:
            masked = self.proxy
            if "@" in masked:
                scheme, _, rest = masked.partition("://")
                creds, _, host = rest.rpartition("@")
                user = creds.split(":")[0]
                masked = f"{scheme}://{user}:***@{host}"
        return {
            "proxy_configured": self.has_proxy,
            "proxy": masked,
            "timeout_seconds": self.timeout_seconds,
        }


def load_network_config() -> NetworkConfig:
    """يقرأ إعدادات الشبكة من متغيرات البيئة.

    | المتغير | المعنى |
    |---------|--------|
    | ``NONECAP_PROXY`` | وكيل HTTP/SOCKS لكل الطلبات الخارجية |
    | ``NONECAP_HCAPTCHA_PROXY`` | وكيل خاص بـ hCaptcha يتقدّم على العام |
    | ``NONECAP_TUNNEL_HEADER`` | رأس إضافي للنفق بصيغة ``Name: value`` |
    | ``NONECAP_HTTP_TIMEOUT`` | المهلة بالثواني (افتراضي 60) |
    """
    proxy = _clean(os.environ.get("NONECAP_HCAPTCHA_PROXY")) or _clean(
        os.environ.get("NONECAP_PROXY")
        or os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
    )
    timeout = 60.0
    raw_timeout = os.environ.get("NONECAP_HTTP_TIMEOUT", "").strip()
    if raw_timeout:
        try:
            timeout = max(5.0, float(raw_timeout))
        except ValueError:
            timeout = 60.0

    header: Optional[Tuple[str, str]] = None
    raw_header = (os.environ.get("NONECAP_TUNNEL_HEADER") or "").strip()
    if raw_header and ":" in raw_header:
        name, _, value = raw_header.partition(":")
        header = (name.strip(), value.strip())

    return NetworkConfig(
        proxy=proxy or None, timeout_seconds=timeout, tunnel_header=header
    )


NETWORK = load_network_config()


def hcaptcha_base_url() -> str:
    """عنوان خدمة hCaptcha (قابل للتغيير عبر النفق للاختبار أو التوجيه)."""
    override = (os.environ.get("NONECAP_HCAPTCHA_BASE") or "").strip().rstrip("/")
    if override and not any(m in override.lower() for m in _PLACEHOLDER_MARKERS):
        return override
    return "https://hcaptcha.com"


__all__ = ["NetworkConfig", "NETWORK", "load_network_config", "hcaptcha_base_url"]
