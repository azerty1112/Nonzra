#!/usr/bin/env bash
# النشر السريع باستخدام دوكير كومبوز (بما في ذلك Base URL مخصص)
set -e

echo "=== بناء وتشغيل NoneCap Clone ==="
docker compose up --build -d

echo "=== انتظار بدء السيرفر ==="
for i in $(seq 1 30); do
  if curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "السيرفر يعمل على http://localhost:8000"
    echo "لوحة التحكم: http://localhost:8000/dashboard"
    echo "المقاييس: http://localhost:8000/metrics"
    exit 0
  fi
  sleep 1
done

echo "فشل بدء السيرفر"
exit 1
