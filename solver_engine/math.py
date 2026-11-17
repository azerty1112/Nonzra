"""حلّال كبتشا العمليات الحسابية: قراءة التعبير (OCR) ثم حسابه بأمان.

يدعم التعبيرات مثل ``5 + 3`` و ``12-4`` و ``7 × 2`` و ``9 ÷ 3``
مع تطبيع الرموز الشائعة (×، x، ÷، ، الخ) وحساب النتيجة بدون ``eval``.
"""

import ast
import operator
import re
import time
import unicodedata
from typing import Any, Optional, Tuple

import numpy as np
import pytesseract

from .base import BaseSolver, CaptchaType, SolverResult
from .preprocess import (
    enhance_for_ocr,
    load_image,
    load_image_bytes,
    preprocess_pipeline,
    to_pil,
)

# الرموز التي قد تظهر بدلًا من العمليات الحسابية
_OPERATOR_MAP = {
    "×": "*",
    "x": "*",
    "X": "*",
    "·": "*",
    "•": "*",
    "÷": "/",
    ":": "/",
    "−": "-",
    "–": "-",
    "—": "-",
    "+": "+",
    "=": "",
    "?": "",
    "؟": "",
}

_ALLOWED_CHARS = set("0123456789+-*/(). ")

_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


class _SafeMathError(ValueError):
    """تعبير حسابي غير مدعوم أو غير آمن."""


def _eval_node(node: ast.AST) -> float:
    """تقييم آمن لعقد AST الحسابية فقط (بدون استدعاءات أو أسماء)."""
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return float(node.value)
        raise _SafeMathError("قيمة غير مدعومة في التعبير")
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _eval_node(node.left)
        right = _eval_node(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 8:
            raise _SafeMathError("أُس كبير غير مسموح")
        if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
            raise _SafeMathError("قسمة على صفر")
        return _BIN_OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_eval_node(node.operand))
    raise _SafeMathError("تعبير غير مسموح")


def evaluate_expression(expression: str) -> Tuple[bool, Optional[float], Optional[str]]:
    """يحسب تعبيرًا حسابيًا بأمان.

    Returns:
        (نجاح, النتيجة, رسالة الخطأ)
    """
    try:
        tree = ast.parse(expression, mode="eval")
        value = _eval_node(tree)
    except _SafeMathError as exc:
        return False, None, str(exc)
    except Exception as exc:  # noqa: BLE001
        return False, None, f"تعذر تحليل التعبير: {exc}"
    return True, value, None


def normalize_expression(text: str) -> str:
    """تطبيع نص OCR إلى تعبير حسابي قابل للحساب."""
    if not text:
        return ""
    # توحيد الأرقام العربية/الفارسية
    normalized = "".join(
        str(unicodedata.digit(ch)) if ch.isdigit() and not ch.isascii() else ch
        for ch in text
    )
    for src, dst in _OPERATOR_MAP.items():
        normalized = normalized.replace(src, dst)
    normalized = normalized.replace("=", "")
    # إصلاح أخطاء OCR الشائعة بين الأرقام والحروف
    normalized = normalized.replace("O", "0").replace("o", "0")
    normalized = normalized.replace("l", "1").replace("I", "1").replace("|", "1")
    normalized = normalized.replace("S", "5").replace("s", "5")
    normalized = normalized.replace("B", "8").replace("Z", "2").replace("z", "2")
    normalized = "".join(ch for ch in normalized if ch in _ALLOWED_CHARS)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def format_number(value: float) -> str:
    """تنسيق النتيجة: عدد صحيح بدون كسور، وإلا بمنزلتين عشريتين كحد أقصى."""
    if abs(value - round(value)) < 1e-9:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


