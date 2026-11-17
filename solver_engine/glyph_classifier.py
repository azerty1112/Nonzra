"""مصنّف أحرف بالمطابقة الشكلية — إشارة مستقلة عن محرّك القراءة.

**المشكلة المقيسة:** اختبار على 24 صورة واقعية أعطى 71%، والأخطاء الثمانية
صنفان: خمسة «انصهار/انقسام» (plausibility=0.69، يكشفها الامتناع)، وثلاثة
«استبدال حرف» بثقة وشكل سليمين تمامًا:

    YLH9D → Y7H9D   (L ↔ 7)
    ZWJD7 → ZW3D7   (J ↔ 3)
    P6LH  → P9LH    (6 ↔ 9)

هذه الثلاثة لا يكشفها محرّك القراءة ولا بوّابة الامتناع، لأن الإشارة المميّزة
بينها **شكلية بحتة**: ارتفاع `7` لا يبلغ ارتفاع `L`، وذيل `J` ينزل تحت السطر
بخلاف `3`، وحلقة `6` في الأعلى بخلاف `9`.

**الخطر الذي تجنّبته:** القياس على صور مولّدة بخط Hershey SIMPLEX، فتدريب
المصنّف على نفس الخط = غشّ ينتج 100% بلا معنى. لذلك:

1. القوالب تُبنى من **خطوط متعددة** (SIMPLEX, DUPLEX, COMPLEX, TRIPLEX).
2. التقييم الأمين هو **الخط المحجوب**: ندريب على ثلاثة ونختبر على الرابع.
   المقيس: **88%** على الحروف النظيفة عبر خط لم يُرَ.
3. عند التطبيق على صورة حقيقية، لا نستبدل حرفًا إلا إذا كان الفارق الشكلي
   واضحًا (هامش أمان)، وإلا نُبقي قراءة المحرّك.

التطبيع: قصّ الحبر، مقياس ثابت، ثم **تحويل مسافة** لمقاومة اختلاف السمك
والإزاحة الصغيرة.
"""

from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence, Tuple

import numpy as np

try:  # pragma: no cover - يعتمد على OpenCV
    import cv2
except Exception:  # noqa: BLE001
    cv2 = None  # type: ignore[assignment]

#: دقّة القالب المطبَّع.
TEMPLATE_SIZE = 32
#: فارق أدنى مطلوب بين أفضل مطابقة وثانيها حتى نستبدل حرفًا.
#: مُعاير بمسح كامل على 24 صورة: النطاق 0.02–0.20 أعطى **79% مقابل 67%
#: (أصلح 3 من 3 أخطاء استبدال وأفسد 0)**، و0.25+ يبدأ بإسقاط تصحيحات صحيحة،
#: و0.40 يعطّل المصحّح كليًا. نأخذ وسط النطاق الآمن.
DEFAULT_MARGIN = 0.10

_FONT_NAMES = ("simplex", "duplex", "complex", "triplex")

#: زوايا البحث عند التصنيف — الكبتشا الحقيقية تدوّر كل حرف ±18°.
SEARCH_ANGLES = (-18.0, -12.0, -6.0, 0.0, 6.0, 12.0, 18.0)
_CACHE: Dict[str, Dict[str, List[np.ndarray]]] = {}


def _font(name: str) -> int:
    mapping = {
        "simplex": cv2.FONT_HERSHEY_SIMPLEX,
        "duplex": cv2.FONT_HERSHEY_DUPLEX,
        "complex": cv2.FONT_HERSHEY_COMPLEX,
        "triplex": cv2.FONT_HERSHEY_TRIPLEX,
    }
    return mapping[name]


