"""التحقق من الهوية وإدارة مفاتيح API والتحكم في المعدل لكل مفتاح."""

from typing import Any, Dict, Optional
import hashlib
import json
import os
import secrets
import time


KEYS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "api_keys.json")


def _load_keys() -> Dict[str, Dict[str, Any]]:
    if not os.path.exists(KEYS_FILE):
        return {}
    try:
        with open(KEYS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {}


def _save_keys(keys: Dict[str, Dict[str, Any]]) -> None:
    try:
        with open(KEYS_FILE, "w", encoding="utf-8") as f:
            json.dump(keys, f, ensure_ascii=False, indent=2)
    except Exception:  # noqa: BLE001
        pass


class ApiKeyStore:
    """مستودع مفاتيح API مع 통제 الوصول والمعدل لكل مفتاح، تُحفظ في ملف JSON."""

    def __init__(self) -> None:
        self.keys: Dict[str, Dict[str, Any]] = _load_keys()
        self.usage: Dict[str, Dict[int, int]] = {}
        self._last_cleanup = time.time()

    def add(self, key_id: str, key_hash: str, name: Optional[str] = None) -> None:
        self.keys[key_id] = {
            "key_hash": key_hash,
            "name": name or "",
            "is_active": True,
            "created_at": time.time(),
            "usage_count": 0,
        }
        self.usage.setdefault(key_id, {})
        _save_keys(self.keys)

    def validate(self, api_key: str) -> Optional[Dict[str, Any]]:
        if not api_key:
            return None
        key_hash = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        for key_id, info in self.keys.items():
            if info.get("key_hash") == key_hash and info.get("is_active"):
                return {"key_id": key_id, **info}
        return None

    def record_usage(self, key_id: str) -> None:
        self.usage.setdefault(key_id, {})
        now_minute = int(time.time() // 60)
        self.usage[key_id][now_minute] = self.usage[key_id].get(now_minute, 0) + 1
        if key_id in self.keys:
            self.keys[key_id]["usage_count"] = int(self.keys[key_id].get("usage_count", 0)) + 1
            _save_keys(self.keys)

    def is_rate_limited(self, key_id: str, limit_per_minute: int = 60) -> bool:
        if key_id not in self.usage:
            return False
        now_minute = int(time.time() // 60)
        return self.usage[key_id].get(now_minute, 0) >= limit_per_minute

    def list_keys(self) -> list:
        out = []
        for key_id, info in self.keys.items():
            out.append({
                "key_id": key_id,
                "name": info.get("name", ""),
                "is_active": bool(info.get("is_active", True)),
                "created_at": info.get("created_at"),
                "usage_count": info.get("usage_count", 0),
                "key_hash_prefix": info.get("key_hash", "")[:8],
            })
        return out

    def deactivate(self, key_id: str) -> bool:
        if key_id not in self.keys:
            return False
        self.keys[key_id]["is_active"] = False
        _save_keys(self.keys)
        return True


api_key_store = ApiKeyStore()


def hash_api_key(api_key: str) -> str:
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def generate_api_key(prefix: str = "nc") -> str:
    return f"{prefix}_{secrets.token_urlsafe(32)}"


def extract_api_key(
    credentials: Optional[Any],
    x_api_key: Optional[str],
    query_api_key: Optional[str],
) -> Optional[str]:
    if credentials and credentials.scheme and credentials.scheme.lower() == "bearer":
        return credentials.credentials
    if x_api_key:
        return x_api_key
    return query_api_key


__all__ = [
    "ApiKeyStore",
    "api_key_store",
    "hash_api_key",
    "generate_api_key",
    "extract_api_key",
    "KEYS_FILE",
]