class MathSolver(BaseSolver):
    """يحل كبتشا الرياضيات: يقرأ ``5 + 3`` ويعيد ``8``."""

    captcha_type = CaptchaType.MATH

    def __init__(self, psm: int = 7, oem: int = 3) -> None:
        self.psm = psm
        self.oem = oem

    def _read_text(self, image: np.ndarray) -> Tuple[str, str, float]:
        """يقرأ التعبير من الصورة ويعيد (النص الخام, الطريقة, الثقة)."""
        processed = preprocess_pipeline(
            image,
            grayscale=True,
            denoise=True,
            threshold="otsu",
            resize_width=400,
        )
        pil_image = enhance_for_ocr(to_pil(processed))
        config = f"--psm {self.psm} --oem {self.oem}"
        raw = ""
        try:
            raw = pytesseract.image_to_string(pil_image, config=config)
        except Exception:  # noqa: BLE001
            raw = ""
        raw = raw.strip()
        if raw:
            cleaned = normalize_expression(raw)
            # تحقق أن القراءة تحتوي عملية حسابية واحدة على الأقل
            if cleaned and re.search(r"[0-9]\s*[-+*/]\s*[0-9]", cleaned):
                return raw, "tesseract", 0.8

        # حل احتياطي: قراءة بأوضاع psm متعددة واختيار أول تعبير صالح
        for alt_psm in (6, 8, 13):
            try:
                alt = pytesseract.image_to_string(
                    pil_image, config=f"--psm {alt_psm} --oem {self.oem}"
                ).strip()
            except Exception:  # noqa: BLE001
                continue
            cleaned = normalize_expression(alt)
            if cleaned and re.search(r"[0-9]\s*[-+*/]\s*[0-9]", cleaned):
                return alt, f"tesseract_psm{alt_psm}", 0.65

        return raw, "tesseract_raw", 0.0

    def solve(
        self,
        image_path: Optional[str] = None,
        image_bytes: Optional[bytes] = None,
        **kwargs: Any,
    ) -> SolverResult:
        start = time.time()
        try:
            if image_bytes is not None:
                image = load_image_bytes(image_bytes)
            elif image_path is not None:
                image = load_image(image_path)
            else:
                return SolverResult(
                    success=False,
                    captcha_type=self.captcha_type,
                    error="يجب توفير image_path أو image_bytes",
                    response_time_ms=0,
                )

            raw, method, read_confidence = self._read_text(image)
            expression = normalize_expression(raw)
            elapsed = int((time.time() - start) * 1000)

            if not expression:
                return SolverResult(
                    success=False,
                    captcha_type=self.captcha_type,
                    error="لم يتم التعرف على أي تعبير حسابي",
                    response_time_ms=elapsed,
                    metadata={"raw_text": raw, "method": method},
                )

            ok, value, error = evaluate_expression(expression)
            if not ok or value is None:
                # قد يحتوي النص على أرقام زائدة: جرّب آخر تعبير فرعي صالح
                for match in re.finditer(r"\d+\s*[-+*/]\s*\d+", expression):
                    ok, value, error = evaluate_expression(match.group(0))
                    if ok and value is not None:
                        expression = match.group(0)
                        break
            if not ok or value is None:
                return SolverResult(
                    success=False,
                    captcha_type=self.captcha_type,
                    error=error or "تعبير حسابي غير صالح",
                    response_time_ms=int((time.time() - start) * 1000),
                    metadata={"expression": expression, "raw_text": raw, "method": method},
                )

            answer = format_number(value)
            confidence = read_confidence
            # ثقة أعلى عندما تكون القراءة نظيفة تمامًا
            if re.fullmatch(r"[0-9+\-*/(). ]+", expression) and method == "tesseract":
                confidence = min(0.95, confidence + 0.1)

            return SolverResult(
                success=True,
                captcha_type=self.captcha_type,
                text=answer,
                confidence=confidence,
                response_time_ms=int((time.time() - start) * 1000),
                metadata={
                    "expression": expression,
                    "result": value,
                    "raw_text": raw,
                    "method": method,
                },
            )
        except Exception as exc:  # noqa: BLE001
            return SolverResult(
                success=False,
                captcha_type=self.captcha_type,
                error=str(exc),
                response_time_ms=int((time.time() - start) * 1000),
            )

    async def solve_async(self, *args: Any, **kwargs: Any) -> SolverResult:
        import asyncio

        return await asyncio.to_thread(self.solve, *args, **kwargs)


__all__ = [
    "MathSolver",
    "evaluate_expression",
    "normalize_expression",
    "format_number",
]
