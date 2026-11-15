"""طبقة الذكاء التحليلي - تحليل صعوبة الكبتشا وتوقع معدل النجاح."""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import math
import numpy as np
import cv2


@dataclass
class CaptchaAnalysis:
    """نتيجة تحليل الكبتشا."""
    captcha_type: str
    difficulty_score: float  # 0.0 (سهل) إلى 1.0 (صعب جدًا)
    estimated_success_rate: float  # 0.0 إلى 1.0
    estimated_time_ms: int
    recommended_strategy: str
    features: Dict[str, float] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


class CaptchaAnalyzer:
    """محلل ذكي يحدد صعوبة الكبتشا ويستuggest أفضل استراتيجية حل."""

    def analyze_image(self, image: np.ndarray) -> CaptchaAnalysis:
        if image is None or image.size == 0:
            return CaptchaAnalysis(
                captcha_type="image",
                difficulty_score=1.0,
                estimated_success_rate=0.1,
                estimated_time_ms=5000,
                recommended_strategy="external_service",
                warnings=["صورة فارغة أو غير صالحة"],
            )

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        h, w = gray.shape

        # ميزات الصورة
        contrast = float(gray.std()) / 255.0
        brightness = float(gray.mean()) / 255.0
        edges = cv2.Canny(gray, 50, 150)
        edge_density = float((edges > 0).mean())
        noise = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        noise_score = min(1.0, noise / 500.0)

        # تقدير عدد الأحرف عبر تقطيع بسيط
        _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        char_boxes = [cv2.boundingRect(c) for c in contours if cv2.boundingRect(c)[2] > 3 and cv2.boundingRect(c)[3] > 8]
        char_count = len(char_boxes)

        features: Dict[str, float] = {
            "contrast": contrast,
            "brightness": brightness,
            "edge_density": edge_density,
            "noise": noise_score,
            "char_count": float(char_count),
            "aspect_ratio": float(w / h) if h else 1.0,
        }

        # حساب درجة الصعوبة المركبة
        difficulty = 0.0
        if contrast < 0.15:
            difficulty += 0.25
            features["low_contrast"] = 1.0
        if noise_score > 0.5:
            difficulty += 0.2
        if edge_density > 0.4:
            difficulty += 0.15
        if char_count > 8:
            difficulty += 0.15
        if brightness < 0.2 or brightness > 0.9:
            difficulty += 0.1
        difficulty = min(1.0, difficulty)

        # معدل النجاح المتوقع بناءً على الصعوبة
        success_rate = max(0.15, 1.0 - difficulty * 0.8)
        est_time = int(800 + difficulty * 3000)

        strategy = "local_ocr"
        warnings: List[str] = []
        if difficulty > 0.7:
            strategy = "external_service"
            warnings.append("صعوبة عالية يُنصح بالخدمة الخارجية")
        elif difficulty > 0.4:
            strategy = "ensemble_ocr"
            warnings.append("جودة متوسطة يُنصح بالتجميع بين محركات متعددة")

        return CaptchaAnalysis(
            captcha_type="image",
            difficulty_score=round(difficulty, 3),
            estimated_success_rate=round(success_rate, 3),
            estimated_time_ms=est_time,
            recommended_strategy=strategy,
            features=features,
            warnings=warnings,
        )

    def analyze_hcaptcha(self, sitekey: str, url: str) -> CaptchaAnalysis:
        # تحليل استباقي لأن hCaptcha يختلف حسب الموقع والمفتاح
        features = {
            "sitekey_entropy": float(len(sitekey or "")) / 40.0 if sitekey else 0.0,
            "url_length": float(len(url or "")) / 100.0,
        }
        difficulty = 0.55  # hCaptcha متوسط الصعوبة افتراضيًا
        return CaptchaAnalysis(
            captcha_type="hcaptcha",
            difficulty_score=difficulty,
            estimated_success_rate=0.75,
            estimated_time_ms=8000,
            recommended_strategy="external_service",
            features=features,
            warnings=["hCaptcha يتطلب عادةً خدمة خارجية لتحقيق نجاح عالٍ"],
        )

    def recommend(self, analysis: CaptchaAnalysis) -> Dict[str, Any]:
        return {
            "strategy": analysis.recommended_strategy,
            "use_local_first": analysis.difficulty_score < 0.5,
            "use_external_fallback": analysis.difficulty_score > 0.4,
            "expected_success": analysis.estimated_success_rate,
            "expected_time_ms": analysis.estimated_time_ms,
            "warnings": analysis.warnings,
            "features": analysis.features,
        }


__all__ = ["CaptchaAnalysis", "CaptchaAnalyzer"]
