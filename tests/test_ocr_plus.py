"""اختبارات طبقة القراءة العميقة: تطبيع، تحليل بصري، تصويت، وتعلّم سياسة القراءة."""

import os

import cv2
import numpy as np
import pytest

from intelligence.ocr_policy import OcrPolicy
from solver_engine import ocr_plus
from solver_engine.bench import render_captcha
from solver_engine.ocr import OcrResult, read_text

CHARSET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # مجموعة hCaptcha (بلا I/O/1)
ALNUM = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"  # أوسع: تقبل 1 و O


def _text_image(text: str, dark: bool = False, noisy: bool = False) -> np.ndarray:
    back = 40 if dark else 240
    fore = 235 if dark else 20
    image = np.full((64, 230, 3), back, np.uint8)
    cv2.putText(image, text, (14, 48), cv2.FONT_HERSHEY_SIMPLEX, 1.5, (fore,) * 3, 3, cv2.LINE_AA)
    if noisy:
        rng = np.random.default_rng(3)
        for _ in range(4):
            p1 = (int(rng.integers(0, 230)), int(rng.integers(0, 64)))
            p2 = (int(rng.integers(0, 230)), int(rng.integers(0, 64)))
            cv2.line(image, p1, p2, (120, 120, 120), 1, cv2.LINE_AA)
    return image


# ---------------------- التطبيع والتحليل البصري ----------------------


def test_normalize_polarity_flips_dark_background():
    dark = _text_image("AB12", dark=True)
    assert ocr_plus.is_dark_background(ocr_plus.as_gray(dark))
    flipped = ocr_plus.normalize_polarity(dark)
    assert not ocr_plus.is_dark_background(flipped)


def test_prepare_pads_image():
    image = _text_image("AB12")
    prepared = ocr_plus.prepare(image, pad=12)
    assert prepared.ndim == 2
    assert prepared.shape[0] == image.shape[0] + 24
    assert prepared.shape[1] == image.shape[1] + 24


def test_ink_bounds_and_crop_trim_background():
    image = _text_image("7KQ9")
    bounds = ocr_plus.ink_bounds(image)
    assert bounds is not None
    x0, _, x1, _ = bounds
    assert 0 <= x0 < x1 <= image.shape[1]
    cropped = ocr_plus.crop_to_ink(image)
    assert cropped.shape[1] < image.shape[1]


def test_visual_glyph_count_matches_letters():
    assert ocr_plus.visual_glyph_count(_text_image("AB12")) == 4
    assert ocr_plus.visual_glyph_count(_text_image("7KQ9")) == 4


def test_plausibility_penalizes_truncated_text():
    image = _text_image("AB12")
    assert ocr_plus.plausibility(image, "AB12") == 1.0
    assert ocr_plus.plausibility(image, "AB") < 0.9
    assert ocr_plus.plausibility(image, "") == 0.0


def test_normalize_text_maps_confusable_characters():
    # "l" يُرفع إلى "L" وهو مسموح، و"-" يُسقط
    assert ocr_plus.normalize_text("ab-l2 ", CHARSET) == "ABL2"
    # خارج المجموعة ⇒ يُحوّل إلى أقرب شكل مسموح
    assert ocr_plus.normalize_text("O0Q", "0123456789") == "000"
    assert ocr_plus.normalize_text("xy", "XYZ") == "XY"
    assert ocr_plus.normalize_text(None, CHARSET) == ""


def test_variants_respect_level_and_order():
    image = _text_image("AB12")
    fast = ocr_plus.variants(image, level="fast")
    assert [name for name, _ in fast] == ["padded"]
    balanced = [name for name, _ in ocr_plus.variants(image, level="balanced")]
    assert balanced[0] == "padded" and len(balanced) >= 3
    ordered = [name for name, _ in ocr_plus.variants(image, level="balanced", order=["upscaled"])]
    assert ordered[0] == "upscaled" and "padded" in ordered


