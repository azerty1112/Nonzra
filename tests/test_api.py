"""اختبارات تكامل لسيرفر NoneCap Clone (تتطلب تشغيل السيرفر أو TestClient)."""

from fastapi.testclient import TestClient
from api_server.main import app


def test_health():
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"


def test_metrics():
    client = TestClient(app)
    resp = client.get("/metrics")
    assert resp.status_code == 200


def test_solve_image_no_file():
    client = TestClient(app)
    resp = client.post("/solve/image")
    assert resp.status_code in (400, 422)


def test_stats():
    client = TestClient(app)
    resp = client.get("/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert "total" in data
    assert "success_rate" in data
