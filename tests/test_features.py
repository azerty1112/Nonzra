"""اختبارات الميزات الجديدة: الحساب الآمن، المولّد الصناعي، والقدرات."""

import base64

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from solver_engine.base import CaptchaType
from solver_engine.math import (
    evaluate_expression,
    format_number,
    normalize_expression,
)
from solver_engine.registry import SolverRegistry, get_capabilities, registry
from solver_engine.synthetic import DEFAULT_CHARSET, encode_png, generate_batch, generate_sample
from solver_engine.text import NumericSolver, TextSolver

# ---------------------- الحساب الآمن ----------------------


def test_evaluate_simple_operations():
    assert evaluate_expression("5+3")[:2] == (True, 8.0)
    assert evaluate_expression("10-4")[:2] == (True, 6.0)
    assert evaluate_expression("7*2")[:2] == (True, 14.0)
    assert evaluate_expression("9/3")[:2] == (True, 3.0)
    assert evaluate_expression("2+3*4")[:2] == (True, 14.0)


def test_evaluate_rejects_code_execution():
    for payload in (
        "__import__('os').system('id')",
        "open('/etc/passwd').read()",
        "2**999",
        "1/0",
        "lambda: 1",
    ):
        ok, value, error = evaluate_expression(payload)
        assert ok is False
        assert value is None
        assert error


def test_normalize_expression_handles_ocr_noise():
    assert normalize_expression("5 × 3 =") == "5 * 3"
    assert normalize_expression("1O - 4") == "10 - 4"
    assert normalize_expression("9 ÷ 3 ؟") == "9 / 3"
    assert normalize_expression("") == ""


def test_format_number():
    assert format_number(8.0) == "8"
    assert format_number(2.5) == "2.5"
    assert format_number(1 / 3) in ("0.33", "0.3")


# ---------------------- المولّد الصناعي ----------------------


def test_generate_sample_is_deterministic_with_seed():
    img1, text1 = generate_sample(length=5, seed=42)
    img2, text2 = generate_sample(length=5, seed=42)
    assert text1 == text2
    assert len(text1) == 5
    assert img1.shape == img2.shape
    assert all(ch in DEFAULT_CHARSET for ch in text1)
    assert np.array_equal(img1, img2)


def test_generate_sample_respects_custom_charset():
    _, text = generate_sample(length=6, charset="01", seed=1)
    assert set(text) <= {"0", "1"}


def test_generate_batch_png_roundtrip():
    items = generate_batch(count=3, length=4, seed=10)
    assert len(items) == 3
    raw = base64.b64decode(items[0]["png_base64"])
    decoded = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape[:2] == (60, 160)


def test_encode_png_returns_png_bytes():
    image, _ = generate_sample(seed=3)
    data = encode_png(image)
    assert data.startswith(b"\x89PNG")


# ---------------------- القدرات والمحرّكات ----------------------


def test_capabilities_lists_new_solvers():
    caps = get_capabilities()
    for expected in ("image", "hcaptcha", "slider", "rotate", "math", "text"):
        assert expected in caps["supported_types"]
        assert caps["types"][expected]["count"] >= 1
    assert caps["total_solvers"] >= 10


def test_registry_includes_slider_rotate_math_text():
    reg = SolverRegistry()
    from solver_engine import (
        DragSolver,
        ImageCaptchaSolver,
        MathSolver,
        PointSolver,
        RotateSolver,
        SliderSolver,
        TextSolver,
    )

    for solver in (
        ImageCaptchaSolver(),
        DragSolver(),
        PointSolver(),
        SliderSolver(),
        RotateSolver(),
        MathSolver(),
        TextSolver(),
    ):
        reg.register(solver)

    assert reg.get_solvers(CaptchaType.SLIDER)
    assert reg.get_solvers(CaptchaType.ROTATE)
    assert reg.get_solvers(CaptchaType.MATH)
    assert reg.get_solvers(CaptchaType.TEXT)
    # المثيل العام المسجّل في السيرفر يحتوي نفس الأنواع
    assert registry.get_solvers(CaptchaType.SLIDER)
    assert registry.get_solvers(CaptchaType.MATH)


