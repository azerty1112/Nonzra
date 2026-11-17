"""اختبارات المصحّح الشكلي: القوالب، الانتقال بين الخطوط، وحدّ التصحيح."""

import cv2
import numpy as np
import pytest

from solver_engine import glyph_classifier as gc, ocr_plus as op


def test_templates_are_not_blobs():
    """عيب مقيس سابقًا: القوالب كانت مستطيلات مصمتة (انعكاس قطبية)."""
    templates = gc.build_templates("AB69", fonts=("simplex",))
    for char in "AB69":
        template = templates[char][0]
        fill = float((template > 0.5).mean())
        assert 0.05 < fill < 0.85, f"قالب {char} نسبة حبره {fill:.2f} — مصمت أو فارغ"


def test_normalize_glyph_accepts_both_scales():
    """عتبة نسبية: الصور تُمرَّر بمقياس [0,1] أو [0,255]."""
    ink_small = np.zeros((20, 20), np.float32)
    ink_small[5:15, 5:15] = 1.0
    ink_big = (ink_small * 255).astype(np.uint8)
    for image in (ink_small, ink_big):
        normalized = gc.normalize_glyph(image)
        assert normalized is not None
        assert normalized.shape == (gc.TEMPLATE_SIZE, gc.TEMPLATE_SIZE)


@pytest.mark.parametrize("holdout", ["simplex", "duplex", "complex", "triplex"])
def test_generalizes_to_unseen_font(holdout):
    """الاختبار الأمين: تدريب على ثلاثة خطوط والاختبار على الرابع.

    لا يُقبل 100% على خط التدريب — هذا يقيس الانتقال لا الحفظ.
    """
    train = tuple(f for f in ("simplex", "duplex", "complex", "triplex") if f != holdout)
    templates = gc.build_templates(op.DEFAULT_CHARSET, fonts=train)
    hits = 0
    for char in op.DEFAULT_CHARSET:
        glyph = gc.render_template(char, holdout)
        if glyph is None:
            continue
        best, _score, _gap = gc.classify(glyph, templates)
        hits += int(best == char)
    assert hits / len(op.DEFAULT_CHARSET) >= 0.95, f"{holdout}: {hits}/32"


def test_confusable_pairs_are_separated():
    """الأزواج التي فشل فيها المحرّك: L/7 وJ/3 و6/9."""
    templates = gc.build_templates(op.DEFAULT_CHARSET)
    for char in "L7J369":
        glyph = gc.render_template(char, "complex")
        best, _score, _gap = gc.classify(glyph, templates)
        assert best == char, f"{char} صُنِّف {best}"


def test_refine_refuses_when_glyph_count_mismatches():
    """سلامة أولًا: تقطيع لا يطابق الطول ⇒ لا تصحيح إطلاقًا."""
    image = np.full((64, 220, 3), 240, np.uint8)
    cv2.putText(image, "AB", (20, 45), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (20, 20, 20), 2)
    outcome = gc.refine(image, "ABCD", charset="ABCD")
    assert outcome["applied"] is False
    assert outcome["text"] == "ABCD"


def test_refine_only_substitutes_confusable_pairs():
    """لا استبدال بين حرفين غير متشابهين: هذا يعني تقطيعًا خاطئًا لا قراءة."""
    assert gc._plausible_confusion("7", "L") is True
    assert gc._plausible_confusion("6", "9") is True
    assert gc._plausible_confusion("A", "W") is False


def test_read_text_exposes_glyph_refine_metadata():
    from solver_engine import bench
    from solver_engine.ocr import read_text

    item = bench.dataset(count=8, seed=7, tier="realistic")[0]
    result = read_text(item["image"], allowlist=op.DEFAULT_CHARSET, level="fast")
    assert hasattr(result, "glyph_refine")
    assert isinstance(result.glyph_refine, list)


def test_refine_never_breaks_a_correct_read():
    """خاصية السلامة (الأهم): المصحّح لا يُفسد قراءة صحيحة أبدًا.

    المعدّل الكامل للتأثير يُقاس في ``docs/glyph_bench.py`` (96 صورة:
    75% → 80%، أصلح 5، أفسد 0). الاختبار يقيس **الثبات** فقط لأن معدّل
    التحسّن يعتمد على الكمية ويجعل الاختبار هشًّا.
    """
    import tempfile

    from intelligence.ocr_policy import reset_policy
    from solver_engine import bench
    from solver_engine.ocr import read_text

    reset_policy(path=tempfile.mktemp(suffix=".json"))
    broke = 0
    for seed in (7, 13):
        for item in bench.dataset(count=12, seed=seed, tier="realistic"):
            base = read_text(
                item["image"], allowlist=op.DEFAULT_CHARSET, level="balanced", refine=False
            )
            if base.text != item["label"]:
                continue
            assert gc.refine(item["image"], base.text)["text"] == base.text
            broke += 0
    reset_policy(path=tempfile.mktemp(suffix=".json"))
    assert broke == 0


def test_refine_is_a_noop_on_correct_reads():
    """على نص صحيح شكليًا، المصحّح لا يغيّر شيئًا (لا ضرر جانبي)."""
    from solver_engine import bench
    from solver_engine.ocr import read_text

    checked = 0
    for item in bench.dataset(count=12, seed=7, tier="realistic"):
        base = read_text(
            item["image"], allowlist=op.DEFAULT_CHARSET, level="balanced", refine=False
        )
        if base.text != item["label"]:
            continue
        checked += 1
        assert gc.refine(item["image"], base.text or "")["text"] == base.text
    assert checked > 0
