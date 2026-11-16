"""نظام النسخ الاحتياطي والاستعادة التلقائي."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from datetime import datetime, timezone
import json
import os
import shutil
import tarfile
import uuid
import zipfile


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class BackupInfo:
    """معلومات نسخة احتياطية."""
    backup_id: str
    timestamp: str
    backup_type: str  # full, incremental
    file_path: str
    file_size: int
    includes_db: bool
    includes_config: bool
    includes_intelligence: bool
    status: str  # creating, completed, failed
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "backup_id": self.backup_id,
            "timestamp": self.timestamp,
            "backup_type": self.backup_type,
            "file_path": self.file_path,
            "file_size": self.file_size,
            "includes_db": self.includes_db,
            "includes_config": self.includes_config,
            "includes_intelligence": self.includes_intelligence,
            "status": self.status,
            "error": self.error,
        }


class BackupManager:
    """مدير النسخ الاحتياطي والاستعادة."""

    def __init__(self, backup_dir: str = "backups") -> None:
        self.backup_dir = backup_dir
        os.makedirs(backup_dir, exist_ok=True)
        self.backups: List[BackupInfo] = []
        self._load_existing()

    def _load_existing(self) -> None:
        """تحميل النسخ الاحتياطية الموجودة."""
        if not os.path.exists(self.backup_dir):
            return
        for filename in os.listdir(self.backup_dir):
            if filename.endswith(".tar.gz") or filename.endswith(".zip"):
                filepath = os.path.join(self.backup_dir, filename)
                file_size = os.path.getsize(filepath)
                backup_id = filename.replace(".tar.gz", "").replace(".zip", "")
                self.backups.append(BackupInfo(
                    backup_id=backup_id,
                    timestamp="",  # سيتم استرداده من اسم الملف أو المحتوى
                    backup_type="full",
                    file_path=filepath,
                    file_size=file_size,
                    includes_db=True,
                    includes_config=True,
                    includes_intelligence=True,
                    status="completed",
                ))

    def create_backup(
        self,
        include_db: bool = True,
        include_config: bool = True,
        include_intelligence: bool = True,
        backup_type: str = "full",
    ) -> BackupInfo:
        """إنشاء نسخة احتياطية."""
        backup_id = str(uuid.uuid4())[:8]
        timestamp = _now()
        backup_filename = f"nonecap_backup_{backup_id}_{timestamp.replace(':', '-').replace(' ', '_')}.tar.gz"
        backup_path = os.path.join(self.backup_dir, backup_filename)

        backup_info = BackupInfo(
            backup_id=backup_id,
            timestamp=timestamp,
            backup_type=backup_type,
            file_path=backup_path,
            file_size=0,
            includes_db=include_db,
            includes_config=include_config,
            includes_intelligence=include_intelligence,
            status="creating",
        )

        try:
            with tarfile.open(backup_path, "w:gz") as tar:
                # نسخ قاعدة البيانات
                if include_db and os.path.exists("nonecap_clone.db"):
                    tar.add("nonecap_clone.db", arcname="nonecap_clone.db")

                # نسخ ملفات التكوين
                if include_config:
                    for config_file in ["pyproject.toml", "Dockerfile", "docker-compose.yml", ".env"]:
                        if os.path.exists(config_file):
                            tar.add(config_file, arcname=config_file)

                # نسخ ملفات الذكاء الاصطناعي
                if include_intelligence:
                    for intel_file in ["knowledge_base.json", "training_data.json", "intelligence/knowledge_base.json", "intelligence/training_data.json"]:
                        if os.path.exists(intel_file):
                            tar.add(intel_file, arcname=intel_file)

                # نسخ ملفات الإضافة
                if os.path.exists("extension"):
                    tar.add("extension", arcname="extension")

            file_size = os.path.getsize(backup_path)
            backup_info.file_size = file_size
            backup_info.status = "completed"

        except Exception as exc:  # noqa: BLE001
            backup_info.status = "failed"
            backup_info.error = str(exc)

        self.backups.append(backup_info)
        return backup_info

    def list_backups(self) -> List[BackupInfo]:
        """قائمة جميع النسخ الاحتياطية."""
        return sorted(self.backups, key=lambda b: b.timestamp, reverse=True)

    def delete_backup(self, backup_id: str) -> bool:
        """حذف نسخة احتياطية."""
        for i, backup in enumerate(self.backups):
            if backup.backup_id == backup_id:
                if os.path.exists(backup.file_path):
                    os.remove(backup.file_path)
                del self.backups[i]
                return True
        return False

    def restore_backup(self, backup_id: str) -> Dict[str, Any]:
        """استعادة نسخة احتياطية."""
        for backup in self.backups:
            if backup.backup_id == backup_id:
                if not os.path.exists(backup.file_path):
                    return {"success": False, "error": "ملف النسخة الاحتياطية غير موجود"}
                try:
                    with tarfile.open(backup.file_path, "r:gz") as tar:
                        tar.extractall()
                    return {"success": True, "message": "تم الاستعادة بنجاح"}
                except Exception as exc:  # noqa: BLE001
                    return {"success": False, "error": str(exc)}
        return {"success": False, "error": "النسخة الاحتياطية غير موجودة"}


# مثيل واحد من مدير النسخ الاحتياطي
backup_manager = BackupManager()


__all__ = [
    "BackupInfo",
    "BackupManager",
    "backup_manager",
]