def test_text_solver_uses_whitelist():
    solver = TextSolver()
    assert solver.captcha_type == CaptchaType.TEXT
    assert solver.config.psm == 8
    assert "A" in (solver.config.whitelist or "")


def test_numeric_solver_whitelist_is_digits():
    solver = NumericSolver()
    assert solver.config.whitelist == "0123456789"


# ---------------------- نقاط النهاية الجديدة ----------------------


@pytest.fixture()
def client():
    from api_server.main import app

    return TestClient(app)


def test_capabilities_endpoint(client):
    resp = client.get("/capabilities")
    assert resp.status_code == 200
    data = resp.json()
    assert "supported_types" in data
    assert "math" in data["supported_types"]
    assert data["version"]


def test_math_evaluate_endpoint(client):
    resp = client.post("/math/evaluate", json={"expression": "12 × 4"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["answer"] == "48"
    assert data["expression"] == "12 * 4"


def test_math_evaluate_endpoint_rejects_bad_expression(client):
    resp = client.post("/math/evaluate", json={"expression": "abc"})
    assert resp.status_code == 200
    assert resp.json()["success"] is False


def test_synthetic_batch_endpoint(client):
    resp = client.post(
        "/synthetic/batch",
        json={"count": 2, "length": 4, "seed": 5, "with_png": True},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert len(data["items"]) == 2
    assert all(len(item["text"]) == 4 for item in data["items"])


def test_synthetic_sample_endpoint_returns_png(client):
    resp = client.get("/synthetic/sample?length=4&seed=1")
    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/png"
    assert resp.content.startswith(b"\x89PNG")


def test_batch_solve_endpoint_handles_invalid_payloads(client):
    resp = client.post(
        "/batch/solve",
        json={
            "items": [
                {"image_b64": "not-valid-base64!!", "captcha_type": "image"},
                {"image_b64": base64.b64encode(b"x").decode(), "captcha_type": "nope"},
            ]
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 2
    assert data["succeeded"] == 0
    assert all(not r["success"] for r in data["results"])


def test_batch_solve_with_generated_image(client):
    image, _ = generate_sample(seed=8)
    b64 = base64.b64encode(encode_png(image)).decode()
    resp = client.post(
        "/batch/solve",
        json={"items": [{"image_b64": b64, "captcha_type": "image"}], "captcha_type": "image"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] == 1
    assert data["results"][0]["captcha_type"] == "image"


def test_health_reports_version_and_worker(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"]
    assert "worker" in data


def test_root_redirects_to_dashboard(client):
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/dashboard"


def test_metrics_is_prometheus_text(client):
    resp = client.get("/metrics")
    assert resp.status_code in (200, 503)
    if resp.status_code == 200:
        assert "text/plain" in resp.headers["content-type"]
        assert b"# HELP" in resp.content or b"nonecap" in resp.content


# ---------------------- أمان مفاتيح API (قاعدة البيانات المشفّرة) ----------------------


def test_encryption_key_is_stable_across_calls():
    from solver_engine.db import decrypt_value, encrypt_value

    cipher = encrypt_value("stable-secret")
    assert cipher != "stable-secret"
    assert decrypt_value(cipher) == "stable-secret"


def test_api_key_survives_new_database_instance(tmp_path):
    from solver_engine.db import Database

    db_url = f"sqlite:///{tmp_path / 'keys.db'}"
    db1 = Database(db_url)
    db1.add_api_key("key-1", "raw-secret", "test")
    # مثيل جديد يحاكي إعادة تشغيل السيرفر
    db2 = Database(db_url)
    info = db2.verify_api_key("raw-secret")
    assert info is not None
    assert info["key_id"] == "key-1"
    assert db2.verify_api_key("wrong") is None
    assert db2.deactivate_api_key("key-1") is True
    assert db2.verify_api_key("raw-secret") is None
