"""مقياس دقة القراءة: يولّد كبتشا صعبة بتسميات دقيقة ويقارن المسارات.

الغرض: أي تحسين يجب أن يُقاس، لا يُفترض. هذا السكربت يعطي رقمًا واحدًا
(الدقة الكاملة) وزمنًا للقراءة، ويحفظ تقريرًا JSON لاستخدامه في الاختبارات
أو في مقارنة الإصدارات.

الاستخدام:
    python -m solver_engine.bench --count 40
    python -m solver_engine.bench --count 40 --level fast
    python -m solver_engine.bench --count 40 --json out/bench.json
"""

from __future__ import annotations

import argparse
import json
import random
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

CHARSET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


# ---------------------------------------------------------------------------
# مولّد صعب لكن عادل: كل الحروف داخل الحدود، والتسمية = ما رُسم فعلًا
# ---------------------------------------------------------------------------


# مستويان مقصودان:
#   realistic — يشبه hCaptcha النصية فعلًا: كل الحروف كاملة داخل الصورة، الخطوط
#               تُرسم خلف النص (لا تعبر منتصف الحروف)، تشويش معتدل.
#   harsh     — صور قاسية: خطوط تعبر الحروف وكتل ضوضاء فوقها. صُمّمت أصلًا
#               لتكشف نقاط الضعف، لكن بعضها غير قابل للقراءة حتى للبشر، لذلك
#               لا تُستخدم وحدها للحكم على النظام.
REALISTIC = "realistic"
HARSH = "harsh"


