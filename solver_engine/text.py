"""حلّال كبتشا النصوص البحتة (أحرف فقط أو أرقام فقط) بمعالجة مخصّصة."""

from typing import Optional

from .base import CaptchaType
from .image import ImageCaptchaSolver, ImageSolveConfig


class TextSolver(ImageCaptchaSolver):
    """نسخة متخصّصة من حلّال الصور مضبوطة على النصوص الأبجدية.

    تعيد استخدام خط أنابيب OCR نفسه لكن بقائمة أحرف مسموحة ومنطقة
    معالجة مناسبة للنصوص القصيرة، ما يرفع الدقة على كبتشا "اكتب الكلمة".
    """

    captcha_type = CaptchaType.TEXT

    def __init__(self, config: Optional[ImageSolveConfig] = None) -> None:
        cfg = config or ImageSolveConfig(
            psm=8,
            oem=3,
            whitelist="ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789",
            preprocess=True,
            resize_width=420,
            threshold="otsu",
            denoise=True,
            segment=False,
        )
        super().__init__(cfg)
        self.config = cfg


class NumericSolver(ImageCaptchaSolver):
    """حلّال كبتشا الأرقام فقط (مثل كبتشا OTP)."""

    captcha_type = CaptchaType.IMAGE

    def __init__(self, config: Optional[ImageSolveConfig] = None) -> None:
        cfg = config or ImageSolveConfig(
            psm=7,
            oem=3,
            whitelist="0123456789",
            preprocess=True,
            resize_width=300,
            threshold="otsu",
            denoise=True,
            segment=False,
        )
        super().__init__(cfg)
        self.config = cfg


__all__ = ["TextSolver", "NumericSolver"]
