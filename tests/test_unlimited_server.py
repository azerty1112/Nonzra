"""اختبارات «الخادم المجاني بلا حدود»: السياسة، غياب 429، ونقاط النهاية العامة."""

import importlib
import os

import pytest
from fastapi.testclient import TestClient


def _reload_main_with_env(monkeypatch, **env):
    """يعيد تحميل وحدة السيرفر بعد ضبط متغيرات البيئة (السياسة تُقرأ عند الإقلاع)."""
    for key, value in env.items():
        monkeypatch.setenv(key, str(value))
    import api_server.main as main_mod
    import api_server.policy as policy_mod

    importlib.reload(policy_mod)
    importlib.reload(main_mod)
    return main_mod


@pytest.fixture()
def default_client():
    from api_server.main import app

    return TestClient(app)


# ---------------------- السياسة ----------------------


def test_policy_defaults_to_unlimited():
    from api_server.policy import load_policy

    for key in (
        "NONECAP_UNLIMITED",
        "NONECAP_REQUIRE_API_KEY",
        "NONECAP_RATE_LIMIT_PER_MINUTE",
        "NONECAP_KEY_RATE_LIMIT_PER_MINUTE",
        "NONECAP_IP_BLOCK_SECONDS",
    ):
        os.environ.pop(key, None)
    policy = load_policy()
    assert policy.unlimited is True
    assert policy.require_api_key is False
    assert policy.rate_limited is False
    assert policy.per_ip_per_minute == 0
    assert policy.to_dict()["mode"] == "unlimited"


def test_policy_can_be_guarded(monkeypatch):
    from api_server.policy import load_policy

    monkeypatch.setenv("NONECAP_UNLIMITED", "0")
    monkeypatch.setenv("NONECAP_RATE_LIMIT_PER_MINUTE", "45")
    monkeypatch.setenv("NONECAP_REQUIRE_API_KEY", "1")
    policy = load_policy()
    assert policy.unlimited is False
    assert policy.rate_limited is True
    assert policy.per_ip_per_minute == 45
    assert policy.require_api_key is True
    assert policy.to_dict()["mode"] == "guarded"


def test_policy_unlimited_overrides_explicit_limits(monkeypatch):
    from api_server.policy import load_policy

    monkeypatch.setenv("NONECAP_UNLIMITED", "1")
    monkeypatch.setenv("NONECAP_RATE_LIMIT_PER_MINUTE", "10")
    monkeypatch.setenv("NONECAP_REQUIRE_API_KEY", "1")
    policy = load_policy()
    assert policy.per_ip_per_minute == 0
    assert policy.require_api_key is False


# ---------------------- السيرفر ----------------------


def test_status_reports_unlimited_mode(default_client):
    resp = default_client.get("/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["mode"] == "unlimited"
    assert data["free"] is True
    assert data["requires_api_key"] is False
    assert data["policy"]["per_ip_per_minute"] == 0
    assert data["supported_types"]
    assert "load" in data and "storage" in data


def test_no_rate_limit_after_many_requests(default_client):
    statuses = {default_client.get("/health").status_code for _ in range(140)}
    assert statuses == {200}


def test_health_ok_and_versioned(default_client):
    data = default_client.get("/health").json()
    assert data["status"] == "ok"
    assert data["version"]


def test_landing_page_served_at_root(default_client):
    resp = default_client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    body = resp.text
    assert "Nonzra" in body
    assert "مجاني" in body


def test_landing_assets_exist(default_client):
    for asset in ("logo.svg", "logo-mark.svg", "favicon.svg", "architecture.svg"):
        resp = default_client.get(f"/static/img/{asset}")
        assert resp.status_code == 200, asset
        assert "svg" in resp.headers["content-type"]


def test_solve_works_without_any_api_key(default_client):
    import base64

    import cv2
    import numpy as np

    image = np.full((60, 200, 3), 255, np.uint8)
    cv2.putText(image, "AB12", (12, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (0, 0, 0), 3)
    ok, buf = cv2.imencode(".png", image)
    assert ok
    resp = default_client.post(
        "/solve/image", json={"image_b64": base64.b64encode(buf.tobytes()).decode()}
    )
    assert resp.status_code == 200
    assert resp.json()["status"] in ("completed", "failed")


def test_dashboard_and_docs_available(default_client):
    assert default_client.get("/dashboard").status_code == 200
    assert default_client.get("/docs").status_code == 200
    assert default_client.get("/openapi.json").status_code == 200


def test_guarded_mode_rejects_missing_key(monkeypatch):
    main_mod = _reload_main_with_env(
        monkeypatch, NONECAP_UNLIMITED="0", NONECAP_REQUIRE_API_KEY="1"
    )
    client = TestClient(main_mod.app)
    resp = client.get("/stats")
    assert resp.status_code == 401

    # والوضع المحدود يفرض حدًا في المعدل → 429 بعد تجاوز الحد
    monkeypatch.setenv("NONECAP_RATE_LIMIT_PER_MINUTE", "5")
    main_mod = _reload_main_with_env(
        monkeypatch,
        NONECAP_UNLIMITED="0",
        NONECAP_REQUIRE_API_KEY="0",
        NONECAP_RATE_LIMIT_PER_MINUTE="5",
        NONECAP_IP_BLOCK_SECONDS="0",
    )
    client = TestClient(main_mod.app)
    codes = [client.get("/health").status_code for _ in range(12)]
    assert 429 in codes

    # استعادة الوضع الافتراضي بحيث لا تتأثر الاختبارات التالية
    _reload_main_with_env(
        monkeypatch,
        NONECAP_UNLIMITED="1",
        NONECAP_REQUIRE_API_KEY="0",
        NONECAP_RATE_LIMIT_PER_MINUTE="0",
        NONECAP_IP_BLOCK_SECONDS="0",
    )


def test_memory_sweep_drops_expired_jobs(monkeypatch):
    main_mod = _reload_main_with_env(monkeypatch, NONECAP_JOB_TTL_SECONDS="60")
    from datetime import datetime, timedelta, timezone

    old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    fresh = datetime.now(timezone.utc).isoformat()
    main_mod.JOBS["old"] = {"status": "completed", "created_at": old, "finished_at": old}
    main_mod.JOBS["fresh"] = {
        "status": "completed",
        "created_at": fresh,
        "finished_at": fresh,
    }
    main_mod._sweep_memory()
    assert "old" not in main_mod.JOBS
    assert "fresh" in main_mod.JOBS
    main_mod.JOBS.clear()
    _reload_main_with_env(monkeypatch, NONECAP_UNLIMITED="1")


def test_batch_endpoint_accepts_more_than_fifty(default_client):
    resp = default_client.post(
        "/batch/solve",
        json={"items": [{"image_b64": "x"} for _ in range(60)], "captcha_type": "image"},
    )
    assert resp.status_code == 200
    assert resp.json()["count"] == 60
