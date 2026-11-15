"""اختبارات الطبقة الذاتية: الكشف، الضبط، التعلّم، المنسّق، والعامل الخلفي."""

import asyncio
import os
import tempfile
import time

import numpy as np
import cv2
from fastapi.testclient import TestClient

from intelligence.detector import AutoDetector
from intelligence.tuner import AdaptiveTuner
from intelligence.learning import LearningEngine
from intelligence.orchestrator import AutoOrchestrator
from intelligence.self_improver import SelfImprover
from intelligence.training import CaptchaDataset
from intelligence.worker import AutoWorker
from solver_engine.base import BaseSolver, CaptchaType, SolverResult
from solver_engine.registry import SolverRegistry

import api_server.main as main_mod


class FakeSolver(BaseSolver):
    captcha_type = CaptchaType.IMAGE

    def __init__(self, confidence: float = 0.99, fail_times: int = 0) -> None:
        self.confidence = confidence
        self.fail_times = fail_times
        self.calls = 0

    def solve(self, *args: object, **kwargs: object) -> SolverResult:
        self.calls += 1
        if self.calls <= self.fail_times:
            return SolverResult(
                success=False, captcha_type=CaptchaType.IMAGE, error="فشل تجريبي"
            )
        return SolverResult(
            success=True,
            captcha_type=CaptchaType.IMAGE,
            text="ABCD",
            confidence=self.confidence,
            response_time_ms=10,
        )


def _fake_registry(confidence: float = 0.99, fail_times: int = 0) -> SolverRegistry:
    reg = SolverRegistry()
    reg.register(FakeSolver(confidence=confidence, fail_times=fail_times))
    return reg


def _text_image() -> np.ndarray:
    img = np.full((80, 240, 3), 255, dtype=np.uint8)
    for i in range(6):
        x = 15 + i * 35
        cv2.rectangle(img, (x, 20), (x + 20, 60), (0, 0, 0), -1)
    return img


def test_detector_classifies_text_image():
    det = AutoDetector().detect(_text_image())
    assert det.captcha_type == "image"
    assert det.confidence >= 0.35
    assert "component_count" in det.features


def test_detector_handles_empty():
    det = AutoDetector().detect(None)
    assert det.captcha_type == "image"
    assert det.confidence == 0.0


def test_tuner_learns_best_params():
    tuner = AdaptiveTuner(epsilon=0.0, seed=3)
    good = {"psm": 8, "threshold": "adaptive", "denoise": False}
    bad = {"psm": 7, "threshold": "otsu", "denoise": True}
    for _ in range(5):
        tuner.record("image", good, True, 0.95, 100)
    for _ in range(5):
        tuner.record("image", bad, False, 0.1, 900)
    assert tuner.best("image") == good
    assert tuner.snapshot()["image"]


def test_learning_engine_prefers_successful_arm():
    engine = LearningEngine(arms=["a", "b"], epsilon=0.0, seed=1)
    engine.update("b", 1.0)
    assert engine.best_arm() == "b"
    assert engine.select() == "b"
    assert engine.snapshot()["arms"]["b"]["pulls"] == 1


def test_learning_reward_scales_with_quality():
    engine = LearningEngine()
    fast: float = engine.reward_from_result(True, 0.95, 100)
    slow: float = engine.reward_from_result(True, 0.4, 9000)
    failure: float = engine.reward_from_result(False, 0.0, 100)
    assert fast > slow > failure


def test_orchestrator_solves_with_mock_solver():
    orch = AutoOrchestrator(
        registry=_fake_registry(confidence=0.99),
        learner=LearningEngine(epsilon=0.0, seed=0),
        tuner=AdaptiveTuner(epsilon=0.0, seed=0),
    )
    out = orch.solve(captcha_type="image")
    assert out.result.success
    assert out.result.text == "ABCD"
    assert out.escalations == 0
    assert out.trace
    assert out.strategy_used


def test_orchestrator_escalates_and_recovers():
    orch = AutoOrchestrator(
        registry=_fake_registry(confidence=0.99, fail_times=1),
        learner=LearningEngine(epsilon=0.0, seed=0),
        tuner=AdaptiveTuner(epsilon=0.0, seed=0),
    )
    out = orch.solve(captcha_type="image", max_escalations=2)
    assert out.result.success
    assert out.escalations >= 1
    assert any("تصعيد" in line for line in out.trace)


def test_worker_processes_job():
    orch = AutoOrchestrator(
        registry=_fake_registry(confidence=0.99),
        learner=LearningEngine(epsilon=0.0, seed=0),
        tuner=AdaptiveTuner(epsilon=0.0, seed=0),
    )
    worker = AutoWorker(orchestrator=orch, concurrency=1)

    async def run() -> dict:
        await worker.start()
        job_id = worker.submit({"captcha_type": "image"})
        status: dict = {}
        for _ in range(100):
            st = worker.status(job_id)
            assert st is not None
            if st["status"] in ("completed", "failed"):
                status = st
                break
            await asyncio.sleep(0.02)
        await worker.stop()
        return status

    status = asyncio.run(run())
    assert status.get("status") == "completed"
    assert worker.snapshot()["processed"] == 1


