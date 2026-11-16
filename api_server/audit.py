"""سجل التدقيق الشامل (Audit Logging).

يسجل جميع الإجراءات المهمة في النظام للمراقبة والأمان والتحقيق.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
import json
import os
import uuid


@dataclass
class AuditEvent:
    """حدث تدقيق واحد."""
    event_id: str
    timestamp: str
    user_id: Optional[str]
    username: Optional[str]
    action: str
    resource: str
    resource_id: Optional[str]
    details: Dict[str, Any]
    ip_address: Optional[str]
    user_agent: Optional[str]
    success: bool
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_id": self.event_id,
            "timestamp": self.timestamp,
            "user_id": self.user_id,
            "username": self.username,
            "action": self.action,
            "resource": self.resource,
            "resource_id": self.resource_id,
            "details": self.details,
            "ip_address": self.ip_address,
            "user_agent": self.user_agent,
            "success": self.success,
            "error_message": self.error_message,
        }


class AuditLogger:
    """مدير سجل التدقيق."""

    def __init__(self, log_file: Optional[str] = None) -> None:
        self.log_file = log_file or "audit.log"
        self.events: List[AuditEvent] = []
        self._load_existing()

    def _load_existing(self) -> None:
        """تحميل الأحداث الموجودة من الملف."""
        if not os.path.exists(self.log_file):
            return
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        event = AuditEvent(**data)
                        self.events.append(event)
                    except Exception:  # noqa: BLE001
                        continue
        except Exception:  # noqa: BLE001
            pass

    def log(
        self,
        action: str,
        resource: str,
        user_id: Optional[str] = None,
        username: Optional[str] = None,
        resource_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        success: bool = True,
        error_message: Optional[str] = None,
    ) -> AuditEvent:
        """تسجيل حدث تدقيق جديد."""
        event = AuditEvent(
            event_id=str(uuid.uuid4()),
            timestamp=_now(),
            user_id=user_id,
            username=username,
            action=action,
            resource=resource,
            resource_id=resource_id,
            details=details or {},
            ip_address=ip_address,
            user_agent=user_agent,
            success=success,
            error_message=error_message,
        )

        self.events.append(event)

        # حفظ في الملف
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        except Exception:  # noqa: BLE001
            pass

        return event

    def get_events(
        self,
        user_id: Optional[str] = None,
        action: Optional[str] = None,
        resource: Optional[str] = None,
        success: Optional[bool] = None,
        limit: int = 100,
    ) -> List[AuditEvent]:
        """الحصول على الأحداث مع التصفية."""
        events = self.events
        if user_id:
            events = [e for e in events if e.user_id == user_id]
        if action:
            events = [e for e in events if e.action == action]
        if resource:
            events = [e for e in events if e.resource == resource]
        if success is not None:
            events = [e for e in events if e.success == success]
        return events[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """إرجاع إحصائيات سجل التدقيق."""
        total = len(self.events)
        successful = sum(1 for e in self.events if e.success)
        failed = total - successful

        actions: Dict[str, int] = {}
        for e in self.events:
            actions[e.action] = actions.get(e.action, 0) + 1

        resources: Dict[str, int] = {}
        for e in self.events:
            resources[e.resource] = resources.get(e.resource, 0) + 1

        users: Dict[str, int] = {}
        for e in self.events:
            if e.user_id:
                users[e.user_id] = users.get(e.user_id, 0) + 1

        return {
            "total_events": total,
            "successful_events": successful,
            "failed_events": failed,
            "actions": actions,
            "resources": resources,
            "active_users": len(users),
        }


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


# مثيل واحد من مدقق التدقيق
audit_logger = AuditLogger()


def audit_log(
    action: str,
    resource: str,
    user_id: Optional[str] = None,
    username: Optional[str] = None,
    resource_id: Optional[str] = None,
    details: Optional[Dict[str, Any]] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    success: bool = True,
    error_message: Optional[str] = None,
) -> AuditEvent:
    """دالة مساعدة لتسجيل حدث تدقيق."""
    return audit_logger.log(
        action=action,
        resource=resource,
        user_id=user_id,
        username=username,
        resource_id=resource_id,
        details=details,
        ip_address=ip_address,
        user_agent=user_agent,
        success=success,
        error_message=error_message,
    )


__all__ = [
    "AuditEvent",
    "AuditLogger",
    "audit_logger",
    "audit_log",
]