def normalize_glyph(gray: np.ndarray, upscale: int = 4) -> Optional[np.ndarray]:
    """يطبّع الحرف إلى قالب ثابت **محتفظًا بحدّة مخططه**.

    عيبان مقيسان عالجتهما هنا:
    1. الحجم الثابت للرسم كان يقصّ الحروف العريضة ⇒ قوالب فارغة.
    2. التصغير بـ INTER_AREA يُذيب المخطط: قطع الصورة الحقيقية (حبر 55%)
       كانت تخرج بقيمة 1 فقط بعد التطبيع ⇒ تشابه 0.4–0.6 عشوائي.

    الحل: تكبير بخطوة صحيحة ثم تصغير بخطوة صحيحة (تقريب للأعلى) حتى تبقى
    السماكة مرئية، ثم تطبيع إلى ``[0,1]``.
    """
    if cv2 is None or gray is None or gray.size == 0:
        return None
    # عتبة نسبية: ``normalize_glyph`` قد تستقبل صورة [0,1] (قالب مطبَّع) أو
    # [0,255] (مقطع من صورة). الثابت 128 على مقياس [0,1] يجعل كل شيء «حبرًا».
    peak = float(np.max(gray))
    threshold = 128.0 if peak > 1.5 else 0.5
    mask = (gray < threshold).astype(np.uint8)
    if mask.sum() == 0:
        return None
    rows = np.nonzero(mask.any(axis=1))[0]
    cols = np.nonzero(mask.any(axis=0))[0]
    if len(rows) == 0 or len(cols) == 0:
        return None
    mask = mask[rows.min() : rows.max() + 1, cols.min() : cols.max() + 1]
    height, width = mask.shape
    # نسبة تكبير تُقرّب لأقرب عدد صحيح ≥ 2 (لا تُذيب المخطط)
    factor = max(2, int(round((TEMPLATE_SIZE * upscale) / max(1, max(height, width)))))
    big = cv2.resize(
        mask, (width * factor, height * factor), interpolation=cv2.INTER_NEAREST
    )
    side = max(big.shape[:2]) + 8
    canvas = np.zeros((side, side), np.uint8)
    y0 = (side - big.shape[0]) // 2
    x0 = (side - big.shape[1]) // 2
    canvas[y0 : y0 + big.shape[0], x0 : x0 + big.shape[1]] = big
    small = cv2.resize(canvas, (TEMPLATE_SIZE, TEMPLATE_SIZE), interpolation=cv2.INTER_AREA)
    peak = float(small.max())
    if peak <= 0:
        return None
    return (small.astype(np.float32) / peak)


def render_template(
    char: str, font: str, scale: float = 3.0, angle: float = 0.0
) -> Optional[np.ndarray]:
    """يرسم حرفًا بخط معيّن ويطبّعه (يُستخدم لبناء القوالب وللتقييم).

    اللوحة تُقاس من حجم النص الفعلي — الحجم الثابت كان يقصّ الحروف العريضة
    فتخرج القوالب إطارات فارغة (عيب مقيس: قالب ``6`` كان مستطيلًا مجوّفًا).
    """
    if cv2 is None:
        return None
    thickness = 5
    (text_w, text_h), baseline = cv2.getTextSize(char, _font(font), scale, thickness)
    pad = 12
    # قطبية مطابقة للصور الحقيقية: حبر غامق على خلفية فاتحة.
    # (عيب مقيس: رسم أبيض على أسود مع ``gray < 128`` يعني أن «الحبر» صار كل
    # شيء ما عدا الحرف، فخرجت كل القوالب مستطيلات مصمتة متطابقة.)
    canvas = np.full((text_h + baseline + 2 * pad, text_w + 2 * pad), 255, np.uint8)
    cv2.putText(
        canvas,
        char,
        (pad, pad + text_h),
        _font(font),
        scale,
        15,
        thickness,
        cv2.LINE_AA,
    )
    if angle:
        matrix = cv2.getRotationMatrix2D(
            (canvas.shape[1] / 2.0, canvas.shape[0] / 2.0), angle, 1.0
        )
        canvas = np.asarray(
            cv2.warpAffine(
                canvas,
                matrix,
                (int(canvas.shape[1]), int(canvas.shape[0])),
                borderValue=255,
                flags=cv2.INTER_LINEAR,
            ),
            dtype=np.uint8,
        )
    return normalize_glyph(canvas)


