"""اختبارات لمحرك حل الكبتشا."""

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from solver_engine.preprocess import (
    load_image_bytes,
    preprocess_pipeline,
    threshold_otsu,
    adaptive_threshold,
    remove_noise,
    segment_characters,
    to_pil,
    enhance_for_ocr,
)
from solver_engine.image import ImageCaptchaSolver, ImageSolveConfig


def make_captcha_image(text="AB12", size=(200, 80)):
    """إنشاء صورة كبتشا صناعية للاختبار."""
    img = Image.new("RGB", size, color="white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default()
    except Exception:
        font = None
    x = 10
    for ch in text:
        draw.text((x, 20), ch, fill="black", font=font)
        x += 40
    buf = np.frombuffer(img.tobytes(), dtype=np.uint8).reshape(size[1], size[0], 3)
    return buf


def test_threshold_otsu():
    img = make_captcha_image()
    out = threshold_otsu(img)
    assert out.shape == (80, 200)
    assert out.dtype == np.uint8


def test_adaptive_threshold():
    img = make_captcha_image()
    out = adaptive_threshold(img)
    assert out.shape == (80, 200)


def test_remove_noise():
    img = make_captcha_image()
    out = remove_noise(img)
    assert out.shape == img.shape


def test_preprocess_pipeline():
    img = make_captcha_image()
    out = preprocess_pipeline(img, grayscale=True, threshold="otsu")
    assert len(out.shape) == 2


def test_segment_characters():
    img = make_captcha_image()
    boxes = segment_characters(img)
    assert isinstance(boxes, list)


def test_to_pil_and_enhance():
    img = make_captcha_image()
    pil = to_pil(img)
    assert isinstance(pil, Image.Image)
    enhanced = enhance_for_ocr(pil)
    assert isinstance(enhanced, Image.Image)


def test_solver_returns_result_structure():
    solver = ImageCaptchaSolver()
    img = make_captcha_image("HELLO")
    from solver_engine.preprocess import to_pil as to_pil_img
    buf = to_pil_img(img)
    import io
    b = io.BytesIO()
    buf.save(b, format="PNG")
    result = solver.solve(image_bytes=b.getvalue())
    assert result.captcha_type == "image"
    assert isinstance(result.success, bool)
    assert isinstance(result.response_time_ms, int)
    assert result.metadata is not None


def test_solver_no_image_returns_error():
    solver = ImageCaptchaSolver()
    result = solver.solve()
    assert result.success is False
    assert result.error is not None


def test_config_defaults():
    cfg = ImageSolveConfig()
    assert cfg.psm == 7
    assert cfg.oem == 3
    assert cfg.preprocess is True
