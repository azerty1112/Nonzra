"""معالجة الصور المسبقة لتحسين دقة حل الكبتشا."""

from typing import List, Tuple
import numpy as np
import cv2
from PIL import Image, ImageOps, ImageFilter, ImageEnhance


def load_image(path: str) -> np.ndarray:
    """تحميل صورة من مسار إلى مصفوفة Numpy (BGR)."""
    image = cv2.imread(path, cv2.IMREAD_COLOR)
    if image is None:
        raise FileNotFoundError(f"لا يمكن تحميل الصورة: {path}")
    return image


def load_image_bytes(data: bytes) -> np.ndarray:
    """تحميل صورة من بايتات إلى مصفوفة Numpy (BGR)."""
    nparr = np.frombuffer(data, np.uint8)
    image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("بيانات الصورة غير صالحة")
    return image


def to_gray(image: np.ndarray) -> np.ndarray:
    """تحويل الصورة إلى رمادي."""
    return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)


def resize(image: np.ndarray, width: int = 0, height: int = 0) -> np.ndarray:
    """تغيير حجم الصورة مع الحفاظ على النسبة."""
    h, w = image.shape[:2]
    if width and height:
        return cv2.resize(image, (width, height), interpolation=cv2.INTER_CUBIC)
    if width:
        r = width / float(w)
        return cv2.resize(image, (width, int(h * r)), interpolation=cv2.INTER_CUBIC)
    if height:
        r = height / float(h)
        return cv2.resize(image, (int(w * r), height), interpolation=cv2.INTER_CUBIC)
    return image


def threshold_otsu(image: np.ndarray) -> np.ndarray:
    """عتبة أوتسو لتحويل الصورة إلى أبيض وأسود."""
    if len(image.shape) == 3:
        image = to_gray(image)
    _, th = cv2.threshold(image, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return th


def adaptive_threshold(image: np.ndarray) -> np.ndarray:
    """عتبة متكيفة للتعامل مع الخلفيات غير المتساوية."""
    if len(image.shape) == 3:
        image = to_gray(image)
    return cv2.adaptiveThreshold(
        image, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
    )


def remove_noise(image: np.ndarray, ksize: int = 3) -> np.ndarray:
    """إزالة الضوضاء باستخدام median blur."""
    return cv2.medianBlur(image, ksize)


def dilate(image: np.ndarray, iterations: int = 1) -> np.ndarray:
    """تكبير السمك (Dilation)."""
    kernel = np.ones((3, 3), np.uint8)
    return cv2.dilate(image, kernel, iterations=iterations)


def erode(image: np.ndarray, iterations: int = 1) -> np.ndarray:
    """تآكل السمك (Erosion)."""
    kernel = np.ones((3, 3), np.uint8)
    return cv2.erode(image, kernel, iterations=iterations)


def deskew(image: np.ndarray) -> np.ndarray:
    """تعديل إمالة النص."""
    if len(image.shape) == 3:
        gray = to_gray(image)
    else:
        gray = image
    coords = np.column_stack(np.where(gray > 0))
    if coords.size == 0:
        return image
    angle = cv2.minAreaRect(coords)[-1]
    if angle < -45:
        angle = -(90 + angle)
    else:
        angle = -angle
    (h, w) = gray.shape[:2]
    center = (w // 2, h // 2)
    M = cv2.getRotationMatrix2D(center, angle, 1.0)
    return cv2.warpAffine(
        image, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )


def preprocess_pipeline(
    image: np.ndarray,
    grayscale: bool = True,
    denoise: bool = True,
    threshold: str = "otsu",
    resize_width: int = 0,
    resize_height: int = 0,
    deskew_flag: bool = False,
) -> np.ndarray:
    """أنابيب معالجة مسبقة متكاملة."""
    img = image
    if resize_width or resize_height:
        img = resize(img, resize_width, resize_height)
    if grayscale:
        img = to_gray(img)
    if denoise:
        img = remove_noise(img, 3)
    if threshold == "otsu":
        img = threshold_otsu(img)
    elif threshold == "adaptive":
        img = adaptive_threshold(img)
    elif threshold == "none":
        pass
    else:
        img = threshold_otsu(img)
    if deskew_flag:
        img = deskew(img)
    return img


def to_pil(image: np.ndarray) -> Image.Image:
    """تحويل مصفوفة Numpy إلى صورة PIL."""
    if len(image.shape) == 2:
        return Image.fromarray(image)
    return Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))


def enhance_for_ocr(image: Image.Image) -> Image.Image:
    """تحسين الصورة لـ OCR (تباين، حدة)."""
    img = ImageOps.grayscale(image)
    img = ImageEnhance.Contrast(img).enhance(2.0)
    img = ImageEnhance.Sharpness(img).enhance(2.0)
    img = img.filter(ImageFilter.MedianFilter(size=3))
    return img


def segment_characters(
    image: np.ndarray, min_width: int = 5, min_height: int = 15
) -> List[Tuple[int, int, int, int]]:
    """تقطيع الصورة إلى نطاقات حروف مرشحة."""
    if len(image.shape) == 3:
        gray = to_gray(image)
    else:
        gray = image
    _, th = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for cnt in contours:
        x, y, w, h = cv2.boundingRect(cnt)
        if w >= min_width and h >= min_height:
            boxes.append((x, y, w, h))
    boxes.sort(key=lambda b: b[0])
    return boxes
