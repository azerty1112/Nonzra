#!/usr/bin/env bash
# تثبيت وتشغيل NoneCap Clone بسرعة
set -e

echo "=== تثبيت الاعتمادات ==="
pip install -r api_server/requirements.txt

echo "=== تشغيل السيرفر ==="
uvicorn api_server.main:app --host 0.0.0.0 --port 8000