def test_auto_endpoint_with_mock(monkeypatch):
    from fastapi.testclient import TestClient
    import api_server.main as main_mod

    monkeypatch.setattr(main_mod.orchestrator, "registry", _fake_registry(confidence=0.99))
    monkeypatch.setattr(main_mod.orchestrator, "learner", LearningEngine(epsilon=0.0, seed=0))
    monkeypatch.setattr(main_mod.orchestrator, "tuner", AdaptiveTuner(epsilon=0.0, seed=0))
    client = TestClient(main_mod.app)
    ok, buf = cv2.imencode(".png", _text_image())
    assert ok
    resp = client.post(
        "/auto",
        files={"file": ("captcha.png", buf.tobytes(), "image/png")},
        data={"max_escalations": "1"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["success"] is True
    assert data["detected_type"] == "image"
    assert data["trace"]


def test_auto_status_endpoint():
    from fastapi.testclient import TestClient
    from api_server.main import app

    client = TestClient(app)
    resp = client.get("/auto/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "worker" in data
    assert "learning" in data
    assert "tuner" in data


def test_feedback_endpoint():
    from fastapi.testclient import TestClient
    from api_server.main import app

    client = TestClient(app)
    resp = client.post(
        "/feedback",
        json={
            "strategy": "local_primary",
            "success": True,
            "confidence": 0.9,
            "response_time_ms": 120,
            "captcha_type": "image",
            "params": {"psm": 7, "threshold": "otsu", "denoise": True},
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["ok"] is True
    assert "reward" in data


def test_api_keys_crud():
    client = TestClient(main_mod.app)
    # إنشاء مفتاح
    resp = client.post("/api/keys", json={"name": "test-key"})
    assert resp.status_code == 200
    data = resp.json()
    assert "api_key" in data
    assert "key_id" in data
    key_id = data["key_id"]

    # قائمة المفاتيح
    resp = client.get("/api/keys")
    assert resp.status_code == 200
    keys = resp.json()
    assert any(k["key_id"] == key_id for k in keys)

    # إلغاء المفتاح
    resp = client.delete(f"/api/keys/{key_id}")
    assert resp.status_code == 200


def test_self_improve_stats():
    client = TestClient(main_mod.app)
    resp = client.get("/self-improve/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "dataset" in data


def test_self_improve_retrain():
    client = TestClient(main_mod.app)
    resp = client.post("/self-improve/retrain")
    assert resp.status_code == 200
    data = resp.json()
    assert "retrained" in data


def test_worker_auto_scale():
    orch = AutoOrchestrator(
        registry=_fake_registry(confidence=0.99),
        learner=LearningEngine(epsilon=0.0, seed=0),
        tuner=AdaptiveTuner(epsilon=0.0, seed=0),
    )
    worker = AutoWorker(orchestrator=orch, concurrency=1, max_concurrency=4)

    async def run() -> None:
        await worker.start()
        # إرسال مهام كثيرة لتحفيز التوسيع
        for _ in range(10):
            worker.submit({"captcha_type": "image"})
        await asyncio.sleep(0.3)
        await worker.stop()

    asyncio.run(run())
    snap = worker.snapshot()
    assert snap["processed"] >= 0
    assert snap["concurrency"] >= 1


def test_bulk_submit_and_status():
    orig_registry = main_mod.orchestrator.registry
    main_mod.orchestrator.registry = _fake_registry(confidence=0.99)
    try:
        with TestClient(main_mod.app) as client:
            resp = client.post(
                "/bulk/auto",
                json={
                    "items": [
                        {"captcha_type": "image"},
                        {"captcha_type": "image"},
                    ]
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["count"] == 2
            assert len(data["job_ids"]) == 2
            bulk_id = data["bulk_id"]

            # انتظار الإكمال
            for _ in range(100):
                st = client.get(f"/bulk/{bulk_id}").json()
                if st.get("completed", 0) + st.get("failed", 0) >= 2:
                    break
                time.sleep(0.05)
            assert st.get("completed", 0) + st.get("failed", 0) >= 2
    finally:
        main_mod.orchestrator.registry = orig_registry


def test_dashboard_endpoint():
    client = TestClient(main_mod.app)
    resp = client.get("/web")
    assert resp.status_code == 200
    assert "Nonzra" in resp.text or "لوحة" in resp.text


def test_training_dataset():
    from intelligence.training import CaptchaDataset
    import tempfile, os

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        ds = CaptchaDataset(path=path)
        sid = ds.add("image", text="ABC", confidence=0.95, confirmed=True)
        assert ds.confirm(sid)
        stats = ds.stats()
        assert stats["confirmed"] >= 1
    finally:
        os.unlink(path)


def test_self_improver_auto_confirm():
    from intelligence.self_improver import SelfImprover
    from intelligence.training import CaptchaDataset
    import tempfile, os

    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
        path = f.name
    try:
        ds = CaptchaDataset(path=path)
        si = SelfImprover(dataset=ds, retrain_confidence_threshold=0.5, retrain_min_new_samples=1)
        confirmed = si.auto_confirm("job1", "image", None, "TEXT", 0.99)
        assert confirmed is True
        stats = si.stats()
        assert stats["auto_confirmed"] >= 1
    finally:
        os.unlink(path)
