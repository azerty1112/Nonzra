"""توافق: يمنع استيراد الحزمة على إصدارات بايثون غير مدعومة برسالة واضحة.

السبب: بيئة CI على Ubuntu 26.04 لم تعد توفّر Python 3.9/3.10، والمشروع يعتمد
فعليًا على `rapidocr-onnxruntime` و`onnxruntime` اللذين يحتاجان ≥3.11. بدل فشل
غامض عند تثبيت الحزم، نُعطي رسالة صريحة تحمل الحل.
"""

import sys

if sys.version_info < (3, 11):  # pragma: no cover - يعتمد على بيئة التشغيل
    raise ImportError(
        "Nonecap يحتاج Python 3.11 أو أحدث "
        f"(الإصدار الحالي {sys.version_info.major}.{sys.version_info.minor}). "
        "المحرّك العصبي rapidocr-onnxruntime لا يدعم ما قبله. "
        "ثبّت 3.11+: https://www.python.org/downloads/"
    )

__all__ = ["__version__"]
__version__ = "0.8.0"
