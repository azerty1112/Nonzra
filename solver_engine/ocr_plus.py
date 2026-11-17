"""قراءة عميقة للصور النصية: تطبيع، اختيار طريقة عرض، وتصعيد تكيّفي.

كل ما هنا مبني على قياس فعلي داخل المستودع (``solver_engine/bench.py``)، لا على
افتراض. الخلاصة المقيسة — بما فيها ما خالف التوقّع:

- **القصّ إلى الحبر + حشو كبير (``crop_pad``) أفضل طريقة مفردة**: 75% على
  مجموعة واقعية، مقابل 67% للحشو وحده و54% للتكبير. الحشو وحده كان أكبر مكسب
  سابق (45% ← 65% على المجموعة القاسية)، لكن القصّ يتفوّق عليه.
- **التصويت بين عدّة طرق يضرّ إن أُجبر دائمًا**: 71% مقابل 75% للمفردة، لأن
  القراءات الضعيفة ناقصة الحروف فتصوّت للنص الأقصر. الحل المقيس: اقرأ مرة
  واحدة، ولا تتوسّع إلا عند انخفاض الثقة **أو** تناقض عدد الحروف مع الصورة
  (رفع ذلك 14/24 ← 17/24).
- **التدوير والبنرية القوية وإزالة الخطوط مدمّرة**: إزالة الخطوط أعطت 12%
  فقط لأنها تحذف ضربات الحروف. لذلك هي آخر الخيارات.
- **تقدير عدد الحروف لا يفصل الصحيح عن الخطأ** (فصل ≈ 0.00): يُستعمل فقط
  كإشارة تناقض صارخ لتفعيل إعادة القراءة، **لا** لمعايرة الثقة.
- **توافق طرق العرض هو الإشارة الصادقة للثقة**: 0.73 للصحيح مقابل 0.57 للخطأ.
- **الثقة الخام متفائلة**: قراءة ناقصة قد تحمل 0.99؛ لذلك تُعاير بما نعرفه
  فعلًا (التوافق) ويتعلّم النظام الباقي من قبول/رفض hCaptcha نفسه.

كل شيء هنا numpy + OpenCV فقط — بلا أي نموذج خارجي أو خدمة.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np

DEFAULT_CHARSET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

# مجموعات الحروف المتشابهة بصريًا: تُستخدم لتصحيح قراءة محتملة ولتوليد بدائل
CONFUSION_GROUPS: Tuple[str, ...] = (
    "0OQD",
    "1ILJ|",
    "2Z",
    "5S",
    "6Gb",
    "8B",
    "9Gq",
    "4A",
    "7T",
    "UVY",
    "CGo",
    "KMH",
)
_CONFUSION: Dict[str, str] = {}
for _group in CONFUSION_GROUPS:
    for _ch in _group:
        _CONFUSION[_ch] = _group


# ---------------------------------------------------------------------------
# 1) تطبيع بصري
# ---------------------------------------------------------------------------


def as_gray(image: np.ndarray) -> np.ndarray:
    if image is None:
        raise ValueError("صورة فارغة")
    if image.ndim == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    return image


def is_dark_background(gray: np.ndarray) -> bool:
    """النص فاتح على خلفية داكنة؟"""
    return float(np.median(gray)) < 110.0


def normalize_polarity(image: np.ndarray) -> np.ndarray:
    """يوحّد الحالة إلى «حبر داكن على خلفية فاتحة» — ما تتوقعه نماذج OCR."""
    gray = as_gray(image)
    if is_dark_background(gray):
        return cv2.bitwise_not(gray)
    return gray


def ink_mask(image: np.ndarray) -> np.ndarray:
    """قناع الحبر (1 حيث يوجد حبر) بعد توحيد القطبية وعتبة أوتسو.

    ملاحظة: العتبة هنا لأغراض التحليل (حدود النص/عدد المكوّنات)، لا للقراءة.
    """
    gray = normalize_polarity(image)
    if gray.size == 0:
        return np.zeros((1, 1), np.uint8)
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return (binary < 128).astype(np.uint8)


def ink_bounds(image: np.ndarray, min_ratio: float = 0.05) -> Optional[Tuple[int, int, int, int]]:
    """حدود الحبر (x0, y0, x1, y1) — أدق من حدود الصورة لهذه المهمة."""
    mask = ink_mask(image)
    if mask.sum() == 0:
        return None
    cols = mask.sum(axis=0)
    rows = mask.sum(axis=1)
    col_idx = np.where(cols >= max(2, mask.shape[0] * min_ratio))[0]
    row_idx = np.where(rows >= max(2, mask.shape[1] * min_ratio))[0]
    if len(col_idx) == 0 or len(row_idx) == 0:
        return None
    return int(col_idx[0]), int(row_idx[0]), int(col_idx[-1]), int(row_idx[-1])


def crop_to_ink(image: np.ndarray, margin: int = 3) -> np.ndarray:
    """يقصّ الفراغ الزائد — يجعل الحروف أقرب لمركز الصورة."""
    bounds = ink_bounds(image)
    if bounds is None:
        return as_gray(image)
    x0, y0, x1, y1 = bounds
    gray = as_gray(image)
    h, w = gray.shape[:2]
    x0, y0 = max(0, x0 - margin), max(0, y0 - margin)
    x1, y1 = min(w, x1 + margin + 1), min(h, y1 + margin + 1)
    if x1 - x0 < 8 or y1 - y0 < 8:
        return gray
    return gray[y0:y1, x0:x1]


def pad_for_ocr(image: np.ndarray, pad: int = 12, value: int = 255) -> np.ndarray:
    """حشو أبيض حول الصورة — أهم تحسين مقيس (يمنع إهمال حروف الحافة)."""
    gray = normalize_polarity(image)
    if pad <= 0:
        return gray
    return cv2.copyMakeBorder(gray, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=value)


def prepare(
    image: np.ndarray,
    pad: int = 12,
    crop: bool = False,
    scale: float = 1.0,
    stretch_y: float = 1.0,
) -> np.ndarray:
    """المعالجة القياسية: توحيد قطبية ← قصّ اختياري ← تكبير ← حشو.

    ``stretch_y`` يمطّ الصورة عموديًا فقط. مقيس أنه يفصل الحروف الملتحمة
    أفقيًا (مثل ``MG``) لأن الشبكة ترى فجوة رأسية أوضح — رفع هذه الحالة من
    خطأ إلى صحيح في القياس، بينما تمديد الحشو الأكبر لم يفعل شيئًا.
    """
    gray = normalize_polarity(image)
    if crop:
        gray = crop_to_ink(gray)
    if scale and abs(scale - 1.0) > 0.01:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    if stretch_y and abs(stretch_y - 1.0) > 0.01:
        height, width = gray.shape[:2]
        gray = cv2.resize(
            gray, (width, max(1, int(height * stretch_y))), interpolation=cv2.INTER_CUBIC
        )
    return pad_for_ocr(gray, pad=pad)


def normalize_contrast(image: np.ndarray) -> np.ndarray:
    """CLAHE — يعيد التباين لصور باهتة أو شديدة الظل."""
    gray = normalize_polarity(image)
    return cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(gray)


def binarize_otsu(image: np.ndarray) -> np.ndarray:
    binary = cv2.threshold(
        normalize_contrast(image), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )[1]
    if float((binary < 128).mean()) > 0.5:
        binary = cv2.bitwise_not(binary)
    return binary


def remove_thin_lines(binary: np.ndarray, max_len: int = 22) -> np.ndarray:
    """يحذف خطوط التشويش الرفيعة الطويلة ويُبقي ضربات الحروف."""
    if binary.ndim == 3:
        binary = as_gray(binary)
    if binary.max() <= 1:  # قناع 0/1
        binary = (binary * 255).astype(np.uint8)
    ink = cv2.bitwise_not(binary)
    kernel_h = cv2.getStructuringElement(cv2.MORPH_RECT, (max_len, 1))
    kernel_v = cv2.getStructuringElement(cv2.MORPH_RECT, (1, max_len))
    lines = cv2.bitwise_or(
        cv2.morphologyEx(ink, cv2.MORPH_OPEN, kernel_h),
        cv2.morphologyEx(ink, cv2.MORPH_OPEN, kernel_v),
    )
    cleaned = cv2.subtract(ink, lines)
    return cv2.bitwise_not(cleaned)


def deskew_angle(image: np.ndarray, max_angle: float = 10.0) -> float:
    """يقدّر ميل النص من تباين إسقاط الحبر الأفقي."""
    mask = ink_mask(image)
    if mask.sum() < 20:
        return 0.0
    h, w = mask.shape[:2]
    center = (w / 2.0, h / 2.0)
    best_angle, best_score = 0.0, -1.0
    for angle in np.arange(-max_angle, max_angle + 0.5, 1.0):
        rotated = cv2.warpAffine(
            mask, cv2.getRotationMatrix2D(center, float(angle), 1.0), (w, h),
            flags=cv2.INTER_NEAREST,
        )
        score = float(np.var(rotated.sum(axis=1).astype(np.float32)))
        if score > best_score:
            best_angle, best_score = float(angle), score
    return best_angle


def rotate(image: np.ndarray, angle: float) -> np.ndarray:
    if abs(angle) < 0.5:
        return as_gray(image)
    gray = normalize_polarity(image)
    h, w = gray.shape[:2]
    matrix = cv2.getRotationMatrix2D((w / 2.0, h / 2.0), angle, 1.0)
    return cv2.warpAffine(gray, matrix, (w, h), flags=cv2.INTER_CUBIC, borderValue=255)


def glyph_boxes(image: np.ndarray) -> List[Tuple[int, int, int, int]]:
    """صناديق أحرف محتملة من تحليل المكوّنات المتصلة (مستقل عن محرّك القراءة)."""
    mask = ink_mask(image)
    if mask.sum() == 0:
        return []
    h, w = mask.shape[:2]
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
    cleaned = cv2.morphologyEx(mask * 255, cv2.MORPH_OPEN, kernel)
    count, _, stats, _ = cv2.connectedComponentsWithStats(cleaned, 8)
    boxes: List[Tuple[int, int, int, int]] = []
    for index in range(1, count):
        x, y, bw, bh, area = stats[index]
        if bh < h * 0.28 or bw < 2 or area < 18:
            continue
        boxes.append((int(x), int(y), int(bw), int(bh)))
    boxes.sort(key=lambda box: box[0])
    return boxes


def merge_overlapping(
    boxes: Sequence[Tuple[int, int, int, int]], gap: int = 1
) -> List[Tuple[int, int, int, int]]:
    """يدمج الصناديق المتداخلة/الملتصقة فعلًا (حرف من قلمين) في صندوق واحد.

    ``gap`` صغير عن قصد: كبتشا تفصل بين حروفها القليل من الفراغ، فدمج فراغ
    كبير يقلّل عدد الحروف المكتشَف ويُفسد تقدير الاتساق.
    """
    merged: List[List[int]] = []
    for x, y, w, h in sorted(boxes, key=lambda b: b[0]):
        if merged and x <= merged[-1][0] + merged[-1][2] + gap:
            last = merged[-1]
            x1 = max(last[0] + last[2], x + w)
            y0 = min(last[1], y)
            y1 = max(last[1] + last[3], y + h)
            merged[-1] = [last[0], y0, x1 - last[0], y1 - y0]
        else:
            merged.append([x, y, w, h])
    return [(m[0], m[1], m[2], m[3]) for m in merged]


def visual_glyph_count(image: np.ndarray) -> int:
    """عدد الأحرف المرئية تقديريًا — مؤشر مستقل عن محرّك القراءة."""
    return len(merge_overlapping(glyph_boxes(image)))


# ---------------------------------------------------------------------------
# 2) طرق عرض آمنة (variants) — مرتّبة من الأرخص إلى الأثقل
# ---------------------------------------------------------------------------


_RENDERERS: Dict[str, Callable[[np.ndarray], np.ndarray]] = {
    "padded": lambda image: prepare(image, pad=12),
    # أفضل طريقة مقيسة للصور الواقعية: قصّ الحبر ثم حشو كبير (81% مقابل 75%)
    "crop_pad": lambda image: prepare(image, pad=30, crop=True),
    "crop_pad_tall": lambda image: prepare(image, pad=24, crop=True, stretch_y=1.8),
    "padded_8": lambda image: prepare(image, pad=8),
    "upscaled": lambda image: prepare(image, pad=10, scale=1.8),
    "padded_cropped": lambda image: prepare(image, pad=12, crop=True),
    "clahe": lambda image: pad_for_ocr(normalize_contrast(image), pad=12),
    "deskewed": lambda image: pad_for_ocr(rotate(image, deskew_angle(image)), pad=12),
    "lines_removed": lambda image: pad_for_ocr(remove_thin_lines(binarize_otsu(image)), pad=12),
}

# ترتيب كل مستوى: الأول هو الأرخص والأكثر أمانًا دائمًا.
# ``lines_removed`` في آخر ``max`` فقط: القياس أظهر أنه مدمّر (12% دقة) لأنه
# يحذف ضربات الحروف نفسها؛ أُبقي للصور المليئة بخطوط طويلة فقط.
# القياس على مجموعة واقعية (24 صورة): أفضل طريقة مفردة هي ``crop_pad``
# (75%، 18/24) وتتفوّق على دمج عدّة طرق (67–71%)، لأن القراءات الضعيفة
# تسحب التصويت. لذلك نبدأ بها، ونتوسّع فقط إذا كانت الثقة منخفضة.
LEVEL_ORDER: Dict[str, List[str]] = {
    "fast": ["crop_pad"],
    "balanced": ["crop_pad", "padded", "crop_pad_tall", "upscaled"],
    "max": [
        "crop_pad",
        "padded",
        "crop_pad_tall",
        "upscaled",
        "padded_8",
        "clahe",
        "deskewed",
        "lines_removed",
    ],
}


def render_variant(image: np.ndarray, name: str) -> np.ndarray:
    """يبني صورة العرض المطلوبة بالاسم (أو ``padded`` إن كان الاسم مجهولًا)."""
    renderer = _RENDERERS.get(name) or _RENDERERS["padded"]
    return renderer(image)


def variants(
    image: np.ndarray,
    level: str = "balanced",
    order: Optional[Sequence[str]] = None,
) -> List[Tuple[str, np.ndarray]]:
    """طرق عرض الصورة للقراءة.

    Args:
        image: صورة BGR أو رمادية.
        level: ``fast`` (حشو فقط) | ``balanced`` (حشو + قصّ + تكبير) |
            ``max`` (يضيف تباينًا/تصحيح ميل/إزالة خطوط).
        order: ترتيب مفروض من سياسة التعلّم (أسماء من ``LEVEL_ORDER``) — يسمح
            بتقديم الطريقة التي تنجح فعليًا على هذا النوع من الصور.
    """
    if order:
        names = [name for name in order if name in _RENDERERS]
        # نُبقي الشمولية: أي طريقة من مستوى أعلى تُضاف في النهاية
        for name in LEVEL_ORDER.get(level, LEVEL_ORDER["balanced"]):
            if name not in names:
                names.append(name)
    else:
        names = list(LEVEL_ORDER.get(level, LEVEL_ORDER["balanced"]))
    return [(name, render_variant(image, name)) for name in names]


# ---------------------------------------------------------------------------
# 3) تطبيع النص وتصحيح الأخطاء المتوقّعة
# ---------------------------------------------------------------------------


def normalize_text(text: Optional[str], charset: Optional[str] = None) -> str:
    """توحيد: إزالة الفراغات، رفع الحالة، تحويل المتشابهات غير المسموحة.

    مثال: نص ``"ab l2"`` مع charset بلا حروف صغيرة ⇒ ``"AB12"``. التحويل
    لا يحدث إلا إذا كان الحرف البديل مسموحًا فعلًا، فلا نفسد قراءة صحيحة.
    """
    raw = "".join(ch for ch in (text or "").upper() if not ch.isspace())
    if not charset:
        return raw
    result: List[str] = []
    for ch in raw:
        if ch in charset:
            result.append(ch)
            continue
        for candidate in _CONFUSION.get(ch, ""):
            if candidate in charset:
                result.append(candidate)
                break
    return "".join(result)


def repair_visual_confusions(text: str, charset: Optional[str] = None) -> str:
    """يستبدل حروفًا خارج مجموعة الأرقام/الحروف ببدائلها الأكثر شيوعًا."""
    if not text:
        return text
    charset = charset or DEFAULT_CHARSET
    swaps = {"O": "0", "Q": "0", "I": "1", "L": "1", "S": "5", "Z": "2", "B": "8"}
    return "".join(
        swaps.get(ch, ch) if ch not in charset else ch for ch in text
    )


# ---------------------------------------------------------------------------
# 4) التصويت بين القراءات
# ---------------------------------------------------------------------------


@dataclass
class Vote:
    """قراءة واحدة من طريقة عرض/محرّك واحد."""

    text: str
    confidence: float
    source: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "confidence": round(self.confidence, 4),
            "source": self.source,
        }


@dataclass
class EnsembleResult:
    """نتيجة الدمج مع أثر كامل للقرار (قابلة للتفسير والاختبار)."""

    text: str
    confidence: float
    votes: List[Vote] = field(default_factory=list)
    agreed: int = 0
    variants_tried: int = 0
    strategy: str = "single"
    raw_engine_confidence: float = 0.0
    plausibility: float = 1.0
    notes: List[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return bool(self.text)

    @property
    def confidence_gap(self) -> float:
        """فرق الثقة الخام عن المصحّحة — مؤشر «هل نحن واثقون زورًا؟»."""
        return round(self.raw_engine_confidence - self.confidence, 4)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "text": self.text,
            "confidence": round(self.confidence, 4),
            "raw_engine_confidence": round(self.raw_engine_confidence, 4),
            "plausibility": round(self.plausibility, 4),
            "strategy": self.strategy,
            "agreed": self.agreed,
            "variants_tried": self.variants_tried,
            "notes": list(self.notes),
            "votes": [vote.to_dict() for vote in self.votes],
        }


def vote(
    votes: Sequence[Vote],
    charset: Optional[str] = None,
    expected_len: Optional[int] = None,
) -> Tuple[str, float, int]:
    """تصويت مرجّح حرفًا بحرف. يُرجع ``(النص، الثقة، عدد المتفقين)``."""
    normalized: List[Tuple[str, float]] = []
    for item in votes:
        text = normalize_text(item.text, charset)
        if text:
            normalized.append((text, max(0.05, float(item.confidence))))
    if not normalized:
        return "", 0.0, 0

    # 1) الطول الأرجح: ثقل الأصوات، مع أفضلية خفيفة للطول المتوقّع إن عُرف
    weights: Dict[int, float] = {}
    for text, confidence in normalized:
        weights[len(text)] = weights.get(len(text), 0.0) + confidence
    if expected_len:
        weights[expected_len] = weights.get(expected_len, 0.0) + 0.9
    best_len = max(weights.items(), key=lambda kv: kv[1])[0]

    contenders = [(t, c) for t, c in normalized if len(t) == best_len]
    if not contenders:
        contenders = sorted(normalized, key=lambda item: item[1], reverse=True)[:1]
        best_len = len(contenders[0][0])

    # 2) تصويت كل موضع
    chars: List[str] = []
    per_position_share: List[float] = []
    for index in range(best_len):
        tally: Dict[str, float] = {}
        for text, confidence in contenders:
            tally[text[index]] = tally.get(text[index], 0.0) + confidence
        winner = max(tally, key=tally.get)
        chars.append(winner)
        per_position_share.append(tally[winner] / sum(tally.values()))

    text = "".join(chars)
    mean_conf = float(np.mean([c for _, c in contenders]))
    agreement = float(np.mean(per_position_share))
    confidence = float(np.clip(0.55 * agreement + 0.45 * mean_conf, 0.0, 1.0))
    agreed = sum(1 for t, _ in contenders if t == text)
    return text, confidence, agreed


def support(votes: Sequence[Vote], text: str, charset: Optional[str] = None) -> float:
    """نسبة طرق العرض التي أنتجت النص الفائز — إشارة الثقة الأصدق.

    مقيسة على مجموعة صعبة: متوسط 0.73 للقراءة الصحيحة مقابل 0.57 للخطأ،
    ومعدّل قبول خاطئ 2/7 عند عتبة 0.6. لذلك تُستخدم لتقدير «هل أُرسل الإجابة
    أم أعيد القراءة بعمق أكبر؟».
    """
    texts = [normalize_text(vote.text, charset) for vote in votes]
    texts = [item for item in texts if item]
    if not texts:
        return 0.0
    return sum(1 for item in texts if item == text) / len(texts)


def confidence_from_support(support_ratio: float) -> float:
    """يحوّل نسبة التوافق إلى ثقة تقريبية (المعايرة الدقيقة تتعلّمها السياسة)."""
    return float(np.clip(0.35 + 0.6 * support_ratio, 0.0, 0.995))


def measure_wide_glyphs(image: np.ndarray, ratio: float = 1.55) -> List[Tuple[int, int, int, int]]:
    """مكوّنات عريضة بشكل غير طبيعي — أي حرفين ملتحمين أو أكثر.

    تحليل المكوّنات يرى الحرفين الملتصقين مكوّنًا واحدًا، فيظنّ النظام أن عدد
    الحروف أقل فيقبل قراءة ناقصة. هذا المؤشر يعدّهما حرفين، وهو ما يجعل
    العقوبة تعمل لصالحنا بدلًا من أن تنقلب علينا.
    """
    boxes = glyph_boxes(image)
    if len(boxes) < 2:
        return []
    widths = sorted(box[2] for box in boxes)
    median_width = float(np.median(widths)) or 1.0
    return [box for box in boxes if box[2] > median_width * ratio]


def estimated_glyph_count(image: np.ndarray, ratio: float = 1.55) -> float:
    """عدد الأحرف التقديري مع احتساب المكوّنات العريضة كأكثر من حرف."""
    boxes = glyph_boxes(image)
    if not boxes:
        return 0.0
    widths = sorted(box[2] for box in boxes)
    median_width = float(np.median(widths)) or 1.0
    total = 0.0
    for box in boxes:
        total += max(1.0, round(box[2] / median_width))
    return total


def character_consistency(image: np.ndarray, text: str) -> float:
    """مقارنة عدد الأحرف المقروءة بعدد الأحرف التقديري (مع دمج التناقضات).

    ``1.0`` تطابق تام، ``< 1`` يعني على الأغلب حرفًا ساقطًا أو زائدًا.
    """
    if not text:
        return 0.0
    estimated = estimated_glyph_count(image)
    if estimated <= 0:
        return 0.7
    diff = abs(estimated - len(text))
    tolerance = 0.5 if estimated <= 4 else max(0.5, estimated * 0.15)
    if diff <= tolerance:
        return 1.0
    return float(max(0.1, 0.75 - 0.25 * (diff - tolerance)))


def plausibility(image: np.ndarray, text: str) -> float:
    """توافق القراءة مع الشكل البصري — **لا يُستخدم لمعايرة الثقة**.

    السبب: القياس على مجموعة صعبة أظهر أن تقدير عدد الحروف من تحليل المكوّنات
    لا يفصل الصحيح عن الخطأ (الفصل ≈ 0.00)، لأن الحروف الملتصقة تُرى مكوّنًا
    واحدًا. الإشارة التي أثبتت فصلًا حقيقيًا هي **توافق طرق العرض المختلفة**
    (انظر ``support`` ولاحظ متوسط الدعم: 0.73 للصحيح مقابل 0.57 للخطأ).

    تُبقى هذه الدالة للاستدلال/التشخيص وعرض الحالة، لا لقرار القبول.
    """
    if not text:
        return 0.0
    return character_consistency(image, text)


# ---------------------------------------------------------------------------
# 5) القراءة المتجمّعة مع تصعيد تكيّفي
# ---------------------------------------------------------------------------

ReadOne = Callable[[np.ndarray], Optional[Tuple[str, float]]]


def _empty(read_one: ReadOne, variant: np.ndarray) -> Optional[Tuple[str, float]]:
    try:
        return read_one(variant)
    except Exception:  # noqa: BLE001 - فشل طريقة عرض واحدة لا يجب أن يُسقط العملية
        return None


def ensemble_read(
    image: np.ndarray,
    read_one: ReadOne,
    charset: Optional[str] = None,
    expected_len: Optional[int] = None,
    level: str = "balanced",
    min_confidence: float = 0.9,
    time_budget_ms: float = 8000.0,
    stop_on_perfect: bool = True,
    order: Optional[Sequence[str]] = None,
) -> EnsembleResult:
    """يقرأ الصورة بعدة طرق عرض ويصوّت، مع تصعيد تكيّفي وميزانية زمنية.

    التصعيد: تبدأ القراءة بأرخص طرق العرض، وإن كانت الثقة عالية *و* الطول
    منطقيًا مطابق لما تراه الصورة نتوقف فورًا. وإلا نضيف طرق عرض أثقل حتى
    تنتهي الميزانية. هذا يعطي سرعة الحالة السهلة ودقة الحالة الصعبة معًا.
    """
    import time

    started = time.perf_counter()
    votes: List[Vote] = []
    tried = 0
    notes: List[str] = []

    for name, variant in variants(image, level=level, order=order):
        if (time.perf_counter() - started) * 1000.0 > time_budget_ms:
            notes.append("time_budget_exhausted")
            break
        tried += 1
        output = _empty(read_one, variant)
        if not output:
            continue
        text = normalize_text(output[0], charset)
        if not text:
            continue
        confidence = float(output[1])
        votes.append(Vote(text, confidence, name))

        best_text, best_conf, agreed = vote(votes, charset=charset, expected_len=expected_len)
        # إشارة «الشكل»: هل عدد الحروف المقروءة يوافق عدد الحروف المرئية؟
        # ليست معايرةً للثقة (سبق أن قِسنا أنها لا تفصل)، لكنها كافية لتفعيل
        # إعادة القراءة عند تناقض صارخ (نص أقصر من المرئي بفارق كبير).
        consistent = plausibility(image, best_text) >= 0.9
        # توقّف مبكر: قراءة أولى بثقة جيدة **ومتّسقة مع شكل الصورة** ⇒ لا داعي
        # للتصويت. القياس أظهر أن تكرار القراءة يضرّ 5 نقاط (14/24 ← 9/24)،
        # وأن باقي الطرق تُقرأ غالبًا ناقصة، فتصويت الأغلبية يختارها.
        if stop_on_perfect and best_conf >= min_confidence and consistent:
            notes.append("early_stop")
            break

    if not votes:
        return EnsembleResult("", 0.0, [], 0, tried, f"ensemble:{level}")

    text, confidence, agreed = vote(votes, charset=charset, expected_len=expected_len)
    agree_ratio = support(votes, text, charset)
    raw = max(v.confidence for v in votes)
    # الإشارة المقيسة: كلما زاد توافق طرق العرض زادت الثقة. عند قراءة واحدة
    # (الحالة السهلة) لا نُعاقب — لكن لا ندّعي ثقة أعلى من ثقة المحرّك.
    if len(votes) > 1:
        calibrated = 0.5 * confidence + 0.5 * confidence_from_support(agree_ratio)
    else:
        calibrated = confidence
    if len(votes) > 1 and agree_ratio < 0.6:
        notes.append("low_variant_agreement")
    sane = plausibility(image, text)
    return EnsembleResult(
        text=text,
        confidence=float(np.clip(calibrated, 0.0, 0.999)),
        votes=votes,
        agreed=agreed,
        variants_tried=tried,
        strategy=f"ensemble:{level}",
        raw_engine_confidence=raw,
        plausibility=sane,
        notes=notes,
    )


__all__ = [
    "CONFUSION_GROUPS",
    "DEFAULT_CHARSET",
    "EnsembleResult",
    "Vote",
    "as_gray",
    "binarize_otsu",
    "character_consistency",
    "estimated_glyph_count",
    "crop_to_ink",
    "estimated_glyph_count",
    "measure_wide_glyphs",
    "deskew_angle",
    "ensemble_read",
    "glyph_boxes",
    "ink_bounds",
    "ink_mask",
    "is_dark_background",
    "merge_overlapping",
    "normalize_contrast",
    "normalize_polarity",
    "normalize_text",
    "pad_for_ocr",
    "plausibility",
    "prepare",
    "LEVEL_ORDER",
    "remove_thin_lines",
    "render_variant",
    "support",
    "repair_visual_confusions",
    "rotate",
    "variants",
    "visual_glyph_count",
    "vote",
]