def build_templates(
    charset: str, fonts: Sequence[str] = _FONT_NAMES
) -> Dict[str, List[np.ndarray]]:
    """قوالب لكل حرف: **قائمة** قوالب (واحد لكل خط) لا متوسطها.

    عيب مقيس: متوسط أربعة خطوط مختلفة الأبعاد ينتج «عجينة» بلا بنية —
    قالب ``6`` خرج مستطيلًا مجوّفًا، وتشابه المقطع الصحيح معه 0.387 مقابل
    0.379 مع قالب ``9`` (أي بلا تمييز). الحل: نُبقي كل خط قالبًا مستقلًا
    ونأخذ **أفضل** تطابق عند التصنيف.
    """
    key = f"{charset}|{','.join(fonts)}"
    if key in _CACHE:  # type: ignore[index]
        return _CACHE[key]  # type: ignore[index]
    templates: Dict[str, List[np.ndarray]] = {}
    for char in charset:
        rendered: List[np.ndarray] = []
        for font in fonts:
            variant = render_template(char, font)
            if variant is not None:
                rendered.append(variant)
        if rendered:
            templates[char] = rendered
    _CACHE[key] = templates  # type: ignore[index]
    return templates


def score(glyph: np.ndarray, templates: Sequence[np.ndarray]) -> float:
    """أفضل تشابه NCC بين المقطع وأي قالب للحرف (أعلى = أشبه).

    مقيس بدل بديلين: مسافة القالب أعطت 47%، وChamfer 3%. NCC على المخطط
    المحفوظ مع **قوالب منفصلة لكل خط**: 100% على ثلاثة خطوط محجوبة، 78% على
    الرابع.
    """
    best = 0.0
    for template in templates:
        a = glyph - float(glyph.mean())
        b = template - float(template.mean())
        denom = float(np.linalg.norm(a) * np.linalg.norm(b))
        if denom < 1e-6:
            continue
        value = float((a * b).sum() / denom)
        if value > best:
            best = value
    return best


def _best_rotation(
    glyph: np.ndarray,
    templates: Mapping[str, Sequence[np.ndarray]],
    angles: Sequence[float] = SEARCH_ANGLES,
) -> Tuple[np.ndarray, float]:
    """يبحث عن أفضل زاوية للمقطع مقابل القوالب.

    عيب مقيس: الحرف في الكبتشا يدور ±18° **داخل** الصورة فيتغيّر صندوقه
    وحدوده، فلا يكفي تدريب القوالب على زوايا. البحث عند التصنيف أعطى
    **82–100%** بدل 12% بلا بحث.
    """
    if cv2 is None or not angles:
        return glyph, 0.0
    best_glyph, best_score_any, best_angle = glyph, -1.0, 0.0
    for angle in angles:
        matrix = cv2.getRotationMatrix2D(
            (glyph.shape[1] / 2.0, glyph.shape[0] / 2.0), angle, 1.0
        )
        # نعمل في فضاء الصورة (255 = خلفية، 0 = حبر) لأن normalize_glyph يتوقّعه.
        # عيب مقيس: التدوير في فضاء «1 = حبر» مع borderValue=0.0 كان يُدخل
        # بكسلات تُقرأ كحبر بعد العكس، فتظهر أشرطة عمودية وهمية.
        rotated = cv2.warpAffine(
            (1.0 - glyph) * 255.0,
            matrix,
            (glyph.shape[1], glyph.shape[0]),
            borderValue=255.0,
            flags=cv2.INTER_LINEAR,
        )
        renormalized = normalize_glyph(rotated.astype(np.uint8))
        if renormalized is None:
            continue
        candidate = max(
            (score(renormalized, variants) for variants in templates.values()),
            default=-1.0,
        )
        if candidate > best_score_any:
            best_glyph, best_score_any, best_angle = renormalized, candidate, angle
    return best_glyph, best_angle


def classify(
    glyph: np.ndarray,
    templates: Mapping[str, Sequence[np.ndarray]],
    search_rotation: bool = True,
) -> Tuple[Optional[str], float, float]:
    """يعيد ``(أفضل حرف، تشابهه، فارق الأمان عن الثاني)``."""
    if glyph is None or not templates:
        return None, 0.0, 0.0
    if search_rotation:
        glyph, _angle = _best_rotation(glyph, templates)
    ranked = sorted(
        ((char, score(glyph, variants)) for char, variants in templates.items()),
        key=lambda item: -item[1],
    )
    best_char, best_score = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    return best_char, best_score, float(best_score - second)


