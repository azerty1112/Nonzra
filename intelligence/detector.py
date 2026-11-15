"""الكشف التلقائي لنوع الكبتشا من الصورة (ذكاء التصنيف)."""

from dataclasses import dataclass
from typing import Any, Dict, Optional
import numpy as np
import cv2


@dataclass
class Detection:
    """نتيجة الكشف التلقائي."""
    captcha_type: str
    confidence: float
    features: Dict[str, float]


class AutoDetector:
    """يصنّف نوع الكبتشا تلقائيًا من خصائص الصورة دون تدخل بشري."""

    def detect(self, image: Any) -> Detection:
        if image is None or not isinstance(image, np.ndarray) or image.size == 0:
            return Detection(captcha_type="image", confidence=0.0, features={})

        is_color = len(image.shape) == 3 and image.shape[2] == 3
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if is_color else image
        h, w = gray.shape[:2]

        # ميزات اللون
        saturation = 0.0
        hue_variety = 0.0
        if is_color:
            hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
            saturation = float(hsv[:, :, 1].mean()) / 255.0
            hue = hsv[:, :, 0].astype(np.int32)
            sat_mask = hsv[:, :, 1] > 80
            if sat_mask.any():
                hue_variety = float(np.std(hue[sat_mask])) / 90.0

        # مكونات الاتصال
        _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = [cv2.boundingRect(c) for c in contours]
        boxes = [b for b in boxes if b[2] >= 4 and b[3] >= 4]
        count = len(boxes)
        if count:
            widths = [float(b[2]) for b in boxes]
            heights = [float(b[3]) for b in boxes]
            xs = [float(b[0]) for b in boxes]
            ys = [float(b[1]) for b in boxes]
            avg_w = sum(widths) / count
            avg_h = sum(heights) / count
            # مدى محاذاة أفقي (نص عادةً محاذى)
            mean_y = sum(ys) / count
            y_std = (sum((y - mean_y) ** 2 for y in ys) / count) ** 0.5
            x_spread = (max(xs) - min(xs)) / max(1.0, float(w))
            big = max(avg_w, avg_h)
            size_ratio = min(avg_w, avg_h) / big if big else 0.0
        else:
            avg_w = avg_h = 0.0
            y_std = 0.0
            x_spread = 0.0
            size_ratio = 0.0

        features: Dict[str, float] = {
            "saturation": saturation,
            "hue_variety": hue_variety,
            "component_count": float(count),
            "avg_w": avg_w,
            "avg_h": avg_h,
            "y_std": y_std,
            "x_spread": x_spread,
            "size_ratio": size_ratio,
            "aspect": float(w / h) if h else 1.0,
        }

        # قرار التصنيف
        scores: Dict[str, float] = {
            "image": 0.2,
            "point": 0.0,
            "drag": 0.0,
            "grid": 0.0,
        }

        # نص: مكوّنات صغيرة كثيرة محاذاة أفقيًا على صورة عريضة
        if 3 <= count <= 25 and 6 <= avg_h <= 70 and x_spread > 0.35 and y_std < h * 0.25:
            scores["image"] += 0.6
        # نقطة/لون: تشبع لوني عالٍ مع بقع قليلة كبيرة
        if saturation > 0.25 and hue_variety > 0.2 and count <= 8:
            scores["point"] += 0.65
        # شبكة صور: صورة مربعة تقريباً مع بقع متعددة كبيرة نسبياً
        if count >= 6 and 0.7 <= (w / h if h else 1.0) <= 1.4 and avg_w > 30 and avg_h > 30:
            scores["grid"] += 0.55
        # drag: منطقة كبيرة + قطعة صغيرة (نسبة حجم منخفضة، مكونات قليلة)
        if count <= 4 and size_ratio < 0.5 and avg_w > 20 and avg_h > 20:
            scores["drag"] += 0.5
            scores["point"] += 0.1

        best_type = max(scores, key=lambda k: scores[k])
        best_score = scores[best_type]
        confidence = min(1.0, best_score)

        # إذا كانت الثقة منخفضة، نرجع الصورة النصية كافتراض آمن
        if confidence < 0.35:
            best_type = "image"
            confidence = max(confidence, 0.35)

        return Detection(captcha_type=best_type, confidence=round(confidence, 3), features=features)


__all__ = ["Detection", "AutoDetector"]
