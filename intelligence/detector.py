"""الكشف التلقائي لنوع الكبتشا من الصورة (ذكاء التصنيف) باستخدام قاعدة المعرفة الشاملة."""

from dataclasses import dataclass
from typing import Any, Dict

import cv2
import numpy as np

from intelligence.captcha_knowledge import CAPTCHA_TYPES, list_types


@dataclass
class Detection:
    """نتيجة الكشف التلقائي."""
    captcha_type: str
    confidence: float
    features: Dict[str, float]


class AutoDetector:
    """يصنّف نوع الكبتشا تلقائيًا من خصائص الصورة وقواعد المعرفة الشاملة."""

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

        # تقييم كل نوع باستخدام قواعده من قاعدة المعرفة
        scores: Dict[str, float] = {}
        for type_id in list_types():
            info = CAPTCHA_TYPES[type_id]
            score = 0.0
            rules = info.detection_rules

            # عدد المكونات
            if "component_count" in rules:
                lo, hi = rules["component_count"]
                if lo <= count <= hi:
                    score += 0.25
            if "component_count_max" in rules and count <= rules["component_count_max"]:
                score += 0.15
            if "component_count_min" in rules and count >= rules["component_count_min"]:
                score += 0.15

            # متوسط الارتفاع
            if "avg_h" in rules:
                lo, hi = rules["avg_h"]
                if lo <= avg_h <= hi:
                    score += 0.2
            if "avg_h_min" in rules and avg_h >= rules["avg_h_min"]:
                score += 0.1

            # متوسط العرض
            if "avg_w_min" in rules and avg_w >= rules["avg_w_min"]:
                score += 0.1

            # الانتشار الأفقي (نص محاذى)
            if "x_spread" in rules:
                lo, hi = rules["x_spread"]
                if lo <= x_spread <= hi:
                    score += 0.2

            # انحراف y المحوري
            if "y_std_max_ratio" in rules and y_std < h * rules["y_std_max_ratio"]:
                score += 0.15

            # نسبة الحجم (drag)
            if "size_ratio_max" in rules and size_ratio <= rules["size_ratio_max"]:
                score += 0.2

            # نسبة العرض إلى الارتفاع (grid)
            if "aspect_ratio_range" in rules:
                lo, hi = rules["aspect_ratio_range"]
                aspect = features["aspect"]
                if lo <= aspect <= hi:
                    score += 0.2

            # التشبع (point/lون)
            if "saturation_min" in rules and saturation >= rules["saturation_min"]:
                score += 0.25
            if "saturation_max" in rules and saturation <= rules["saturation_max"]:
                score += 0.1

            scores[type_id] = score

        # إذا لم يسجل أي نوع نقاط، نعطي image أولوية افتراضية
        if not scores or max(scores.values()) <= 0:
            scores["image"] = 0.2

        best_type = max(scores, key=lambda k: scores[k])
        best_score = scores[best_type]
        confidence = min(1.0, best_score)

        # إذا كانت الثقة منخفضة، نرجع الصورة النصية كافتراض آمن
        if confidence < 0.35:
            best_type = "image"
            confidence = max(confidence, 0.35)

        return Detection(captcha_type=best_type, confidence=round(confidence, 3), features=features)


__all__ = ["Detection", "AutoDetector"]