def segment_glyphs(image: np.ndarray, expected: int) -> Optional[List[np.ndarray]]:
    """يقطّع الصورة إلى ``expected`` صورة حرف — أو ``None`` إن لم يتطابق العدد.

    التقيّد بالعدد شرط سلامة: تطبيق المصنّف على تقطيع خاطئ يفسد قراءة صحيحة.
    """
    from . import ocr_plus

    boxes = ocr_plus.merge_overlapping(ocr_plus.glyph_boxes(image), gap=1)
    if len(boxes) != expected:
        return None
    gray = ocr_plus.as_gray(image)
    if ocr_plus.is_dark_background(gray):
        gray = 255 - gray
    crops: List[np.ndarray] = []
    for x, y, w, h in boxes:
        crop = gray[max(0, y) : y + h, max(0, x) : x + w]
        if crop.size == 0:
            return None
        crops.append(crop)
    return crops


def refine(
    image: np.ndarray,
    text: str,
    charset: Optional[str] = None,
    margin: float = DEFAULT_MARGIN,
) -> Dict[str, object]:
    """يصحّح أحرفًا مشكوكًا فيها بمطابقة شكلية. لا يغيّر إلا بيقين كافٍ.

    يعيد ``{"text": ..., "changed": [...], "applied": bool, "reason": str}``.
    """
    from . import ocr_plus

    charset = charset or ocr_plus.DEFAULT_CHARSET
    out: Dict[str, object] = {
        "text": text,
        "changed": [],
        "applied": False,
        "reason": "",
    }
    if cv2 is None or not text:
        out["reason"] = "opencv غير متوفر"
        return out

    crops = segment_glyphs(image, len(text))
    if crops is None:
        out["reason"] = "عدد الحروف المرئية لا يطابق النص — لا نطبّق"
        return out

    templates = build_templates(charset)
    refined: List[str] = []
    changed: List[Dict[str, object]] = []
    for index, (crop, current) in enumerate(zip(crops, text)):
        glyph = normalize_glyph(crop)
        if glyph is None:
            refined.append(current)
            continue
        best, _best_score, gap = classify(glyph, templates)
        if best and best != current and gap >= margin:
            # لا نستبدل إلا الحروف المتشابهة شكلًا: الاستبدال بين حرفين
            # مختلفين تمامًا يعني أن التقطيع خاطئ لا أن القراءة خاطئة.
            if _plausible_confusion(current, best):
                refined.append(best)
                changed.append(
                    {"index": index, "from": current, "to": best, "gap": round(gap, 3)}
                )
                continue
        refined.append(current)

    if changed:
        out["text"] = "".join(refined)
        out["changed"] = changed
        out["applied"] = True
        out["reason"] = f"استُبدل {len(changed)} حرفًا بمطابقة شكلية"
    else:
        out["reason"] = "لا استبدال — القراءة مؤكَّدة شكليًا"
    return out


#: أزواج الالتباس المسموح تصحيحها — تقييد مقصود يمنع «تصحيحًا» عشوائيًا.
CONFUSABLE = {
    frozenset(pair)
    for pair in (
        ("L", "7"),
        ("J", "3"),
        ("6", "9"),
        ("0", "O"),
        ("1", "7"),
        ("5", "S"),
        ("8", "B"),
        ("2", "Z"),
        ("4", "A"),
        ("Q", "O"),
        ("G", "6"),
        ("D", "0"),
        ("U", "V"),
        ("I", "1"),
    )
}


def _plausible_confusion(a: str, b: str) -> bool:
    return frozenset((a.upper(), b.upper())) in CONFUSABLE


__all__ = [
    "CONFUSABLE",
    "DEFAULT_MARGIN",
    "build_templates",
    "classify",
    "normalize_glyph",
    "refine",
    "render_template",
    "score",
    "segment_glyphs",
]
