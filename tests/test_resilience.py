"""اختبارات الاحتياطات: مهلة صارمة، قاطع دائرة، وتكرار ذكي بلا تكرار أعمى."""

import threading
import time

import pytest

from solver_engine.resilience import (
    AttemptLog,
    CircuitBreaker,
    TimeoutExceeded,
    breakers_snapshot,
    diversify,
    get_breaker,
    run_with_timeout,
)


# ---------------------- المهلة الصارمة ----------------------


def test_run_with_timeout_returns_value():
    assert run_with_timeout(lambda x: x * 2, 21, timeout=5) == 42


def test_run_with_timeout_raises_on_hang():
    started = time.perf_counter()
    with pytest.raises(TimeoutExceeded):
        run_with_timeout(time.sleep, 5, timeout=0.15, name="sleepy")
    elapsed = time.perf_counter() - started
    # يجب أن يرجع فورًا لا أن ينتظر 5 ثوانٍ
    assert elapsed < 2.0


def test_run_with_timeout_propagates_real_error():
    def boom():
        raise ValueError("خطأ حقيقي")

    with pytest.raises(ValueError):
        run_with_timeout(boom, timeout=2)


def test_run_with_timeout_zero_means_no_limit():
    assert run_with_timeout(lambda: "ok", timeout=0) == "ok"


# ---------------------- قاطع الدائرة ----------------------


def test_breaker_stays_closed_while_healthy():
    breaker = CircuitBreaker("healthy", failure_threshold=3)
    for _ in range(5):
        assert breaker.allow() is True
        breaker.record_success()
    assert breaker.snapshot()["state"] == "closed"


def test_breaker_opens_after_threshold():
    breaker = CircuitBreaker("opens", failure_threshold=2, recovery_seconds=30)
    breaker.record_failure("e1")
    assert breaker.allow() is True  # فشل واحد لا يفتح
    breaker.record_failure("e2")
    assert breaker.allow() is False
    snapshot = breaker.snapshot()
    assert snapshot["state"] == "open"
    assert snapshot["wait_seconds"] > 0
    assert snapshot["last_error"] == "e2"


def test_breaker_half_open_then_closes_on_success():
    breaker = CircuitBreaker("recovers", failure_threshold=1, recovery_seconds=0.05)
    breaker.record_failure("down")
    assert breaker.allow() is False
    time.sleep(0.08)
    assert breaker.allow() is True  # يسمح بمحاولة اختبار
    assert breaker.snapshot()["state"] == "half_open"
    breaker.record_success()
    assert breaker.snapshot()["state"] == "closed"


def test_breaker_reopens_longer_on_half_open_failure():
    breaker = CircuitBreaker("relapse", failure_threshold=1, recovery_seconds=0.05)
    breaker.record_failure("down")
    time.sleep(0.08)
    assert breaker.allow() is True
    breaker.record_failure("still down")
    snapshot = breaker.snapshot()
    assert snapshot["state"] == "open"
    # الفتح الثاني ينتظر أطول (backoff أسّي) بدل دورة سريعة بلا نهاية
    assert snapshot["wait_seconds"] > 0.05


def test_breaker_backoff_is_capped():
    breaker = CircuitBreaker(
        "cap", failure_threshold=1, recovery_seconds=10, backoff_factor=10, max_recovery_seconds=20
    )
    for _ in range(6):
        breaker.record_failure("x")
        time.sleep(0.001)
    assert breaker.snapshot()["wait_seconds"] <= 20.0


def test_breaker_snapshot_does_not_deadlock():
    """`snapshot()` كان يستدعي دالة تقفل نفس القفل ⇒ جمود. هذا اختبار انحدار."""
    breaker = CircuitBreaker("nodeadlock", failure_threshold=1, recovery_seconds=5)
    breaker.record_failure("x")
    done = {}

    def read():
        done["snapshot"] = breaker.snapshot()

    thread = threading.Thread(target=read, daemon=True)
    thread.start()
    thread.join(2.0)
    assert not thread.is_alive(), "snapshot() علّق — جمود في الأقفال"
    assert done["snapshot"]["state"] == "open"


def test_get_breaker_is_shared_and_resettable():
    first = get_breaker("shared-test")
    first.record_failure("x")
    assert get_breaker("shared-test") is first
    assert "shared-test" in breakers_snapshot()
    first.reset()
    assert first.snapshot()["failures"] == 0


# ---------------------- التكرار الذكي ----------------------


def test_diversify_rotates_orders():
    orders = [["a", "b"], ["b", "a"], ["c"]]
    seen = [diversify(orders, attempt) for attempt in range(4)]
    assert seen[0] == ["a", "b"]
    assert seen[1] == ["b", "a"]
    assert seen[2] == ["c"]
    assert seen[3] == seen[0]  # يدور بلا نهاية
    assert diversify(None, 0) is None


def test_attempt_log_serializes_extra_fields():
    log = AttemptLog(2, "ocr", True, "AB12", extra={"confidence": 0.9})
    payload = log.to_dict()
    assert payload["round"] == 2
    assert payload["confidence"] == 0.9
    assert payload["ok"] is True
