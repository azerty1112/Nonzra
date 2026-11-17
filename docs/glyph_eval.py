"""تقييم أمين لمصنّف الأحرف: تدريب على خطوط، اختبار على الخط المحجوب.

الخطر الذي يعالجه هذا الملف: صور القياس تُرسم بخط Hershey SIMPLEX، فتدريب
المصنّف على نفس الخط يعطي 100% بلا معنى. هنا نُدريب على كل الخطوط **إلا**
واحدًا، ونقيس على المحجوب.

يشغَّل: .venv/bin/python docs/glyph_eval.py
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from solver_engine import glyph_classifier as gc, ocr_plus as op

ALL_FONTS = ("simplex", "duplex", "complex", "triplex")
CHARSET = op.DEFAULT_CHARSET


def variant(char: str, font: str, mode: str):
    """يرسم الحرف بخط معيّن مع تحريف (دوران/ضجيج) ثم يطبّعه."""
    import cv2

    import numpy as np

    if mode == "clean":
        return gc.render_template(char, font)
    # رسم خام (حبر غامق على خلفية فاتحة) ثم تحريف قبل التطبيع
    (tw, th), bl = cv2.getTextSize(char, gc._font(font), 3.0, 5)
    img = np.full((th + bl + 24, tw + 24), 255, np.uint8)
    cv2.putText(img, char, (12, 12 + th), gc._font(font), 3.0, 15, 5, cv2.LINE_AA)
    if mode == "rot":
        rng = random.Random(char)
        matrix = cv2.getRotationMatrix2D((img.shape[1] / 2, img.shape[0] / 2), rng.uniform(-18, 18), 1.0)
        # borderValue=255 (لون الخلفية) لا 0: الصفر أسود = حبر وهمي عند الدوران
        img = cv2.warpAffine(img, matrix, (img.shape[1], img.shape[0]), borderValue=255)
    elif mode == "noise":
        img = cv2.GaussianBlur(img, (3, 3), 0)
        rng = np.random.default_rng(len(char))
        speckle = rng.integers(0, 255, img.shape, dtype=np.uint8)
        img[img > 200] = 255
        img[speckle > 250] = 15
    return gc.normalize_glyph(img)


def evaluate(holdout: str, mode: str):
    train = tuple(f for f in ALL_FONTS if f != holdout)
    templates = gc.build_templates(CHARSET, fonts=train)
    hits = total = 0
    for char in CHARSET:
        glyph = variant(char, holdout, mode)
        if glyph is None:
            continue
        total += 1
        best, _score, _gap = gc.classify(glyph, templates)
        hits += int(best == char)
    return hits, total


if __name__ == "__main__":
    print(f"{'محجوب':10s} {'نظيف':12s} {'دوران ±18°':14s} {'ضجيج':12s}")
    for holdout in ALL_FONTS:
        cells = []
        for mode in ("clean", "rot", "noise"):
            hits, total = evaluate(holdout, mode)
            cells.append(f"{hits}/{total}={hits / total:.0%}")
        print(f"{holdout:10s} " + "   ".join(f"{c:12s}" for c in cells))
