#!/usr/bin/env python3
"""نقطة دخول أداة سطر الأوامر."""
import sys

try:
    from .nonecap_cli import main
except ImportError:  # تشغيل مباشر: python cli/__main__.py
    from nonecap_cli import main

if __name__ == "__main__":
    sys.exit(main())
