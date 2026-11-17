"""اختبارات محرّكي السلايدر والتدوير على صور مصطنعة بمعايرة دقيقة.

تُغطّي المسارات الثلاثة لمحرّك السلايدر (قالب، كشف فجوة، رفض قالب منخفض التفاصيل)
ومسارين للتدوير (قالب دوّار، ومسقط أفقي) مع التحقق من القيم لا مجرد النجاح.
"""

import cv2
import numpy as np
import pytest

from solver_engine.base import CaptchaType
from solver_engine.rotate import RotateSolver
from solver_engine.slider import SliderSolver

GAP_X, GAP_Y, GAP_W, GAP_H = 190, 55, 46, 46


def _png(image: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", image)
    assert ok
    return buf.tobytes()


def _textured_background(seed: int = 11, size=(160, 320)) -> np.ndarray:
    """خلفية ملوّنة مُنسَّجة تشبه صور السلايدر الحقيقية."""
    rng = np.random.default_rng(seed)
    h, w = size
    image = np.full((h, w, 3), 210, np.uint8)
    for _ in range(25):
        center = (int(rng.integers(0, w)), int(rng.integers(0, h)))
        radius = int(rng.integers(8, 30))
        color = tuple(int(c) for c in rng.integers(20, 200, 3))
        cv2.circle(image, center, radius, color, -1)
    return cv2.GaussianBlur(image, (5, 5), 1.2)


def _slider_pair():
    """يعيد (صورة الخلفية مع الفجوة المظللة, صورة القطعة)."""
    background = _textured_background()
    piece = background[GAP_Y : GAP_Y + GAP_H, GAP_X : GAP_X + GAP_W].copy()
    target = background.copy()
    target[GAP_Y : GAP_Y + GAP_H, GAP_X : GAP_X + GAP_W] = (
        piece.astype(np.float32) * 0.45
    ).astype(np.uint8)
    return target, piece


def _rotated_canvas(angle: float):
    canvas = np.full((100, 320, 3), 255, np.uint8)
    cv2.putText(
        canvas, "AB12", (40, 70), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 3, cv2.LINE_AA
    )
    rotation = cv2.getRotationMatrix2D((160, 50), angle, 1.0)
    rotated = cv2.warpAffine(canvas, rotation, (320, 100), borderValue=(255, 255, 255))
    return canvas, rotated


# ---------------------- SliderSolver ----------------------


def test_slider_with_template_returns_gap_center():
    target, piece = _slider_pair()
    result = SliderSolver().solve(image_bytes=_png(target), template_bytes=_png(piece))
    assert result.success is True
    assert result.captcha_type == CaptchaType.SLIDER
    assert result.metadata["method"] == "template"
    expected_x = GAP_X + GAP_W // 2
    assert abs(int(result.text) - expected_x) <= 2
    assert abs(result.metadata["x"] - expected_x) <= 2
    assert result.confidence >= 0.55


def test_slider_detects_gap_without_template():
    image = np.full((150, 300, 3), 200, np.uint8)
    cv2.rectangle(image, (140, 30), (170, 120), (30, 30, 30), -1)
    result = SliderSolver().solve(image_bytes=_png(image))
    assert result.success is True
    assert result.metadata["method"] == "gradient"
    # الحافة اليسرى للفجوة قريبة من 140
    assert abs(int(result.text) - 140) <= 12


def test_slider_rejects_flat_template():
    target, _ = _slider_pair()
    flat = np.full((40, 40, 3), 200, np.uint8)
    result = SliderSolver().solve(image_bytes=_png(target), template_bytes=_png(flat))
    assert result.success is False
    assert result.error
    assert "تباين" in result.error


def test_slider_without_image_fails_cleanly():
    result = SliderSolver().solve()
    assert result.success is False
    assert result.error
    assert result.response_time_ms >= 0


def test_slider_async_matches_sync():
    import asyncio

    target, piece = _slider_pair()
    solver = SliderSolver()
    sync_result = solver.solve(image_bytes=_png(target), template_bytes=_png(piece))
    async_result = asyncio.run(
        solver.solve_async(image_bytes=_png(target), template_bytes=_png(piece))
    )
    assert async_result.success == sync_result.success
    assert async_result.text == sync_result.text


# ---------------------- RotateSolver ----------------------


@pytest.mark.parametrize("angle", [-25, 12, 40])
def test_rotate_with_template_estimates_angle(angle):
    original, rotated = _rotated_canvas(angle)
    result = RotateSolver().solve(
        image_bytes=_png(rotated), template_bytes=_png(original), coarse_step=5
    )
    assert result.success is True
    assert result.metadata["method"] == "template_rotation"
    assert abs(float(result.text) - angle) <= 2.0
    assert abs(result.metadata["angle"] - angle) <= 2.0
    # زاوية التصحيح معاكسة لزاوية الدوران
    assert abs(result.metadata["correction"] + angle) <= 2.0
    assert result.confidence >= 0.5


def test_rotate_without_template_uses_projection():
    _, rotated = _rotated_canvas(20)
    result = RotateSolver().solve(image_bytes=_png(rotated), coarse_step=5)
    assert result.success is True
    assert result.metadata["method"] == "projection"
    assert result.text is not None
    assert result.confidence >= 0.0


def test_rotate_without_image_fails_cleanly():
    result = RotateSolver().solve()
    assert result.success is False
    assert result.error
    assert result.captcha_type == CaptchaType.ROTATE


# ---------------------- تكامل مع السجل والسيرفر ----------------------


def test_registry_solves_slider_and_rotate():
    from solver_engine.registry import registry

    target, piece = _slider_pair()
    slider = registry.solve(
        CaptchaType.SLIDER, image_bytes=_png(target), template_bytes=_png(piece)
    )
    assert slider.success is True

    original, rotated = _rotated_canvas(-18)
    rot = registry.solve(
        CaptchaType.ROTATE, image_bytes=_png(rotated), template_bytes=_png(original)
    )
    assert rot.success is True


def test_api_solve_slider_endpoint():
    from fastapi.testclient import TestClient

    from api_server.main import app

    target, piece = _slider_pair()
    client = TestClient(app)
    resp = client.post(
        "/solve/slider",
        files={
            "file": ("bg.png", _png(target), "image/png"),
            "template": ("piece.png", _png(piece), "image/png"),
        },
        data={"template_b64": ""},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["result"]["success"] is True
    assert data["result"]["captcha_type"] == "slider"
