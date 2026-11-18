"""قياس على كبتشا **حقيقية** — مصدر خارجي، لا مولّد Hershey.

**لماذا هذا الملف موجود:** كل الأرقام السابقة (67-82%) كانت على صور مولّدة
بخط Hershey. القياس على 1070 صورة حقيقية أعطى نتيجة مختلفة تمامًا، وهذا
الفرق هو أهم ما يجب أن يعرفه من يقرأ الأرقام.

المصدر: ``dmytrogetsko/cnn-captcha-recognition`` (``captcha_dataset.zip``)
- 1070 صورة PNG/JPG بحجم 200×50، خمسة أحرف، أبجدية صغيرة فقط
  (``2345678bcdefgmnpwxy``)، والتسمية هي اسم الملف.
- بلا رخصة معلنة في المستودع ⇒ للقياس المحلي فقط، ولا يُرفع للمستودع.

الإعداد: نزّل الصور إلى ``data/real_captcha/`` ثم:

    python docs/real_captcha_bench.py --limit 40
"""

from __future__ import annotations

import argparse
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2

from intelligence.ocr_policy import reset_policy
from solver_engine import bench, ocr_plus as op
from solver_engine.ocr import read_text

REAL_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "real_captcha")


def run_real(limit: int, level: str) -> dict:
    if not os.path.isdir(REAL_DIR):
        return {"error": f"ضع الصور في {REAL_DIR}"}
    files = sorted(
        f for f in os.listdir(REAL_DIR) if f.lower().endswith((".png", ".jpg", ".jpeg"))
    )[:limit]
    exact = case_insensitive = chars = total_chars = 0
    lengths: dict[int, int] = {}
    for name in files:
        label = os.path.splitext(name)[0]
        image = cv2.imread(os.path.join(REAL_DIR, name))
        if image is None:
            continue
        result = read_text(image, level=level)
        text = result.text or ""
        exact += int(text == label)
        case_insensitive += int(text.lower() == label.lower())
        chars += sum(1 for a, b in zip(text, label) if a == b)
        total_chars += len(label)
        lengths[len(label)] = lengths.get(len(label), 0) + 1
    count = max(1, len(files))
    return {
        "images": len(files),
        "lengths": lengths,
        "exact": exact / count,
        "case_insensitive": case_insensitive / count,
        "chars": chars / max(1, total_chars),
    }


def run_synthetic(count: int, level: str) -> dict:
    items = bench.dataset(count=count, seed=7, tier="realistic")
    ok = 0
    for item in items:
        result = read_text(item["image"], allowlist=op.DEFAULT_CHARSET, level=level)
        ok += int(result.text == item["label"])
    return {"images": count, "exact": ok / max(1, count)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=40)
    parser.add_argument("--level", default="fast")
    parser.add_argument("--synthetic", type=int, default=0)
    args = parser.parse_args()

    reset_policy(path=tempfile.mktemp(suffix=".json"))
    real = run_real(args.limit, args.level)
    if "error" in real:
        print(real["error"])
    else:
        print(f"كبتشا حقيقية ({real['images']} صورة، أطوال {real['lengths']}):")
        print(f"  مطابقة تامة:        {real['exact']:.1%}")
        print(f"  بلا حساسية للحالة:  {real['case_insensitive']:.1%}")
        print(f"  أحرف صحيحة:         {real['chars']:.1%}")
    if args.synthetic:
        synth = run_synthetic(args.synthetic, args.level)
        print(f"Hershey صناعية ({synth['images']} صورة): {synth['exact']:.1%}")
        if "error" not in real:
            print(f"الفجوة: {synth['exact'] - real['exact']:.1%}")
    reset_policy(path=tempfile.mktemp(suffix=".json"))