# ---------------------- التصويت ----------------------


def test_vote_prefers_weighted_majority():
    votes = [
        ocr_plus.Vote("AB12", 0.9, "a"),
        ocr_plus.Vote("AB12", 0.8, "b"),
        ocr_plus.Vote("AB32", 0.4, "c"),
    ]
    text, confidence, agreed = ocr_plus.vote(votes, charset=ALNUM)
    assert text == "AB12"
    assert agreed == 2
    assert confidence > 0.8


def test_vote_uses_expected_length_to_resolve_split():
    votes = [ocr_plus.Vote("AB12", 0.7, "a"), ocr_plus.Vote("AB", 0.75, "b")]
    text, _, _ = ocr_plus.vote(votes, charset=ALNUM, expected_len=4)
    assert text == "AB12"


def test_vote_empty_input():
    text, confidence, agreed = ocr_plus.vote([])
    assert (text, confidence, agreed) == ("", 0.0, 0)


# ---------------------- التجميع عبر المحرّك الحقيقي ----------------------


def test_ensemble_reads_simple_captcha_fast():
    image = _text_image("AB12")
    result = read_text(image, allowlist=ALNUM)
    assert result.text == "AB12"
    assert result.plausibility >= 0.99
    assert result.variants_tried >= 1
    assert result.context  # سياق الصورة صُنّف


def test_ensemble_result_exposes_decision_trace():
    image = _text_image("7KQ9")
    result = read_text(image, allowlist=ALNUM)
    payload = result.to_dict()
    for key in ("raw_engine_confidence", "plausibility", "variants_tried", "context", "strategy"):
        assert key in payload
    assert payload["text"] == "7KQ9"


def test_truncated_read_is_detected_not_trusted():
    """حرف مفقود يجب أن يُكتشف من تحليل الصورة نفسه، بلا معرفة مسبقة بالنص.

    هذه أهم ضمانة في النظام: طول النص المرئي يكذّب القراءة الناقصة حتى لو
    أعطاها المحرّك ثقة 0.99.
    """
    from solver_engine.ocr_plus import plausibility, visual_glyph_count

    image = _text_image("7KQ9")
    assert visual_glyph_count(image) == 4
    assert plausibility(image, "7K9") < 1.0
    assert plausibility(image, "7KQ9") == 1.0
    # قصير جدًا = مؤشر خطر واضح لا يُتجاهل
    assert plausibility(image, "7") < 0.5


def test_disagreeing_variants_lower_confidence():
    """عند اختلاف طرق العرض تنخفض الثقة المصحّحة عن ثقة المحرّك الخام.

    هذا هو مؤشر «لا نعرف» المقيس: التوافق بين الطرق فصل الصحيح عن الخطأ
    بمتوسط 0.73 مقابل 0.57 على مجموعة الاختبار الصعبة.
    """
    image = _text_image("7KQ9")
    outputs = iter([("7K9", 0.97), ("7KQ4", 0.97), ("ABCD", 0.97)])

    def fake_reader(variant):
        return next(outputs, ("ABCD", 0.99))

    outcome = ocr_plus.ensemble_read(
        image, fake_reader, charset=ALNUM, level="balanced", min_confidence=0.9
    )
    assert outcome.text
    assert "low_variant_agreement" in outcome.notes
    assert outcome.confidence <= outcome.raw_engine_confidence



# ---------------------- نقاط النهاية ----------------------


@pytest.fixture()
def client():
    from fastapi.testclient import TestClient

    import api_server.main as main_mod

    return TestClient(main_mod.app)


def test_ocr_policy_endpoint(client):
    response = client.get("/ocr/policy")
    assert response.status_code == 200
    payload = response.json()
    assert "contexts" in payload and "calibration" in payload


def test_ocr_bench_endpoint(client):
    response = client.post("/ocr/bench", json={"count": 4, "level": "fast", "seed": 3})
    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 4
    assert payload["avg_ms"] > 0
