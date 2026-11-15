"""قاعدة بيانات SQLite لتخزين المحاولات، الإحصائيات، ومفاتيح API (اختيارية عند sqlalchemy)."""

from datetime import datetime, timezone
from typing import Optional, Dict, Any

try:
    from sqlalchemy import (
        create_engine,
        Column,
        Integer,
        String,
        Float,
        Boolean,
        DateTime,
        Text,
        func,
    )
    from sqlalchemy.orm import declarative_base, sessionmaker, Session

    Base = declarative_base()
    _SA_AVAILABLE = True
except Exception:  # noqa: BLE001
    _SA_AVAILABLE = False

    class Base:  # type: ignore[no-redef]
        pass

    class Session:  # type: ignore[no-redef]
        pass

if _SA_AVAILABLE:

    class SolveAttempt(Base):  # type: ignore[valid-type, misc]
        __tablename__ = "solve_attempts"

        id = Column(Integer, primary_key=True, index=True)
        captcha_type = Column(String, index=True, nullable=False)
        success = Column(Boolean, default=False, nullable=False)
        confidence = Column(Float, default=0.0, nullable=False)
        response_time_ms = Column(Integer, default=0, nullable=False)
        error = Column(Text, nullable=True)
        created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)

    class APIKey(Base):  # type: ignore[valid-type, misc]
        __tablename__ = "api_keys"

        id = Column(Integer, primary_key=True, index=True)
        key_hash = Column(String, unique=True, nullable=False, index=True)
        name = Column(String, nullable=True)
        is_active = Column(Boolean, default=True, nullable=False)
        created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class Database:
    def __init__(self, db_url: str = "sqlite:///nonecap_clone.db") -> None:
        self.db_url = db_url
        self._available = _SA_AVAILABLE
        if self._available:
            self.engine = create_engine(db_url, connect_args={"check_same_thread": False})
            Base.metadata.create_all(self.engine)
            self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False)  # type: ignore[assignment]

    def session(self) -> Any:
        if not self._available:
            return _DummySession()
        return self.SessionLocal()

    def record_attempt(
        self,
        captcha_type: str,
        success: bool,
        confidence: float = 0.0,
        response_time_ms: int = 0,
        error: Optional[str] = None,
    ) -> None:
        if not self._available:
            return
        db = self.session()
        try:
            attempt = SolveAttempt(  # type: ignore[name-defined]
                captcha_type=captcha_type,
                success=success,
                confidence=confidence,
                response_time_ms=response_time_ms,
                error=error,
            )
            db.add(attempt)
            db.commit()
        finally:
            db.close()

    def stats(self) -> Dict[str, Any]:
        if not self._available:
            return {
                "total": 0,
                "success": 0,
                "success_rate": 0.0,
                "avg_response_time_ms": 0.0,
                "by_type": {},
                "note": "sqlalchemy غير متوفر",
            }
        db = self.session()
        try:
            total = db.query(func.count(SolveAttempt.id)).scalar() or 0  # type: ignore[attr-defined]
            success = (
                db.query(func.count(SolveAttempt.id))
                .filter(SolveAttempt.success == True)  # noqa: E712
                .scalar()
                or 0
            )
            avg_time = db.query(func.avg(SolveAttempt.response_time_ms)).scalar() or 0.0
            by_type = (
                db.query(SolveAttempt.captcha_type, func.count(SolveAttempt.id))
                .group_by(SolveAttempt.captcha_type)
                .all()
            )
            return {
                "total": int(total),
                "success": int(success),
                "success_rate": round((success / total * 100) if total else 0.0, 2),
                "avg_response_time_ms": round(float(avg_time), 2),
                "by_type": {str(t): int(c) for t, c in by_type},
            }
        finally:
            db.close()


class _DummySession:
    def add(self, obj: Any) -> None:
        pass

    def commit(self) -> None:
        pass

    def close(self) -> None:
        pass

    def query(self, *args: Any, **kwargs: Any) -> "_DummyQuery":
        return _DummyQuery()


class _DummyQuery:
    def filter(self, *args: Any, **kwargs: Any) -> "_DummyQuery":
        return self

    def group_by(self, *args: Any, **kwargs: Any) -> "_DummyQuery":
        return self

    def scalar(self) -> Any:
        return 0

    def all(self) -> list:
        return []

    def first(self) -> Any:
        return None