def render_captcha(
    text: str, seed: int = 0, width: int = 220, height: int = 64, tier: str = HARSH
):
    """صورة كبتشا بتسمية دقيقة. ``tier`` يحدّد درجة القسوة (انظر أعلاه)."""
    import cv2
    import numpy as np

    rng = random.Random(seed)
    dark = rng.random() < 0.35
    back = rng.randint(25, 70) if dark else rng.randint(215, 252)
    canvas: np.ndarray = np.full((height, width, 3), back, np.uint8)

    fore = (245, 245, 245) if dark else (15, 15, 15)
    realistic = tier == REALISTIC
    if realistic:
        # في الواقع: خلفية أفتح غالبًا، وخطوط خلف النص
        dark = rng.random() < 0.15
        back = rng.randint(45, 80) if dark else rng.randint(228, 252)
        canvas[:] = back
        fore = (245, 245, 245) if dark else (15, 15, 15)
        for _ in range(rng.randint(1, 3)):
            p1 = (rng.randint(0, width), rng.randint(0, height))
            p2 = (rng.randint(0, width), rng.randint(0, height))
            value = rng.randint(90, 190)
            cv2.line(canvas, p1, p2, (value, value, value), 1, cv2.LINE_AA)

    margin = 8
    slot = (width - 2 * margin) // max(1, len(text))
    drawn: List[str] = []
    for index, ch in enumerate(text):
        scale = rng.uniform(1.0, 1.5) * (slot / 42.0)
        thick = rng.randint(2, 3)
        (tw, th), _ = cv2.getTextSize(ch, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
        if tw > slot - 2:
            scale *= (slot - 3) / float(tw)
            (tw, th), _ = cv2.getTextSize(ch, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
        tile = np.full((th + 24, tw + 24, 3), back, np.uint8)
        cv2.putText(
            tile, ch, (8, th + 8), cv2.FONT_HERSHEY_SIMPLEX, scale, fore, thick, cv2.LINE_AA
        )
        matrix = cv2.getRotationMatrix2D(
            (tile.shape[1] / 2, tile.shape[0] / 2), rng.uniform(-18, 18), 1.0
        )
        tile = np.asarray(
            cv2.warpAffine(
                tile, matrix, (tile.shape[1], tile.shape[0]), borderValue=(back,) * 3
            )
        )
        x0 = margin + index * slot + rng.randint(0, max(0, slot - tw - 2))
        y0 = max(0, (height - tile.shape[0]) // 2 + rng.randint(-6, 6))
        y0 = min(y0, height - tile.shape[0]) if tile.shape[0] <= height else 0
        hs, ws = min(tile.shape[0], height - y0), min(tile.shape[1], width - x0)
        if hs <= 0 or ws <= 0:
            continue
        region = canvas[y0 : y0 + hs, x0 : x0 + ws]
        sub = tile[:hs, :ws]
        mask = np.abs(sub.astype(int) - back).sum(axis=2) > 40
        region[mask] = sub[mask]
        drawn.append(ch)

    if not realistic:
        for _ in range(rng.randint(2, 5)):
            p1 = (rng.randint(0, width), rng.randint(0, height))
            p2 = (rng.randint(0, width), rng.randint(0, height))
            value = rng.randint(60, 180)
            cv2.line(canvas, p1, p2, (value, value, value), rng.randint(1, 2), cv2.LINE_AA)

    speckle = np.random.default_rng(seed).integers(0, 255, (height, width), dtype=np.uint8)
    threshold = 254 if realistic else 252
    canvas[speckle > threshold] = 0
    if not realistic and rng.random() < 0.3:
        canvas = cv2.GaussianBlur(canvas, (3, 3), 0)
    return canvas, "".join(drawn)


def dataset(count: int = 30, seed: int = 7, tier: str = HARSH) -> List[Dict[str, Any]]:
    """مجموعة صور ثابتة (نفس البذرة ⇒ نفس الأرقام بين التشغيلات)."""
    rng = random.Random(seed)
    words = [
        "".join(rng.sample(CHARSET, rng.randint(4, 5))) for _ in range(count)
    ]
    items: List[Dict[str, Any]] = []
    for index, word in enumerate(words):
        image, label = render_captcha(word, seed=index, tier=tier)
        items.append({"image": image, "label": label, "seed": index})
    return items


@dataclass
class BenchReport:
    """نتيجة قياس واحدة."""

    level: str
    tier: str = HARSH
    total: int = 0
    exact: int = 0
    char_hits: int = 0
    char_total: int = 0
    time_ms: List[float] = field(default_factory=list)
    failures: List[Dict[str, Any]] = field(default_factory=list)
    confidence_on_correct: List[float] = field(default_factory=list)
    confidence_on_wrong: List[float] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.exact / self.total if self.total else 0.0

    @property
    def char_accuracy(self) -> float:
        return self.char_hits / self.char_total if self.char_total else 0.0

    @property
    def avg_ms(self) -> float:
        return sum(self.time_ms) / len(self.time_ms) if self.time_ms else 0.0

    @property
    def separation(self) -> float:
        """فرق متوسط الثقة بين الصحيح والخطأ — مقياس جودة «معرفة ما لا نعرفه»."""
        if not self.confidence_on_correct or not self.confidence_on_wrong:
            return 0.0
        return sum(self.confidence_on_correct) / len(
            self.confidence_on_correct
        ) - sum(self.confidence_on_wrong) / len(self.confidence_on_wrong)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "tier": self.tier,
            "total": self.total,
            "exact": self.exact,
            "accuracy": round(self.accuracy, 4),
            "char_accuracy": round(self.char_accuracy, 4),
            "avg_ms": round(self.avg_ms, 1),
            "separation": round(self.separation, 4),
            "failures": self.failures,
        }


def _levenshtein_hits(expected: str, actual: str) -> int:
    """عدد الأحرف الصحيحة في المواضع المتطابقة (تقدير سريع ومحافظ)."""
    return sum(1 for a, b in zip(expected, actual) if a == b)


def run(
    level: str = "balanced",
    count: int = 30,
    seed: int = 7,
    quiet: bool = False,
    tier: str = HARSH,
) -> BenchReport:
    """يشغّل القياس ويعيد تقريرًا كاملًا."""
    from .ocr import read_text

    items = dataset(count=count, seed=seed, tier=tier)
    report = BenchReport(level=level, tier=tier)
    for item in items:
        image, label = item["image"], item["label"]
        started = time.perf_counter()
        result = read_text(image, allowlist=CHARSET, level=level, expected_len=len(label))
        elapsed = (time.perf_counter() - started) * 1000.0
        text = result.text or ""
        report.total += 1
        report.time_ms.append(elapsed)
        report.char_total += len(label)
        report.char_hits += _levenshtein_hits(label, text)
        if text == label:
            report.exact += 1
            report.confidence_on_correct.append(result.confidence)
        else:
            report.confidence_on_wrong.append(result.confidence)
            report.failures.append(
                {
                    "label": label,
                    "got": text,
                    "confidence": round(result.confidence, 3),
                    "raw": round(result.raw_engine_confidence, 3),
                    "variants": result.variants_tried,
                }
            )
        if not quiet:
            mark = "✓" if text == label else "✗"
            print(f"  {mark} {label:6s} → {text:6s}  conf={result.confidence:.2f}")
    if not quiet:
        print(
            f"\n[{tier}/{level}] دقة كاملة {report.exact}/{report.total} "
            f"({report.accuracy:.0%}) | أحرف {report.char_accuracy:.0%} | "
            f"زمن {report.avg_ms:.0f}ms | فصل الثقة {report.separation:+.3f}"
        )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="قياس دقة قراءة الكبتشا")
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--level", default="balanced", choices=["fast", "balanced", "max"])
    parser.add_argument("--tier", default=REALISTIC, choices=[REALISTIC, HARSH])
    parser.add_argument("--compare", action="store_true", help="قارن كل المستويات")
    parser.add_argument("--json", default=None, help="مسار لحفظ التقرير")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    levels = ["fast", "balanced", "max"] if args.compare else [args.level]
    reports = [
        run(
            level=level,
            count=args.count,
            seed=args.seed,
            quiet=args.quiet or args.compare,
            tier=args.tier,
        )
        for level in levels
    ]
    if args.compare:
        print(f"[{args.tier}]")
        print(f"{'level':10s} {'exact':>10s} {'chars':>7s} {'ms':>7s} {'separation':>11s}")
        for report in reports:
            print(
                f"{report.level:10s} {report.exact:>4d}/{report.total:<5d} "
                f"{report.char_accuracy:>6.0%} {report.avg_ms:>7.0f} {report.separation:>+11.3f}"
            )
    if args.json:
        payload = {"tier": args.tier, "reports": [report.to_dict() for report in reports]}
        with open(args.json, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        print(f"حُفظ التقرير: {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
