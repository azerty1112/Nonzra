"""قياس أثر المصحّح الشكلي على دفعة واقعية — العدد الذي يُحتجّ به.

يشغَّل: .venv/bin/python docs/glyph_bench.py

**درس منهجي مسجَّل:** ``read_text`` ليس حتميًا بين استدعاءين لأن
``_learn_from_plan`` يحدّث سياسة OCR المشتركة. لذلك نقيس على نص أساسي
مُجمَّد (قراءة واحدة) وبسياسة معزولة، وإلا ظهرت فروق زائفة.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligence.ocr_policy import reset_policy
from solver_engine import bench, glyph_classifier as gc, ocr_plus as op
from solver_engine.ocr import read_text

SEEDS = (7, 13, 21, 99)
COUNT = 24

reset_policy(path=tempfile.mktemp(suffix=".json"))
rows = []
for seed in SEEDS:
    for item in bench.dataset(count=COUNT, seed=seed, tier="realistic"):
        base = read_text(
            item["image"], allowlist=op.DEFAULT_CHARSET, level="balanced", refine=False
        )
        rows.append((item["image"], item["label"], base.text or ""))

before = sum(1 for _, label, text in rows if label == text)
after = sum(1 for image, label, text in rows if gc.refine(image, text)["text"] == label)
fixed = sum(1 for image, label, text in rows if text != label and gc.refine(image, text)["text"] == label)
broke = sum(1 for image, label, text in rows if text == label and gc.refine(image, text)["text"] != label)

chars_before = chars_after = total_chars = 0
for image, label, text in rows:
    refined = gc.refine(image, text)["text"]
    total_chars += len(label)
    chars_before += sum(1 for a, b in zip(text, label) if a == b)
    chars_after += sum(1 for a, b in zip(refined, label) if a == b)

print(f"عدد الصور: {len(rows)} (بذور {SEEDS})")
print(f"كلمة:  {before}/{len(rows)} = {before / len(rows):.0%}  →  {after}/{len(rows)} = {after / len(rows):.0%}")
print(f"حرف:   {chars_before / total_chars:.1%}  →  {chars_after / total_chars:.1%}")
print(f"أصلح {fixed} | أفسد {broke}")
reset_policy(path=tempfile.mktemp(suffix=".json"))
