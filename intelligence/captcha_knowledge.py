"""مستودع المعرفة الشامل لأنواع الكبتشا_ALL_TYPES.

يحتوي على خصائص كل نوع، استراتيجيات الحل، معاملات المعالجة المسبقة،
قواعد الكشف، والأنماط المعروفة لتسريع التعرف والحل التلقائي.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import hashlib
import json
import os


@dataclass
class CaptchaTypeInfo:
    """معلومات شاملة عن نوع كبتشا."""
    type_id: str
    name_ar: str
    name_en: str
    category: str  # image, token, interaction, math, text
    difficulty: float  # 0.0 سهل إلى 1.0 صعب جدًا
    estimated_time_ms: int
    recommended_strategy: str  # local_primary, external_primary, ensemble_with_fallback, knowledge_direct
    preprocessing_params: Dict[str, Any] = field(default_factory=dict)
    detection_rules: Dict[str, Any] = field(default_factory=dict)
    solving_hints: List[str] = field(default_factory=list)
    known_patterns: List[Dict[str, Any]] = field(default_factory=list)
    external_required: bool = False
    human_like_required: bool = False


# ---------------------- مستودع الأنواع ----------------------

CAPTCHA_TYPES: Dict[str, CaptchaTypeInfo] = {
    "image": CaptchaTypeInfo(
        type_id="image",
        name_ar="صورة/نص (OCR)",
        name_en="Image/Text CAPTCHA",
        category="image",
        difficulty=0.3,
        estimated_time_ms=800,
        recommended_strategy="local_primary",
        preprocessing_params={"psm": 7, "threshold": "otsu", "denoise": True, "preprocess": True, "resize_width": 400},
        detection_rules={
            "component_count": [3, 25],
            "avg_h": [6, 70],
            "x_spread": [0.35, 1.0],
            "y_std_max_ratio": 0.25,
            "saturation_max": 0.25,
        },
        solving_hints=[
            "استخدم Tesseract OCR مع psm 7 أو 8",
            "طبق عتبة otsu أو adaptive قبل القراءة",
            "إزالة الضوضاء والتصغير mejora الدقة",
        ],
        known_patterns=[
            {"feature_hash": "seed_text_alphanumeric", "text": "AB12", "confidence": 0.9},
            {"feature_hash": "seed_text_numeric", "text": "1234", "confidence": 0.95},
        ],
    ),
    "hcaptcha": CaptchaTypeInfo(
        type_id="hcaptcha",
        name_ar="hCaptcha",
        name_en="hCaptcha",
        category="token",
        difficulty=0.7,
        estimated_time_ms=15000,
        recommended_strategy="external_primary",
        preprocessing_params={},
        detection_rules={},
        solving_hints=[
            "يتطلب sitekey و url",
            "الخدمة الخارجية مفضلة للحل الموثوق",
            "يمكن تجربة الحل المحلي كبديل",
        ],
        external_required=True,
    ),
    "hcaptcha_enterprise": CaptchaTypeInfo(
        type_id="hcaptcha_enterprise",
        name_ar="hCaptcha Enterprise",
        name_en="hCaptcha Enterprise",
        category="token",
        difficulty=0.85,
        estimated_time_ms=20000,
        recommended_strategy="external_primary",
        preprocessing_params={},
        detection_rules={},
        solving_hints=[
            "نسخة مؤسسية، صعوبة أعلى",
            "الخدمة الخارجية مطلوبة تقريبًا",
        ],
        external_required=True,
    ),
    "recaptcha_v2": CaptchaTypeInfo(
        type_id="recaptcha_v2",
        name_ar="reCAPTCHA v2",
        name_en="reCAPTCHA v2",
        category="token",
        difficulty=0.65,
        estimated_time_ms=12000,
        recommended_strategy="external_primary",
        preprocessing_params={},
        detection_rules={},
        solving_hints=[
            "يتطلب sitekey و url",
            "غالبًا يحتاج خدمة خارجية",
        ],
        external_required=True,
    ),
    "recaptcha_v2_invisible": CaptchaTypeInfo(
        type_id="recaptcha_v2_invisible",
        name_ar="reCAPTCHA v2 غير مرئي",
        name_en="reCAPTCHA v2 Invisible",
        category="token",
        difficulty=0.75,
        estimated_time_ms=15000,
        recommended_strategy="external_primary",
        preprocessing_params={},
        detection_rules={},
        solving_hints=[
            "لا يظهر زر، يُفعل تلقائيًا",
            "الخدمة الخارجية مفضلة",
        ],
        external_required=True,
    ),
    "recaptcha_v3": CaptchaTypeInfo(
        type_id="recaptcha_v3",
        name_ar="reCAPTCHA v3",
        name_en="reCAPTCHA v3",
        category="token",
        difficulty=0.8,
        estimated_time_ms=18000,
        recommended_strategy="external_primary",
        preprocessing_params={},
        detection_rules={},
        solving_hints=[
            "نظام نقاط (score)، لا يتفاعل مع المستخدم",
            "الخدمة الخارجية مطلوبة",
        ],
        external_required=True,
    ),
    "turnstile": CaptchaTypeInfo(
        type_id="turnstile",
        name_ar="Cloudflare Turnstile",
        name_en="Cloudflare Turnstile",
        category="token",
        difficulty=0.6,
        estimated_time_ms=10000,
        recommended_strategy="external_primary",
        preprocessing_params={},
        detection_rules={},
        solving_hints=[
            "يتطلب sitekey و url",
            "الخدمة الخارجية مفضلة",
        ],
        external_required=True,
    ),
    "drag": CaptchaTypeInfo(
        type_id="drag",
        name_ar="لغز السحب (Drag)",
        name_en="Drag CAPTCHA",
        category="interaction",
        difficulty=0.5,
        estimated_time_ms=3000,
        recommended_strategy="local_primary",
        preprocessing_params={"threshold": "otsu", "denoise": True},
        detection_rules={
            "component_count": [1, 4],
            "size_ratio_max": 0.5,
            "avg_w_min": 20,
            "avg_h_min": 20,
        },
        solving_hints=[
            "تطابق القالب (template matching)",
            "احسب الإزاحة الأفقية للرغ",
        ],
        known_patterns=[],
    ),
    "point": CaptchaTypeInfo(
        type_id="point",
        name_ar="تحديد النقطة (Point)",
        name_en="Point CAPTCHA",
        category="interaction",
        difficulty=0.4,
        estimated_time_ms=2000,
        recommended_strategy="local_primary",
        preprocessing_params={"threshold": "otsu", "denoise": True},
        detection_rules={
            "saturation_min": 0.25,
            "component_count_max": 8,
        },
        solving_hints=[
            "ابحث عن البقع اللونية المشبعة",
            "حدد مركز الهدف باللون المستهدف",
        ],
        known_patterns=[],
    ),
    "funcaptcha": CaptchaTypeInfo(
        type_id="funcaptcha",
        name_ar="FunCaptcha",
        name_en="FunCaptcha",
        category="interaction",
        difficulty=0.7,
        estimated_time_ms=15000,
        recommended_strategy="external_primary",
        preprocessing_params={},
        detection_rules={},
        solving_hints=[
            "تحديات تفاعلية، صعوبة متوسطة",
            "الخدمة الخارجية مفضلة",
        ],
        external_required=True,
    ),
    "geetest": CaptchaTypeInfo(
        type_id="geetest",
        name_ar="GeeTest",
        name_en="GeeTest",
        category="interaction",
        difficulty=0.75,
        estimated_time_ms=15000,
        recommended_strategy="external_primary",
        preprocessing_params={},
        detection_rules={},
        solving_hints=[
            "نظام صيني شعبي",
            "الخدمة الخارجية مفضلة",
        ],
        external_required=True,
    ),
    "text": CaptchaTypeInfo(
        type_id="text",
        name_ar="نصي",
        name_en="Text CAPTCHA",
        category="text",
        difficulty=0.25,
        estimated_time_ms=500,
        recommended_strategy="local_primary",
        preprocessing_params={"psm": 7, "threshold": "otsu", "denoise": True},
        detection_rules={},
        solving_hints=[
            "نص بسيط يُقرأ عبر OCR",
        ],
        known_patterns=[
            {"feature_hash": "seed_text_simple", "text": "HELLO", "confidence": 0.95},
        ],
    ),
    "math": CaptchaTypeInfo(
        type_id="math",
        name_ar="حسابي (Math)",
        name_en="Math CAPTCHA",
        category="math",
        difficulty=0.3,
        estimated_time_ms=600,
        recommended_strategy="local_primary",
        preprocessing_params={"psm": 7, "threshold": "otsu", "denoise": True},
        detection_rules={},
        solving_hints=[
            "عملية حسابية بسيطة (جمع، طرح، ضرب)",
            "اقرأ الأرقام والعلامة ثم احسب",
        ],
        known_patterns=[
            {"feature_hash": "seed_math_add", "text": "5+3", "confidence": 0.9},
            {"feature_hash": "seed_math_sub", "text": "10-4", "confidence": 0.9},
        ],
    ),
    "grid": CaptchaTypeInfo(
        type_id="grid",
        name_ar="شبكة صور (Grid)",
        name_en="Image Grid CAPTCHA",
        category="image",
        difficulty=0.6,
        estimated_time_ms=8000,
        recommended_strategy="ensemble_with_fallback",
        preprocessing_params={"threshold": "otsu", "denoise": True},
        detection_rules={
            "component_count_min": 6,
            "aspect_ratio_range": [0.7, 1.4],
            "avg_w_min": 30,
            "avg_h_min": 30,
        },
        solving_hints=[
            "تصنيف الصور في شبكة",
            "قد يحتاج خدمة خارجية للدقة",
        ],
        known_patterns=[],
    ),
}


# ---------------------- أنماط نصية شائعة (بذور) ----------------------

SEED_TEXT_PATTERNS: List[Dict[str, Any]] = [
    {"text": "AB12", "type": "image", "confidence": 0.92},
    {"text": "XYZ9", "type": "image", "confidence": 0.9},
    {"text": "HELLO", "type": "text", "confidence": 0.96},
    {"text": "WORLD", "type": "text", "confidence": 0.95},
    {"text": "1234", "type": "image", "confidence": 0.95},
    {"text": "5678", "type": "image", "confidence": 0.95},
    {"text": "5+3", "type": "math", "confidence": 0.9},
    {"text": "10-4", "type": "math", "confidence": 0.9},
    {"text": "7*2", "type": "math", "confidence": 0.88},
    {"text": "ABCD", "type": "image", "confidence": 0.93},
    {"text": "EFGH", "type": "image", "confidence": 0.92},
    {"text": "IJKL", "type": "image", "confidence": 0.91},
    {"text": "MNOP", "type": "image", "confidence": 0.91},
    {"text": "QRST", "type": "image", "confidence": 0.9},
    {"text": "UVWX", "type": "image", "confidence": 0.9},
    {"text": "YZ09", "type": "image", "confidence": 0.89},
]


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:32]


def seed_knowledge_base(kb) -> int:
    """يُزرع قاعدة المعرفة بالأنماط الأساسية لجميع الأنواع. يعيد عدد الأنماط المضافة."""
    added = 0
    for p in SEED_TEXT_PATTERNS:
        features = {
            "saturation": 0.0,
            "component_count": float(len(p["text"])),
            "avg_w": float(len(p["text"]) * 10),
            "avg_h": 30.0,
            "x_spread": 0.8,
            "y_std": 0.0,
            "size_ratio": 0.5,
        }
        key = f"{p['type']}:{_hash_text(p['text'])}"
        kb.record_success(
            captcha_type=p["type"],
            features=features,
            text=p["text"],
            confidence=p["confidence"],
        )
        added += 1
    return added


# ---------------------- استراتيجيات الحل حسب النوع ----------------------

STRATEGY_BY_TYPE: Dict[str, str] = {
    "image": "local_primary",
    "hcaptcha": "external_primary",
    "hcaptcha_enterprise": "external_primary",
    "recaptcha_v2": "external_primary",
    "recaptcha_v2_invisible": "external_primary",
    "recaptcha_v3": "external_primary",
    "turnstile": "external_primary",
    "drag": "local_primary",
    "point": "local_primary",
    "funcaptcha": "external_primary",
    "geetest": "external_primary",
    "text": "local_primary",
    "math": "local_primary",
    "grid": "ensemble_with_fallback",
}


# ---------------------- معاملات المعالجة المسبقة حسب النوع ----------------------

PREPROCESS_BY_TYPE: Dict[str, Dict[str, Any]] = {
    "image": {"psm": 7, "threshold": "otsu", "denoise": True, "preprocess": True, "resize_width": 400},
    "text": {"psm": 7, "threshold": "otsu", "denoise": True, "preprocess": True, "resize_width": 400},
    "math": {"psm": 7, "threshold": "otsu", "denoise": True, "preprocess": True, "resize_width": 400},
    "drag": {"threshold": "otsu", "denoise": True},
    "point": {"threshold": "otsu", "denoise": True},
    "grid": {"threshold": "otsu", "denoise": True},
    "hcaptcha": {},
    "hcaptcha_enterprise": {},
    "recaptcha_v2": {},
    "recaptcha_v2_invisible": {},
    "recaptcha_v3": {},
    "turnstile": {},
    "funcaptcha": {},
    "geetest": {},
}


# ---------------------- توابع مساعدة ----------------------

def get_type_info(type_id: str) -> Optional[CaptchaTypeInfo]:
    return CAPTCHA_TYPES.get(type_id)


def list_types() -> List[str]:
    return sorted(CAPTCHA_TYPES.keys())


def get_strategy(type_id: str) -> str:
    return STRATEGY_BY_TYPE.get(type_id, "local_primary")


def get_preprocess(type_id: str) -> Dict[str, Any]:
    return PREPROCESS_BY_TYPE.get(type_id, {"psm": 7, "threshold": "otsu", "denoise": True})


def difficulty_score(type_id: str) -> float:
    info = CAPTCHA_TYPES.get(type_id)
    return info.difficulty if info else 0.5


__all__ = [
    "CaptchaTypeInfo",
    "CAPTCHA_TYPES",
    "SEED_TEXT_PATTERNS",
    "STRATEGY_BY_TYPE",
    "PREPROCESS_BY_TYPE",
    "get_type_info",
    "list_types",
    "get_strategy",
    "get_preprocess",
    "difficulty_score",
    "seed_knowledge_base",
]
