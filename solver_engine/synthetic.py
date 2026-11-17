"""مولّد بيانات تدريب صناعية لكبتشا الصور.

يُنشئ صور كبتشا نصية بخصائص متنوعة (تشويش، تدوير، خطوط، ضوضاء) مع
التسميات الدقيقة، وذلك لتغذية تدريب نموذج CNN أو لاختبار المحرّكات
دون الحاجة إلى بيانات خارجية.
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

DEFAULT_CHARSET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _random_color(rng: random.Random, dark: bool = True) -> Tuple[int, int, int]:
    if dark:
        return (
            rng.randint(0, 90),
            rng.randint(0, 90),
            rng.randint(0, 90),
        )
    return (
        rng.randint(160, 255),
        rng.randint(160, 255),
        rng.randint(160, 255),
    )


def _draw_captcha_text(
    text: str,
    rng: random.Random,
    width: int,
    height: int,
) -> np.ndarray:
    image = np.full((height, width, 3), rng.randint(200, 255), dtype=np.uint8)
    # تدرّج خفيف في الخلفية
    gradient = np.linspace(0, rng.randint(10, 40), width, dtype=np.uint8)
    image[:, :, 0] = np.clip(image[:, :, 0] - gradient, 0, 255)

    n = max(1, len(text))
    slot = max(10, int(width * 0.85 / n))
    x = max(4, (width - slot * n) // 2)
    for ch in text:
        scale = rng.uniform(0.8, 1.3) * (height / 60.0)
        thickness = rng.randint(1, 3)
        color = _random_color(rng)
        y = int(height * 0.72 + rng.uniform(-height * 0.08, height * 0.08))
        cv2.putText(
            image, ch, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA
        )
        x += slot

    # خطوط تشويش
    for _ in range(rng.randint(1, 5)):
        p1 = (rng.randint(0, width), rng.randint(0, height))
        p2 = (rng.randint(0, width), rng.randint(0, height))
        cv2.line(image, p1, p2, _random_color(rng), rng.randint(1, 2), cv2.LINE_AA)

    # ضوضاء نقطية
    noise_ratio = rng.uniform(0.0, 0.02)
    if noise_ratio > 0:
        mask = np.random.random((height, width)) < noise_ratio
        image[mask] = np.random.randint(0, 255, (int(mask.sum()), 3), dtype=np.uint8)

    # دوران بسيط
    angle = rng.uniform(-12, 12)
    center = (width / 2.0, height / 2.0)
    matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
    image = cv2.warpAffine(
        image,
        matrix,
        (width, height),
        borderMode=cv2.BORDER_REPLICATE,
    )

    # تشويش غاوسي
    if rng.random() < 0.6:
        sigma = rng.uniform(1.0, 8.0)
        image = cv2.GaussianBlur(image, (3, 3), sigma)
    return image


def generate_sample(
    length: int = 4,
    charset: str = DEFAULT_CHARSET,
    width: int = 160,
    height: int = 60,
    seed: Optional[int] = None,
) -> Tuple[np.ndarray, str]:
    """يُولّد صورة كبتشا واحدة مع نصها الصحيح.

    Returns:
        (صورة BGR كمصفوفة numpy, النص الصحيح)
    """
    rng = random.Random(seed)
    np.random.seed(seed if seed is not None else random.randint(0, 2**32 - 1))
    length = max(1, min(int(length), len(charset)))
    text = "".join(rng.choice(charset) for _ in range(length))
    return _draw_captcha_text(text, rng, width, height), text


def encode_png(image: np.ndarray) -> bytes:
    """يُشفّر صورة إلى بايتات PNG."""
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise ValueError("تعذّر ترميز الصورة")
    return buf.tobytes()


def generate_batch(
    count: int = 10,
    length: int = 4,
    charset: str = DEFAULT_CHARSET,
    width: int = 160,
    height: int = 60,
    seed: Optional[int] = None,
) -> List[Dict[str, object]]:
    """يُولّد دفعة من العينات، كل عينة مع بايتات PNG جاهزة للإرجاع.

    Returns:
        قائمة من ``{"text", "length", "png_base64", "width", "height"}``.
    """
    import base64

    count = max(1, min(int(count), 200))
    out: List[Dict[str, object]] = []
    for i in range(count):
        item_seed = None if seed is None else seed + i
        image, text = generate_sample(
            length=length, charset=charset, width=width, height=height, seed=item_seed
        )
        out.append(
            {
                "text": text,
                "length": len(text),
                "png_base64": base64.b64encode(encode_png(image)).decode("ascii"),
                "width": int(image.shape[1]),
                "height": int(image.shape[0]),
            }
        )
    return out


__all__ = [
    "DEFAULT_CHARSET",
    "generate_sample",
    "generate_batch",
    "encode_png",
]
