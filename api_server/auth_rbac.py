"""نظام إدارة المستخدمين مع التحكم في الوصول بناءً على الأدوار (RBAC)."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from enum import Enum
import uuid
import time
import hashlib
import json
import os


class UserRole(str, Enum):
    """أدوار المستخدمين في النظام."""
    ADMIN = "admin"      # مسؤول النظام - صلاحيات كاملة
    OPERATOR = "operator" # مشغل - يمكنه حل الكبتشا وعرض الإحصائيات
    USER = "user"        # مستخدم عادي - حل الكبتشا فقط
    GUEST = "guest"      # زائر - صلاحيات محدودة جداً


@dataclass
class User:
    """مستخدم في النظام."""
    user_id: str
    username: str
    role: UserRole
    api_key: str
    api_key_hash: str
    is_active: bool = True
    created_at: str = field(default_factory=lambda: _now())
    last_login: Optional[str] = None
    total_solves: int = 0
    total_attempts: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "user_id": self.user_id,
            "username": self.username,
            "role": self.role.value,
            "is_active": self.is_active,
            "created_at": self.created_at,
            "last_login": self.last_login,
            "total_solves": self.total_solves,
            "total_attempts": self.total_attempts,
            # لا نعيد مفتاح API أو تشفيره للأمان
        }


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _hash_key(api_key: str) -> str:
    """تشفير مفتاح API."""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def _generate_api_key() -> str:
    """إنشاء مفتاح API عشوائي."""
    return f"nc_{uuid.uuid4().hex}_{uuid.uuid4().hex[:8]}"


class UserManager:
    """مدير المستخدمين والتحكم في الوصول."""

    def __init__(self) -> None:
        self.users: Dict[str, User] = {}
        self.api_keys: Dict[str, str] = {}  # api_key_hash -> user_id
        self._load_default_admin()

    def _load_default_admin(self) -> None:
        """إنشاء مسؤول افتراضي إذا لم يكن هناك مستخدمون."""
        if not self.users:
            admin_key = _generate_api_key()
            self.create_user(
                username="admin",
                role=UserRole.ADMIN,
                api_key=admin_key,
            )
            print(f"تم إنشاء مسؤول افتراضي. مفتاح API: {admin_key}")

    def create_user(
        self,
        username: str,
        role: UserRole = UserRole.USER,
        api_key: Optional[str] = None,
    ) -> User:
        """إنشاء مستخدم جديد."""
        if username in [u.username for u in self.users.values()]:
            raise ValueError(f"المستخدم {username} موجود بالفعل")

        if api_key is None:
            api_key = _generate_api_key()

        key_hash = _hash_key(api_key)
        user_id = str(uuid.uuid4())

        user = User(
            user_id=user_id,
            username=username,
            role=role,
            api_key=api_key,
            api_key_hash=key_hash,
        )

        self.users[user_id] = user
        self.api_keys[key_hash] = user_id
        return user

    def get_user(self, user_id: str) -> Optional[User]:
        """الحصول على مستخدم بواسطة المعرف."""
        return self.users.get(user_id)

    def get_user_by_api_key(self, api_key: str) -> Optional[User]:
        """الحصول على مستخدم بواسطة مفتاح API."""
        key_hash = _hash_key(api_key)
        user_id = self.api_keys.get(key_hash)
        if user_id:
            return self.users.get(user_id)
        return None

    def list_users(self) -> List[User]:
        """قائمة جميع المستخدمين."""
        return list(self.users.values())

    def update_user(
        self,
        user_id: str,
        role: Optional[UserRole] = None,
        is_active: Optional[bool] = None,
    ) -> Optional[User]:
        """تحديث مستخدم."""
        user = self.users.get(user_id)
        if not user:
            return None

        if role is not None:
            user.role = role
        if is_active is not None:
            user.is_active = is_active

        return user

    def delete_user(self, user_id: str) -> bool:
        """حذف مستخدم."""
        user = self.users.get(user_id)
        if not user:
            return False

        # لا يمكن حذف المسؤول الأخير
        if user.role == UserRole.ADMIN:
            admins = [u for u in self.users.values() if u.role == UserRole.ADMIN]
            if len(admins) <= 1:
                raise ValueError("لا يمكن حذف المسؤول الأخير")

        del self.users[user_id]
        if user.api_key_hash in self.api_keys:
            del self.api_keys[user.api_key_hash]
        return True

    def authenticate(self, api_key: str) -> Optional[User]:
        """المصادقة باستخدام مفتاح API."""
        return self.get_user_by_api_key(api_key)

    def has_permission(self, user: User, required_role: UserRole) -> bool:
        """التحقق من صلاحية المستخدم."""
        role_hierarchy = {
            UserRole.GUEST: 0,
            UserRole.USER: 1,
            UserRole.OPERATOR: 2,
            UserRole.ADMIN: 3,
        }
        return role_hierarchy.get(user.role, 0) >= role_hierarchy.get(required_role, 0)

    def to_dict_list(self) -> List[Dict[str, Any]]:
        """قائمة المستخدمين كقواميس."""
        return [u.to_dict() for u in self.users.values()]


# مثيل واحد من مدير المستخدمين
user_manager = UserManager()


def require_role(required_role: UserRole):
    """ديكوريتور للتحقق من صلاحية المستخدم."""
    from functools import wraps
    from fastapi import HTTPException, status

    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # البحث عن بيانات الاعتماد في معاملات الدالة
            credentials = None
            for arg in args:
                if isinstance(arg, HTTPAuthorizationCredentials):
                    credentials = arg
                    break
            if credentials is None:
                for kwarg in kwargs.values():
                    if isinstance(kwarg, HTTPAuthorizationCredentials):
                        credentials = kwarg
                        break

            if credentials is None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="مفتاح API مطلوب",
                )

            user = user_manager.authenticate(credentials.credentials)
            if not user:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="مفتاح API غير صالح",
                )
            if not user.is_active:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="المستخدم معطل",
                )
            if not user_manager.has_permission(user, required_role):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="لا تملك صلاحية للوصول إلى هذه النقطة",
                )

            # إضافة المستخدم إلى معاملات الدالة للاستخدام لاحقًا
            kwargs["current_user"] = user
            return await func(*args, **kwargs)

        return wrapper
    return decorator


__all__ = [
    "UserRole",
    "User",
    "UserManager",
    "user_manager",
    "require_role",
    "_now",
]
